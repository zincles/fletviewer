//! Integrated HTTP control plane and minimal status page.

use crate::{
    CoreError, CoreHandle, CoreSnapshot, ErrorCode, EventStreamItem, FakeOperationRequest,
    OperationId, RuntimeState,
};
use axum::{
    Json, Router,
    extract::{Path, Query, State},
    http::{HeaderValue, StatusCode, header},
    response::{Html, IntoResponse, Response, Sse, sse::Event},
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
struct ControlState {
    core: CoreHandle,
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

pub(crate) async fn start(
    listen: SocketAddr,
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
    let router = Router::new()
        .route("/", get(status_page))
        .route("/health/live", get(liveness))
        .route("/health/ready", get(readiness))
        .route("/api/v1/runtime", get(runtime_snapshot))
        .route("/api/v1/profiles", get(list_profiles))
        .route(
            "/api/v1/profiles/{provider}/{profile}/probe",
            post(probe_profile),
        )
        .route(
            "/api/v1/operations",
            get(list_operations).post(start_fake_operation),
        )
        .route("/api/v1/operations/{id}", get(get_operation))
        .route("/api/v1/operations/{id}/cancel", post(cancel_operation))
        .route("/api/v1/events", get(events))
        .with_state(ControlState { core });
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

async fn status_page(State(state): State<ControlState>) -> Response {
    match state.core.snapshot().await {
        Ok(snapshot) => with_security_headers(Html(render_status(&snapshot)).into_response()),
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
                            .event("operation")
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

fn render_status(snapshot: &CoreSnapshot) -> String {
    format!(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta http-equiv=\"refresh\" content=\"2\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>fvcore status</title><style>body{{max-width:64rem;margin:1rem auto;padding:0 1rem;font:14px monospace}}table{{border-collapse:collapse}}th,td{{padding:.3rem .8rem .3rem 0;text-align:left;border-bottom:1px solid #aaa}}</style></head><body><h1>fvcore</h1><table><tr><th>Instance</th><td>{}</td></tr><tr><th>Runtime</th><td>{}</td></tr><tr><th>Status</th><td>{:?}</td></tr><tr><th>Revision</th><td>{}</td></tr><tr><th>Uptime</th><td>{} s</td></tr><tr><th>Control</th><td>{}</td></tr><tr><th>Queued commands</th><td>{}</td></tr><tr><th>Operations</th><td>{} active / {} queued / {} retained</td></tr><tr><th>Latest event</th><td>{}</td></tr></table><h2>Storage</h2><table><tr><th>Schema</th><td>{}</td></tr><tr><th>Data</th><td>{}</td></tr><tr><th>Cache</th><td>{}</td></tr><tr><th>Downloads</th><td>{}</td></tr><tr><th>Temp</th><td>{}</td></tr><tr><th>Database</th><td>{} bytes</td></tr></table><p><a href=\"/api/v1/runtime\">JSON snapshot</a> | <a href=\"/api/v1/operations\">Operations</a></p></body></html>",
        escape_html(&snapshot.instance_name),
        snapshot.runtime_id,
        snapshot.state,
        snapshot.revision,
        snapshot.uptime_seconds,
        snapshot.control_listen.as_deref().unwrap_or("disabled"),
        snapshot.queued_commands,
        snapshot.active_operations,
        snapshot.queued_operations,
        snapshot.retained_operations,
        snapshot.latest_event_sequence,
        snapshot.storage.schema_version,
        escape_html(&snapshot.storage.data),
        escape_html(&snapshot.storage.cache),
        escape_html(&snapshot.storage.downloads),
        escape_html(&snapshot.storage.temp),
        snapshot.storage.database_bytes,
    )
}

fn escape_html(input: &str) -> String {
    input
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&#39;")
}

fn error_response(error: &CoreError) -> Response {
    let status = match error.code() {
        ErrorCode::InvalidInput => StatusCode::BAD_REQUEST,
        ErrorCode::NotReady => StatusCode::SERVICE_UNAVAILABLE,
        ErrorCode::Overloaded => StatusCode::TOO_MANY_REQUESTS,
        ErrorCode::OperationNotFound => StatusCode::NOT_FOUND,
        ErrorCode::OperationFinished => StatusCode::CONFLICT,
        ErrorCode::ProfileNotFound => StatusCode::NOT_FOUND,
        ErrorCode::AuthenticationRequired => StatusCode::UNAUTHORIZED,
        ErrorCode::AccessDenied => StatusCode::FORBIDDEN,
        ErrorCode::RateLimited => StatusCode::TOO_MANY_REQUESTS,
        ErrorCode::ResponseTooLarge => StatusCode::PAYLOAD_TOO_LARGE,
        ErrorCode::RedirectDenied => StatusCode::BAD_GATEWAY,
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

#[cfg(test)]
mod tests {
    use super::escape_html;

    #[test]
    fn escapes_untrusted_status_text() {
        assert_eq!(escape_html("<a & \"b\">"), "&lt;a &amp; &quot;b&quot;&gt;");
    }
}
