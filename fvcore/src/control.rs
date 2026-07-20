//! Integrated HTTP control plane and minimal status page.

use crate::{
    BooruOriginalFetchRequest, ContentMd5, CoreError, CoreHandle, EhPageFetchRequest, ErrorCode,
    EventStreamItem, FakeOperationRequest, OperationId, PixivPageFetchRequest, RuntimeState,
};
use axum::{
    Json, Router,
    body::Body,
    extract::{Path, Query, State},
    http::{HeaderValue, StatusCode, header},
    response::{IntoResponse, Response, Sse, sse::Event},
    routing::{get, post},
};
use serde::{Deserialize, Serialize};
use std::{convert::Infallible, net::SocketAddr, str::FromStr, time::Duration};
use tokio::{net::TcpListener, task::JoinHandle};
use tokio_util::sync::CancellationToken;

pub(crate) struct ControlServer {
    pub(crate) listen: SocketAddr,
    pub(crate) task: JoinHandle<()>,
}

#[derive(Clone)]
pub(crate) struct ControlState {
    pub(crate) core: CoreHandle,
}

#[derive(Serialize)]
struct ErrorBody<'a> {
    code: &'a str,
    message: &'a str,
    retryable: bool,
}

#[derive(Deserialize)]
struct EventQuery {
    #[serde(default)]
    cursor: u64,
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct BooruSearchQuery {
    tags: String,
    page: u64,
    limit: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EhHomeQuery {
    direction: Option<crate::EhPageDirection>,
    gid: Option<u64>,
}

#[derive(Default, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct EhThumbnailQuery {
    page: u32,
}

impl Default for BooruSearchQuery {
    fn default() -> Self {
        Self {
            tags: String::new(),
            page: 1,
            limit: 40,
        }
    }
}

pub(crate) async fn start(
    listen: SocketAddr,
    webui_enabled: bool,
    core: CoreHandle,
    shutdown: CancellationToken,
) -> Result<ControlServer, CoreError> {
    let listener = TcpListener::bind(listen).await.map_err(|error| {
        CoreError::new(
            ErrorCode::Io,
            format!("failed to bind HTTP control plane at {listen}: {error}"),
            false,
        )
    })?;
    let actual_listen = listener.local_addr().map_err(|error| {
        CoreError::new(
            ErrorCode::Io,
            format!("failed to inspect HTTP control address: {error}"),
            false,
        )
    })?;
    let state = ControlState { core };
    let mut router = Router::new()
        .route("/health/live", get(liveness))
        .route("/health/ready", get(readiness))
        .route("/api/v1/runtime", get(runtime_snapshot))
        .route("/api/v1/profiles", get(list_profiles))
        .route(
            "/api/v1/profiles/{provider}/{profile}/probe",
            post(probe_profile),
        )
        .route(
            "/api/v1/providers/danbooru/{profile}/posts",
            get(search_danbooru),
        )
        .route(
            "/api/v1/providers/danbooru/{profile}/posts/{post_id}",
            get(get_danbooru_post),
        )
        .route(
            "/api/v1/providers/gelbooru/{profile}/posts",
            get(search_gelbooru),
        )
        .route(
            "/api/v1/providers/gelbooru/{profile}/posts/{post_id}",
            get(get_gelbooru_post),
        )
        .route(
            "/api/v1/providers/{provider}/{profile}/posts/{post_id}/original/fetch",
            post(start_booru_original_fetch),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/illusts/{illust_id}",
            get(get_pixiv_illust),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/illusts/{illust_id}/pages/{page}/fetch",
            post(start_pixiv_page_fetch),
        )
        .route(
            "/api/v1/resources/images/{digest}/{extension}",
            get(get_image_resource),
        )
        .route("/api/v1/providers/eh/{profile}/galleries", get(get_eh_home))
        .route(
            "/api/v1/providers/eh/{profile}/galleries/{gid}/{token}",
            get(get_eh_gallery_detail),
        )
        .route(
            "/api/v1/providers/eh/{profile}/galleries/{gid}/{token}/thumbnails",
            get(get_eh_thumbnails),
        )
        .route(
            "/api/v1/providers/eh/{profile}/galleries/{gid}/{token}/pages/{page}/fetch",
            post(start_eh_page_fetch),
        )
        .route(
            "/api/v1/providers/eh/{profile}/galleries/{gid}/{token}/archives",
            get(get_eh_archive_options),
        )
        .route(
            "/api/v1/providers/eh/{profile}/galleries/{gid}/{token}/archives/{variant}/download",
            post(start_eh_archive_download),
        )
        .route("/api/v1/archive-tasks", get(list_archive_tasks))
        .route("/api/v1/local-galleries", get(list_local_galleries))
        .route(
            "/api/v1/local-galleries/{id}/comic-info",
            post(generate_local_gallery_comic_info).delete(delete_local_gallery_comic_info),
        )
        .route("/api/v1/archive-tasks/{id}", get(get_archive_task))
        .route(
            "/api/v1/archive-tasks/{id}/cancel",
            post(cancel_archive_task),
        )
        .route("/api/v1/archive-tasks/{id}/retry", post(retry_archive_task))
        .route(
            "/api/v1/operations",
            get(list_operations).post(start_fake_operation),
        )
        .route("/api/v1/operations/{id}", get(get_operation))
        .route("/api/v1/operations/{id}/cancel", post(cancel_operation))
        .route("/api/v1/events", get(events));
    if webui_enabled {
        router = router.merge(crate::webui::routes());
    }
    let router = router.with_state(state);
    let task = tokio::spawn(async move {
        if let Err(error) = axum::serve(listener, router)
            .with_graceful_shutdown(shutdown.cancelled_owned())
            .await
        {
            tracing::error!(%error, "HTTP control plane stopped unexpectedly");
        }
    });
    Ok(ControlServer {
        listen: actual_listen,
        task,
    })
}

async fn liveness() -> Response {
    text_response(StatusCode::OK, "ok\n")
}

async fn readiness(State(state): State<ControlState>) -> Response {
    match state.core.state() {
        RuntimeState::Ready => text_response(StatusCode::OK, "ready\n"),
        RuntimeState::Starting => text_response(StatusCode::SERVICE_UNAVAILABLE, "starting\n"),
        RuntimeState::Stopping => text_response(StatusCode::SERVICE_UNAVAILABLE, "stopping\n"),
        RuntimeState::Stopped => text_response(StatusCode::SERVICE_UNAVAILABLE, "stopped\n"),
    }
}

async fn runtime_snapshot(State(state): State<ControlState>) -> Response {
    match state.core.snapshot().await {
        Ok(snapshot) => with_security_headers(Json(snapshot).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn list_operations(State(state): State<ControlState>) -> Response {
    match state.core.operations().await {
        Ok(operations) => with_security_headers(Json(operations).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn list_profiles(State(state): State<ControlState>) -> Response {
    match state.core.profiles() {
        Ok(profiles) => with_security_headers(Json(profiles).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn probe_profile(
    State(state): State<ControlState>,
    Path((provider, profile)): Path<(String, String)>,
) -> Response {
    let key = crate::ProfileKey::new(provider, profile);
    match state.core.probe_profile(&key).await {
        Ok(probe) => with_security_headers(Json(probe).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn search_danbooru(
    State(state): State<ControlState>,
    Path(profile): Path<String>,
    Query(query): Query<BooruSearchQuery>,
) -> Response {
    let key = crate::ProfileKey::new("danbooru", profile);
    match state
        .core
        .search_danbooru(&key, &query.tags, query.page, query.limit)
        .await
    {
        Ok(result) => with_security_headers(Json(result).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn get_danbooru_post(
    State(state): State<ControlState>,
    Path((profile, post_id)): Path<(String, u64)>,
) -> Response {
    let key = crate::ProfileKey::new("danbooru", profile);
    match state.core.danbooru_post(&key, post_id).await {
        Ok(post) => with_security_headers(Json(post).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn search_gelbooru(
    State(state): State<ControlState>,
    Path(profile): Path<String>,
    Query(query): Query<BooruSearchQuery>,
) -> Response {
    let key = crate::ProfileKey::new("gelbooru", profile);
    match state
        .core
        .search_gelbooru(&key, &query.tags, query.page, query.limit)
        .await
    {
        Ok(result) => with_security_headers(Json(result).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn get_gelbooru_post(
    State(state): State<ControlState>,
    Path((profile, post_id)): Path<(String, u64)>,
) -> Response {
    let key = crate::ProfileKey::new("gelbooru", profile);
    match state.core.gelbooru_post(&key, post_id).await {
        Ok(post) => with_security_headers(Json(post).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn start_booru_original_fetch(
    State(state): State<ControlState>,
    Path((provider, profile, post_id)): Path<(String, String, u64)>,
) -> Response {
    match state
        .core
        .start_booru_original_fetch(BooruOriginalFetchRequest {
            profile: crate::ProfileKey::new(provider, profile),
            post_id,
        })
        .await
    {
        Ok(operation) => {
            with_security_headers((StatusCode::ACCEPTED, Json(operation)).into_response())
        }
        Err(error) => error_response(&error),
    }
}

async fn get_pixiv_illust(
    State(state): State<ControlState>,
    Path((profile, illust_id)): Path<(String, String)>,
) -> Response {
    match state
        .core
        .pixiv_illust(&crate::ProfileKey::new("pixiv", profile), &illust_id)
        .await
    {
        Ok(illust) => with_security_headers(Json(illust).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn start_pixiv_page_fetch(
    State(state): State<ControlState>,
    Path((profile, illust_id, page)): Path<(String, String, u32)>,
) -> Response {
    match state
        .core
        .start_pixiv_page_fetch(PixivPageFetchRequest {
            profile: crate::ProfileKey::new("pixiv", profile),
            illust_id,
            page,
        })
        .await
    {
        Ok(operation) => {
            with_security_headers((StatusCode::ACCEPTED, Json(operation)).into_response())
        }
        Err(error) => error_response(&error),
    }
}

async fn get_image_resource(
    State(state): State<ControlState>,
    Path((digest, extension)): Path<(String, String)>,
) -> Response {
    let digest = match ContentMd5::from_str(&digest) {
        Ok(digest) => digest,
        Err(error) => return error_response(&error),
    };
    match state.core.image_resource(digest, &extension).await {
        Ok(resource) => {
            let Ok(content_type) = HeaderValue::from_str(&resource.descriptor().mime_type) else {
                return error_response(&CoreError::new(
                    ErrorCode::Internal,
                    "image resource has an invalid MIME type",
                    false,
                ));
            };
            let mut response = Response::new(Body::from(resource.bytes()));
            *response.status_mut() = StatusCode::OK;
            response
                .headers_mut()
                .insert(header::CONTENT_TYPE, content_type);
            response.headers_mut().insert(
                header::CACHE_CONTROL,
                HeaderValue::from_static("public, max-age=31536000, immutable"),
            );
            response.headers_mut().insert(
                header::ETAG,
                HeaderValue::from_str(&format!("\"{}\"", resource.descriptor().content_md5))
                    .expect("MD5 ETag is valid"),
            );
            with_resource_security_headers(response)
        }
        Err(error) => error_response(&error),
    }
}

async fn get_eh_archive_options(
    State(state): State<ControlState>,
    Path((profile, gid, token)): Path<(String, u64, String)>,
) -> Response {
    let key = crate::ProfileKey::new("eh", profile);
    match state
        .core
        .eh_archive_options(&key, crate::EhGalleryRef { gid, token })
        .await
    {
        Ok(options) => with_security_headers(Json(options).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn start_eh_archive_download(
    State(state): State<ControlState>,
    Path((profile, gid, token, variant)): Path<(String, u64, String, String)>,
) -> Response {
    let variant = match variant.as_str() {
        "original" => crate::EhArchiveVariant::Original,
        "resample" => crate::EhArchiveVariant::Resample,
        _ => {
            return error_response(&CoreError::new(
                ErrorCode::InvalidInput,
                "EH Archive variant must be original or resample",
                false,
            ));
        }
    };
    match state
        .core
        .start_eh_archive_download(crate::EhArchiveDownloadRequest {
            profile: crate::ProfileKey::new("eh", profile),
            gallery: crate::EhGalleryRef { gid, token },
            variant,
        })
        .await
    {
        Ok(task) => with_security_headers((StatusCode::ACCEPTED, Json(task)).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn list_archive_tasks(State(state): State<ControlState>) -> Response {
    with_security_headers(Json(state.core.archive_tasks().await).into_response())
}

async fn list_local_galleries(State(state): State<ControlState>) -> Response {
    with_security_headers(Json(state.core.local_galleries().await).into_response())
}

async fn generate_local_gallery_comic_info(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_local_gallery_id()),
    };
    match state.core.generate_local_gallery_comic_info(id).await {
        Ok(snapshot) => with_security_headers(Json(snapshot).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn delete_local_gallery_comic_info(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_local_gallery_id()),
    };
    match state.core.delete_local_gallery_comic_info(id).await {
        Ok(()) => with_security_headers(StatusCode::NO_CONTENT.into_response()),
        Err(error) => error_response(&error),
    }
}

async fn get_archive_task(State(state): State<ControlState>, Path(id): Path<String>) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_archive_task_id()),
    };
    match state.core.archive_task(id).await {
        Ok(task) => with_security_headers(Json(task).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn cancel_archive_task(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_archive_task_id()),
    };
    match state.core.cancel_archive_task(id).await {
        Ok(task) => with_security_headers(Json(task).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn retry_archive_task(State(state): State<ControlState>, Path(id): Path<String>) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_archive_task_id()),
    };
    match state.core.retry_archive_task(id).await {
        Ok(task) => with_security_headers(Json(task).into_response()),
        Err(error) => error_response(&error),
    }
}

fn invalid_archive_task_id() -> CoreError {
    CoreError::new(
        ErrorCode::InvalidInput,
        "Archive task ID must be a valid UUID",
        false,
    )
}

fn invalid_local_gallery_id() -> CoreError {
    CoreError::new(
        ErrorCode::InvalidInput,
        "local gallery ID must be a valid UUID",
        false,
    )
}

async fn get_eh_gallery_detail(
    State(state): State<ControlState>,
    Path((profile, gid, token)): Path<(String, u64, String)>,
) -> Response {
    let key = crate::ProfileKey::new("eh", profile);
    match state
        .core
        .eh_gallery_detail(&key, crate::EhGalleryRef { gid, token })
        .await
    {
        Ok(detail) => with_security_headers(Json(detail).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn get_eh_thumbnails(
    State(state): State<ControlState>,
    Path((profile, gid, token)): Path<(String, u64, String)>,
    Query(query): Query<EhThumbnailQuery>,
) -> Response {
    let key = crate::ProfileKey::new("eh", profile);
    match state
        .core
        .eh_thumbnails(&key, crate::EhGalleryRef { gid, token }, query.page)
        .await
    {
        Ok(page) => with_security_headers(Json(page).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn start_eh_page_fetch(
    State(state): State<ControlState>,
    Path((profile, gid, token, page)): Path<(String, u64, String, u32)>,
) -> Response {
    match state
        .core
        .start_eh_page_fetch(EhPageFetchRequest {
            profile: crate::ProfileKey::new("eh", profile),
            gallery: crate::EhGalleryRef { gid, token },
            page,
            nl: None,
        })
        .await
    {
        Ok(operation) => {
            with_security_headers((StatusCode::ACCEPTED, Json(operation)).into_response())
        }
        Err(error) => error_response(&error),
    }
}

async fn get_eh_home(
    State(state): State<ControlState>,
    Path(profile): Path<String>,
    Query(query): Query<EhHomeQuery>,
) -> Response {
    let cursor = match (query.direction, query.gid) {
        (None, None) => None,
        (Some(direction), Some(gid)) => Some(crate::EhPageCursor { direction, gid }),
        _ => {
            return error_response(&CoreError::new(
                ErrorCode::InvalidInput,
                "EH direction and gid must be supplied together",
                false,
            ));
        }
    };
    let key = crate::ProfileKey::new("eh", profile);
    match state.core.eh_home(&key, cursor).await {
        Ok(page) => with_security_headers(Json(page).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn start_fake_operation(
    State(state): State<ControlState>,
    Json(request): Json<FakeOperationRequest>,
) -> Response {
    match state.core.start_fake_operation(request).await {
        Ok(operation) => {
            with_security_headers((StatusCode::ACCEPTED, Json(operation)).into_response())
        }
        Err(error) => error_response(&error),
    }
}

async fn get_operation(State(state): State<ControlState>, Path(id): Path<String>) -> Response {
    let id = match parse_operation_id(&id) {
        Ok(id) => id,
        Err(error) => return error_response(&error),
    };
    match state.core.operation(id).await {
        Ok(operation) => with_security_headers(Json(operation).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn cancel_operation(State(state): State<ControlState>, Path(id): Path<String>) -> Response {
    let id = match parse_operation_id(&id) {
        Ok(id) => id,
        Err(error) => return error_response(&error),
    };
    match state.core.cancel_operation(id).await {
        Ok(operation) => with_security_headers(Json(operation).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn events(State(state): State<ControlState>, Query(query): Query<EventQuery>) -> Response {
    let mut subscription = match state.core.subscribe_events(query.cursor).await {
        Ok(subscription) => subscription,
        Err(error) => return error_response(&error),
    };
    let stream = async_stream::stream! {
        loop {
            match subscription.next().await {
                EventStreamItem::Event(core_event) => {
                    let event_name = match &core_event.subject {
                        crate::CoreEventSubject::Operation { .. } => "operation",
                        crate::CoreEventSubject::ArchiveTask { .. } => "archive_task",
                    };
                    let data = match serde_json::to_string(&core_event) {
                        Ok(data) => data,
                        Err(error) => {
                            tracing::error!(%error, "failed to serialize Core event");
                            break;
                        }
                    };
                    yield Ok::<Event, Infallible>(
                        Event::default()
                            .id(core_event.sequence.to_string())
                            .event(event_name)
                            .data(data)
                    );
                }
                EventStreamItem::ResyncRequired => {
                    yield Ok::<Event, Infallible>(Event::default().event("resync_required").data("{}"));
                    break;
                }
                EventStreamItem::Closed => break,
            }
        }
    };
    with_security_headers(
        Sse::new(stream)
            .keep_alive(
                axum::response::sse::KeepAlive::new()
                    .interval(Duration::from_secs(15))
                    .text("keep-alive"),
            )
            .into_response(),
    )
}

fn error_response(error: &CoreError) -> Response {
    let status = match error.code() {
        ErrorCode::InvalidInput => StatusCode::BAD_REQUEST,
        ErrorCode::NotReady => StatusCode::SERVICE_UNAVAILABLE,
        ErrorCode::Overloaded => StatusCode::TOO_MANY_REQUESTS,
        ErrorCode::OperationNotFound => StatusCode::NOT_FOUND,
        ErrorCode::OperationFinished => StatusCode::CONFLICT,
        ErrorCode::ProfileNotFound => StatusCode::NOT_FOUND,
        ErrorCode::ResourceNotFound => StatusCode::NOT_FOUND,
        ErrorCode::AuthenticationRequired => StatusCode::UNAUTHORIZED,
        ErrorCode::AccessDenied => StatusCode::FORBIDDEN,
        ErrorCode::RateLimited => StatusCode::TOO_MANY_REQUESTS,
        ErrorCode::ResponseTooLarge => StatusCode::PAYLOAD_TOO_LARGE,
        ErrorCode::RedirectDenied => StatusCode::BAD_GATEWAY,
        ErrorCode::IntegrityMismatch => StatusCode::BAD_GATEWAY,
        ErrorCode::InvalidConfig | ErrorCode::Parse => StatusCode::BAD_REQUEST,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    };
    with_security_headers(
        (
            status,
            Json(ErrorBody {
                code: error.code().as_str(),
                message: error.message(),
                retryable: error.retryable(),
            }),
        )
            .into_response(),
    )
}

fn parse_operation_id(input: &str) -> Result<OperationId, CoreError> {
    OperationId::from_str(input).map_err(|_| {
        CoreError::new(
            ErrorCode::InvalidInput,
            "operation ID must be a valid UUID",
            false,
        )
    })
}

fn text_response(status: StatusCode, body: &'static str) -> Response {
    with_security_headers(
        (
            status,
            [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
            body,
        )
            .into_response(),
    )
}

fn with_security_headers(mut response: Response) -> Response {
    let headers = response.headers_mut();
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    headers.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    headers.insert(
        header::CONTENT_SECURITY_POLICY,
        HeaderValue::from_static("default-src 'none'; style-src 'unsafe-inline'"),
    );
    headers.insert("x-frame-options", HeaderValue::from_static("DENY"));
    response
}

fn with_resource_security_headers(mut response: Response) -> Response {
    let headers = response.headers_mut();
    headers.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    headers.insert("x-frame-options", HeaderValue::from_static("DENY"));
    response
}
