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
struct BooruTagQuery {
    query: String,
    #[serde(default = "default_booru_tag_limit")]
    limit: u32,
}

fn default_booru_tag_limit() -> u32 {
    20
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EhHomeQuery {
    search: Option<String>,
    direction: Option<crate::EhPageDirection>,
    gid: Option<u64>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PixivSearchQuery {
    query: String,
    page: u32,
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct PixivRankingQuery {
    mode: String,
    date: String,
    page: u32,
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct PixivFollowingQuery {
    visibility: crate::PixivFollowingVisibility,
    page: u32,
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct PixivBookmarksQuery {
    visibility: crate::PixivBookmarkVisibility,
    offset: u32,
}

impl Default for PixivBookmarksQuery {
    fn default() -> Self {
        Self {
            visibility: crate::PixivBookmarkVisibility::Public,
            offset: 0,
        }
    }
}

impl Default for PixivFollowingQuery {
    fn default() -> Self {
        Self {
            visibility: crate::PixivFollowingVisibility::Public,
            page: 1,
        }
    }
}

impl Default for PixivRankingQuery {
    fn default() -> Self {
        Self {
            mode: "day".to_owned(),
            date: String::new(),
            page: 1,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FavoriteSearchInput {
    provider: String,
    profile: String,
    name: String,
    query: String,
}

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct LocalGalleryQuery {
    offset: u32,
    limit: u32,
}

impl Default for LocalGalleryQuery {
    fn default() -> Self {
        Self {
            offset: 0,
            limit: 100,
        }
    }
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
        .route("/api/v1/config", get(effective_config))
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
            "/api/v1/providers/{provider}/{profile}/posts",
            get(search_extended_booru),
        )
        .route(
            "/api/v1/providers/{provider}/{profile}/posts/{post_id}",
            get(get_extended_booru_post),
        )
        .route(
            "/api/v1/providers/{provider}/{profile}/posts/{post_id}/original/fetch",
            post(start_booru_original_fetch),
        )
        .route(
            "/api/v1/providers/{provider}/{profile}/posts/{post_id}/original/download",
            post(start_booru_image_download),
        )
        .route(
            "/api/v1/providers/{provider}/{profile}/tags",
            get(booru_tag_suggestions),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/illusts/{illust_id}",
            get(get_pixiv_illust),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/search",
            get(search_pixiv),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/ranking",
            get(pixiv_ranking),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/recommendations",
            get(pixiv_recommendations),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/following",
            get(pixiv_following),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/bookmarks",
            get(pixiv_bookmarks),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/illusts/{illust_id}/pages/{page}/fetch",
            post(start_pixiv_page_fetch),
        )
        .route(
            "/api/v1/providers/pixiv/{profile}/illusts/{illust_id}/pages/{page}/download",
            post(start_pixiv_image_download),
        )
        .route(
            "/api/v1/resources/images/{digest}/{extension}",
            get(get_image_resource),
        )
        .route(
            "/api/v1/cache/images",
            get(get_image_cache).post(maintain_image_cache),
        )
        .route("/api/v1/providers/eh/{profile}/galleries", get(get_eh_home))
        .route(
            "/api/v1/favorite-searches",
            get(list_favorite_searches).post(create_favorite_search),
        )
        .route(
            "/api/v1/favorite-searches/{id}",
            axum::routing::delete(delete_favorite_search),
        )
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
        .route(
            "/api/v1/image-download-tasks",
            get(list_image_download_tasks),
        )
        .route("/api/v1/download-tasks", get(list_download_tasks))
        .route("/api/v1/download-tasks/{id}", get(get_download_task))
        .route("/api/v1/local-galleries", get(list_local_galleries))
        .route(
            "/api/v1/local-gallery-inventory",
            get(local_gallery_inventory),
        )
        .route(
            "/api/v1/local-gallery-inventory/{id}/import",
            post(import_local_gallery),
        )
        .route("/api/v1/local-galleries/{id}", get(get_local_gallery))
        .route(
            "/api/v1/local-galleries/{id}/delete-preview",
            post(prepare_local_gallery_delete),
        )
        .route(
            "/api/v1/local-galleries/{id}/delete",
            post(delete_local_gallery),
        )
        .route(
            "/api/v1/local-galleries/{id}/cover",
            get(get_local_gallery_cover),
        )
        .route(
            "/api/v1/local-galleries/{id}/export",
            get(export_local_gallery),
        )
        .route(
            "/api/v1/local-galleries/{id}/pages/{page_id}",
            get(get_local_gallery_page),
        )
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
            "/api/v1/image-download-tasks/{id}",
            get(get_image_download_task).delete(delete_image_download_task),
        )
        .route(
            "/api/v1/image-download-tasks/{id}/cancel",
            post(cancel_image_download_task),
        )
        .route(
            "/api/v1/image-download-tasks/{id}/retry",
            post(retry_image_download_task),
        )
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

async fn get_image_cache(State(state): State<ControlState>) -> Response {
    match state.core.image_cache_snapshot().await {
        Ok(snapshot) => with_security_headers(Json(snapshot).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn maintain_image_cache(State(state): State<ControlState>) -> Response {
    match state.core.maintain_image_cache().await {
        Ok(result) => with_security_headers(Json(result).into_response()),
        Err(error) => error_response(&error),
    }
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

async fn effective_config(State(state): State<ControlState>) -> Response {
    match state.core.effective_config().await {
        Ok(config) => with_security_headers(Json(config).into_response()),
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

async fn search_extended_booru(
    State(state): State<ControlState>,
    Path((provider, profile)): Path<(String, String)>,
    Query(query): Query<BooruSearchQuery>,
) -> Response {
    let key = crate::ProfileKey::new(provider, profile);
    let result = if matches!(
        key.provider.as_str(),
        "yandere" | "konachan" | "konachan_net" | "lolibooru" | "behoimi"
    ) {
        state
            .core
            .search_moebooru(&key, &query.tags, query.page, query.limit)
            .await
    } else if matches!(key.provider.as_str(), "e621" | "e926") {
        state
            .core
            .search_e621(&key, &query.tags, query.page, query.limit)
            .await
    } else if matches!(key.provider.as_str(), "derpibooru" | "furbooru") {
        state
            .core
            .search_philomena(&key, &query.tags, query.page, query.limit)
            .await
    } else if key.provider == "paheal" {
        state
            .core
            .search_paheal(&key, &query.tags, query.page, query.limit)
            .await
    } else {
        state
            .core
            .search_gelbooru_xml(&key, &query.tags, query.page, query.limit)
            .await
    };
    match result {
        Ok(result) => with_security_headers(Json(result).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn get_extended_booru_post(
    State(state): State<ControlState>,
    Path((provider, profile, post_id)): Path<(String, String, u64)>,
) -> Response {
    let key = crate::ProfileKey::new(provider, profile);
    let result = if matches!(
        key.provider.as_str(),
        "yandere" | "konachan" | "konachan_net" | "lolibooru" | "behoimi"
    ) {
        state.core.moebooru_post(&key, post_id).await
    } else if matches!(key.provider.as_str(), "e621" | "e926") {
        state.core.e621_post(&key, post_id).await
    } else if matches!(key.provider.as_str(), "derpibooru" | "furbooru") {
        state.core.philomena_post(&key, post_id).await
    } else if key.provider == "paheal" {
        state.core.paheal_post(&key, post_id).await
    } else {
        state.core.gelbooru_xml_post(&key, post_id).await
    };
    match result {
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

async fn start_booru_image_download(
    State(state): State<ControlState>,
    Path((provider, profile, post_id)): Path<(String, String, u64)>,
) -> Response {
    match state
        .core
        .start_booru_image_download(crate::BooruImageDownloadRequest {
            profile: crate::ProfileKey::new(provider, profile),
            post_id,
        })
        .await
    {
        Ok(task) => with_security_headers((StatusCode::ACCEPTED, Json(task)).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn booru_tag_suggestions(
    State(state): State<ControlState>,
    Path((provider, profile)): Path<(String, String)>,
    Query(query): Query<BooruTagQuery>,
) -> Response {
    let key = crate::ProfileKey::new(provider, profile);
    match state
        .core
        .booru_tag_suggestions(&key, &query.query, query.limit)
        .await
    {
        Ok(result) => with_security_headers(Json(result).into_response()),
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

async fn search_pixiv(
    State(state): State<ControlState>,
    Path(profile): Path<String>,
    Query(query): Query<PixivSearchQuery>,
) -> Response {
    let key = crate::ProfileKey::new("pixiv", profile);
    match state
        .core
        .search_pixiv(&key, &query.query, query.page)
        .await
    {
        Ok(result) => with_security_headers(Json(result).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn pixiv_ranking(
    State(state): State<ControlState>,
    Path(profile): Path<String>,
    Query(query): Query<PixivRankingQuery>,
) -> Response {
    let key = crate::ProfileKey::new("pixiv", profile);
    match state
        .core
        .pixiv_ranking(&key, &query.mode, &query.date, query.page)
        .await
    {
        Ok(result) => with_security_headers(Json(result).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn pixiv_recommendations(
    State(state): State<ControlState>,
    Path(profile): Path<String>,
) -> Response {
    let key = crate::ProfileKey::new("pixiv", profile);
    match state.core.pixiv_recommendations(&key).await {
        Ok(result) => with_security_headers(Json(result).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn pixiv_following(
    State(state): State<ControlState>,
    Path(profile): Path<String>,
    Query(query): Query<PixivFollowingQuery>,
) -> Response {
    let key = crate::ProfileKey::new("pixiv", profile);
    match state
        .core
        .pixiv_following(&key, query.visibility, query.page)
        .await
    {
        Ok(result) => with_security_headers(Json(result).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn pixiv_bookmarks(
    State(state): State<ControlState>,
    Path(profile): Path<String>,
    Query(query): Query<PixivBookmarksQuery>,
) -> Response {
    let key = crate::ProfileKey::new("pixiv", profile);
    match state
        .core
        .pixiv_bookmarks(&key, query.visibility, query.offset)
        .await
    {
        Ok(result) => with_security_headers(Json(result).into_response()),
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

async fn start_pixiv_image_download(
    State(state): State<ControlState>,
    Path((profile, illust_id, page)): Path<(String, String, u32)>,
) -> Response {
    match state
        .core
        .start_pixiv_image_download(crate::PixivImageDownloadRequest {
            profile: crate::ProfileKey::new("pixiv", profile),
            illust_id,
            page,
        })
        .await
    {
        Ok(task) => with_security_headers((StatusCode::ACCEPTED, Json(task)).into_response()),
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

async fn list_image_download_tasks(State(state): State<ControlState>) -> Response {
    with_security_headers(Json(state.core.image_download_tasks().await).into_response())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DownloadTaskQuery {
    provider: Option<String>,
    kind: Option<String>,
}

async fn list_download_tasks(
    State(state): State<ControlState>,
    Query(query): Query<DownloadTaskQuery>,
) -> Response {
    with_security_headers(
        Json(
            state
                .core
                .download_tasks(query.provider.as_deref(), query.kind.as_deref())
                .await,
        )
        .into_response(),
    )
}

async fn get_download_task(State(state): State<ControlState>, Path(id): Path<String>) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_download_task_id()),
    };
    match state.core.download_task(id).await {
        Ok(task) => with_security_headers(Json(task).into_response()),
        Err(error) => error_response(&error),
    }
}

fn invalid_download_task_id() -> CoreError {
    CoreError::new(
        ErrorCode::InvalidInput,
        "Download task ID must be a valid UUID",
        false,
    )
}

async fn list_local_galleries(State(state): State<ControlState>) -> Response {
    match state.core.local_galleries().await {
        Ok(galleries) => with_security_headers(Json(galleries).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn local_gallery_inventory(State(state): State<ControlState>) -> Response {
    match state.core.local_gallery_inventory().await {
        Ok(inventory) => with_security_headers(Json(inventory).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn import_local_gallery(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match id.parse() {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_local_gallery_id()),
    };
    match state.core.import_local_gallery(id).await {
        Ok(gallery) => with_security_headers(Json(gallery).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn get_local_gallery(
    State(state): State<ControlState>,
    Path(id): Path<String>,
    Query(query): Query<LocalGalleryQuery>,
) -> Response {
    let id = match id.parse() {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_local_gallery_id()),
    };
    match state
        .core
        .local_gallery(id, query.offset, query.limit)
        .await
    {
        Ok(gallery) => with_security_headers(Json(gallery).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn get_local_gallery_page(
    State(state): State<ControlState>,
    Path((id, page_id)): Path<(String, u32)>,
) -> Response {
    let id = match id.parse() {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_local_gallery_id()),
    };
    match state.core.local_gallery_page(id, page_id).await {
        Ok(resource) => local_gallery_resource_response(resource),
        Err(error) => error_response(&error),
    }
}

async fn get_local_gallery_cover(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match id.parse() {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_local_gallery_id()),
    };
    match state.core.local_gallery_cover(id).await {
        Ok(resource) => local_gallery_resource_response(resource),
        Err(error) => error_response(&error),
    }
}

async fn export_local_gallery(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match id.parse() {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_local_gallery_id()),
    };
    match state.core.local_gallery_export(id).await {
        Ok(export) => local_gallery_export_response(export),
        Err(error) => error_response(&error),
    }
}

async fn prepare_local_gallery_delete(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match id.parse() {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_local_gallery_id()),
    };
    match state.core.prepare_local_gallery_delete(id).await {
        Ok(confirmation) => with_security_headers(Json(confirmation).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn delete_local_gallery(
    State(state): State<ControlState>,
    Path(id): Path<String>,
    Json(request): Json<crate::LocalGalleryDeleteRequest>,
) -> Response {
    let id = match id.parse() {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_local_gallery_id()),
    };
    match state.core.delete_local_gallery(id, request).await {
        Ok(result) => with_security_headers(Json(result).into_response()),
        Err(error) => error_response(&error),
    }
}

fn local_gallery_resource_response(resource: crate::LocalGalleryResource) -> Response {
    let Ok(content_type) = HeaderValue::from_str(&resource.descriptor().mime_type) else {
        return error_response(&CoreError::new(
            ErrorCode::Internal,
            "local gallery resource has an invalid MIME type",
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
        HeaderValue::from_static("private, max-age=86400"),
    );
    with_resource_security_headers(response)
}

fn local_gallery_export_response(mut export: crate::LocalGalleryExport) -> Response {
    let descriptor = export.descriptor().clone();
    let stream = async_stream::stream! {
        loop {
            match export.read_chunk().await {
                Ok(Some(chunk)) => yield Ok::<bytes::Bytes, std::io::Error>(chunk),
                Ok(None) => break,
                Err(error) => {
                    yield Err(std::io::Error::other(error.to_string()));
                    break;
                }
            }
        }
    };
    let mut response = Response::new(Body::from_stream(stream));
    *response.status_mut() = StatusCode::OK;
    let headers = response.headers_mut();
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/zip"),
    );
    headers.insert(
        header::CONTENT_LENGTH,
        HeaderValue::from_str(&descriptor.byte_length.to_string())
            .expect("u64 Content-Length is valid"),
    );
    headers.insert(
        header::CONTENT_DISPOSITION,
        export_content_disposition(&descriptor),
    );
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    with_resource_security_headers(response)
}

fn export_content_disposition(descriptor: &crate::LocalGalleryExportDescriptor) -> HeaderValue {
    let fallback = if descriptor
        .filename
        .chars()
        .all(|character| character.is_ascii_graphic() && !matches!(character, '"' | '\\'))
    {
        descriptor.filename.as_str()
    } else {
        "gallery.zip"
    };
    let encoded =
        url::form_urlencoded::byte_serialize(descriptor.filename.as_bytes()).collect::<String>();
    HeaderValue::from_str(&format!(
        "attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
    ))
    .expect("validated export filename produces a valid Content-Disposition")
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

async fn get_image_download_task(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_image_download_task_id()),
    };
    match state.core.image_download_task(id).await {
        Ok(task) => with_security_headers(Json(task).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn cancel_image_download_task(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_image_download_task_id()),
    };
    match state.core.cancel_image_download_task(id).await {
        Ok(task) => with_security_headers(Json(task).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn retry_image_download_task(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_image_download_task_id()),
    };
    match state.core.retry_image_download_task(id).await {
        Ok(task) => with_security_headers((StatusCode::ACCEPTED, Json(task)).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn delete_image_download_task(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => return error_response(&invalid_image_download_task_id()),
    };
    match state.core.delete_image_download_task(id).await {
        Ok(()) => with_security_headers(StatusCode::NO_CONTENT.into_response()),
        Err(error) => error_response(&error),
    }
}

fn invalid_image_download_task_id() -> CoreError {
    CoreError::new(
        ErrorCode::InvalidInput,
        "Image download task ID must be a valid UUID",
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
    match state
        .core
        .eh_search(&key, query.search.as_deref().unwrap_or_default(), cursor)
        .await
    {
        Ok(page) => with_security_headers(Json(page).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn list_favorite_searches(State(state): State<ControlState>) -> Response {
    match state.core.favorite_searches() {
        Ok(favorites) => with_security_headers(Json(favorites).into_response()),
        Err(error) => error_response(&error),
    }
}

async fn create_favorite_search(
    State(state): State<ControlState>,
    Json(input): Json<FavoriteSearchInput>,
) -> Response {
    match state
        .core
        .create_favorite_search(input.provider, input.profile, input.name, input.query)
    {
        Ok(favorite) => {
            with_security_headers((StatusCode::CREATED, Json(favorite)).into_response())
        }
        Err(error) => error_response(&error),
    }
}

async fn delete_favorite_search(
    State(state): State<ControlState>,
    Path(id): Path<String>,
) -> Response {
    let id = match uuid::Uuid::parse_str(&id) {
        Ok(id) => id,
        Err(_) => {
            return error_response(&CoreError::new(
                ErrorCode::InvalidInput,
                "favorite search ID must be a valid UUID",
                false,
            ));
        }
    };
    match state.core.delete_favorite_search(id) {
        Ok(true) => with_security_headers(StatusCode::NO_CONTENT.into_response()),
        Ok(false) => error_response(&CoreError::new(
            ErrorCode::ResourceNotFound,
            "favorite search was not found",
            false,
        )),
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
                        crate::CoreEventSubject::ImageDownloadTask { .. } => "image_download_task",
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
