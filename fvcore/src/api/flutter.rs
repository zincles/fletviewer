//! Flutter desktop and Android bridge facade.

use crate::{
    ContentMd5, CoreBuilder, CoreError, CoreHandle, CoreRuntime, EhPageDirection, ErrorCode,
    EventStreamItem, ProfileKey,
};
use serde::Serialize;
use std::{path::PathBuf, str::FromStr};
use tokio::sync::Mutex;

/// Opaque owner used by Flutter to access one embedded Runtime.
#[flutter_rust_bridge::frb(opaque)]
pub struct NativeCore {
    handle: CoreHandle,
    runtime: Mutex<Option<CoreRuntime>>,
}

/// Stable bridge error payload encoded as JSON in FRB error channels.
#[derive(Clone, Debug, Serialize)]
struct BridgeError<'a> {
    code: &'a str,
    message: &'a str,
    retryable: bool,
}

/// Initializes flutter_rust_bridge process utilities.
#[flutter_rust_bridge::frb(init)]
pub fn init_app() {
    flutter_rust_bridge::setup_default_user_utils();
}

/// Starts one embedded Runtime using explicit platform storage paths.
pub async fn start_native_core(
    data_dir: String,
    cache_dir: String,
    downloads_dir: String,
    temp_dir: String,
) -> Result<NativeCore, String> {
    let mut config = crate::CoreConfig::default();
    config.control.enabled = false;
    config.storage.data = PathBuf::from(data_dir);
    config.storage.cache = PathBuf::from(cache_dir);
    config.storage.downloads = PathBuf::from(downloads_dir);
    config.storage.temp = PathBuf::from(temp_dir);
    let runtime = CoreBuilder::new(config)
        .build()
        .await
        .map_err(bridge_error)?;
    let handle = runtime.handle();
    Ok(NativeCore {
        handle,
        runtime: Mutex::new(Some(runtime)),
    })
}

impl NativeCore {
    /// Returns a stable JSON Runtime snapshot.
    pub async fn runtime_json(&self) -> Result<String, String> {
        self.ensure_running().await?;
        to_json(self.handle.snapshot().await)
    }

    /// Returns unified persistent download tasks as JSON.
    pub async fn download_tasks_json(&self) -> Result<String, String> {
        self.ensure_running().await?;
        to_json(Ok(self.handle.download_tasks(None, None).await))
    }

    /// Returns one unified persistent download task as JSON.
    pub async fn download_task_json(&self, id: String) -> Result<String, String> {
        self.ensure_running().await?;
        let id = parse_uuid(&id)?;
        to_json(self.handle.download_task(id).await)
    }

    /// Cancels one persistent download task and returns its updated JSON view.
    pub async fn cancel_download_task_json(&self, id: String) -> Result<String, String> {
        self.ensure_running().await?;
        let id = parse_uuid(&id)?;
        to_json(self.handle.cancel_download_task(id).await)
    }

    /// Retries one persistent download task and returns its updated JSON view.
    pub async fn retry_download_task_json(&self, id: String) -> Result<String, String> {
        self.ensure_running().await?;
        let id = parse_uuid(&id)?;
        to_json(self.handle.retry_download_task(id).await)
    }

    /// Deletes one terminal download task record when the owning family allows it.
    pub async fn delete_download_task(&self, id: String) -> Result<(), String> {
        self.ensure_running().await?;
        let id = parse_uuid(&id)?;
        self.handle
            .delete_download_task(id)
            .await
            .map_err(bridge_error)
    }

    /// Returns one operation snapshot as JSON.
    pub async fn operation_json(&self, id: String) -> Result<String, String> {
        self.ensure_running().await?;
        let id = parse_operation_id(&id)?;
        to_json(self.handle.operation(id).await)
    }

    /// Searches one EH profile and returns a listing page as JSON.
    pub async fn eh_search_json(
        &self,
        profile: String,
        search: String,
        direction: Option<String>,
        gid: Option<u64>,
    ) -> Result<String, String> {
        self.ensure_running().await?;
        let cursor = parse_eh_cursor(direction, gid)?;
        to_json(
            self.handle
                .eh_search(&ProfileKey::new("eh", profile), &search, cursor)
                .await,
        )
    }

    /// Returns parsed metadata for one EH gallery as JSON.
    pub async fn eh_gallery_detail_json(
        &self,
        profile: String,
        gid: u64,
        token: String,
    ) -> Result<String, String> {
        self.ensure_running().await?;
        to_json(
            self.handle
                .eh_gallery_detail(
                    &ProfileKey::new("eh", profile),
                    crate::EhGalleryRef { gid, token },
                )
                .await,
        )
    }

    /// Returns one page of EH thumbnails as JSON.
    pub async fn eh_thumbnails_json(
        &self,
        profile: String,
        gid: u64,
        token: String,
        page: u32,
    ) -> Result<String, String> {
        self.ensure_running().await?;
        to_json(
            self.handle
                .eh_thumbnails(
                    &ProfileKey::new("eh", profile),
                    crate::EhGalleryRef { gid, token },
                    page,
                )
                .await,
        )
    }

    /// Starts one EH web-viewer page image fetch and returns the operation as JSON.
    pub async fn start_eh_page_fetch_json(
        &self,
        profile: String,
        gid: u64,
        token: String,
        page: u32,
    ) -> Result<String, String> {
        self.ensure_running().await?;
        to_json(
            self.handle
                .start_eh_page_fetch(crate::EhPageFetchRequest {
                    profile: ProfileKey::new("eh", profile),
                    gallery: crate::EhGalleryRef { gid, token },
                    page,
                    nl: None,
                })
                .await,
        )
    }

    /// Reads content-addressed image bytes.
    pub async fn image_resource_bytes(
        &self,
        content_md5: String,
        extension: String,
    ) -> Result<Vec<u8>, String> {
        self.ensure_running().await?;
        let md5 = ContentMd5::from_str(&content_md5).map_err(bridge_error)?;
        self.handle
            .image_resource(md5, &extension)
            .await
            .map(|resource| resource.bytes().to_vec())
            .map_err(bridge_error)
    }

    /// Replays retained Runtime events after a cursor as JSON.
    pub async fn events_after_json(&self, cursor: u64) -> Result<String, String> {
        self.ensure_running().await?;
        to_json(self.handle.events_after(cursor).await)
    }

    /// Waits for the next replayed or live event and returns its JSON envelope.
    pub async fn next_event_json(&self, cursor: u64) -> Result<String, String> {
        self.ensure_running().await?;
        let mut subscription = self
            .handle
            .subscribe_events(cursor)
            .await
            .map_err(bridge_error)?;
        match subscription.next().await {
            EventStreamItem::Event(event) => serde_json::to_string(&serde_json::json!({
                "type": "event",
                "event": event,
            }))
            .map_err(serialization_error),
            EventStreamItem::ResyncRequired => Ok(r#"{"type":"resync_required"}"#.to_owned()),
            EventStreamItem::Closed => Ok(r#"{"type":"closed"}"#.to_owned()),
        }
    }

    /// Requests graceful shutdown and waits for owned services to stop.
    pub async fn shutdown(&self) -> Result<(), String> {
        let runtime = self.runtime.lock().await.take();
        match runtime {
            Some(runtime) => runtime.shutdown().await.map_err(bridge_error),
            None => Ok(()),
        }
    }

    async fn ensure_running(&self) -> Result<(), String> {
        if self.runtime.lock().await.is_some() {
            Ok(())
        } else {
            Err(bridge_error(CoreError::new(
                ErrorCode::NotReady,
                "embedded Runtime is already shut down",
                false,
            )))
        }
    }
}

fn parse_uuid(input: &str) -> Result<uuid::Uuid, String> {
    uuid::Uuid::parse_str(input).map_err(|_| {
        bridge_error(CoreError::new(
            ErrorCode::InvalidInput,
            "Download task ID must be a valid UUID",
            false,
        ))
    })
}

fn parse_operation_id(input: &str) -> Result<crate::OperationId, String> {
    crate::OperationId::from_str(input).map_err(|_| {
        bridge_error(CoreError::new(
            ErrorCode::InvalidInput,
            "Operation ID must be a valid UUID",
            false,
        ))
    })
}

fn parse_eh_cursor(
    direction: Option<String>,
    gid: Option<u64>,
) -> Result<Option<crate::EhPageCursor>, String> {
    match (direction, gid) {
        (None, None) => Ok(None),
        (Some(direction), Some(gid)) => {
            let direction = match direction.as_str() {
                "previous" => EhPageDirection::Previous,
                "next" => EhPageDirection::Next,
                _ => {
                    return Err(bridge_error(CoreError::new(
                        ErrorCode::InvalidInput,
                        "EH direction must be previous or next",
                        false,
                    )));
                }
            };
            if gid == 0 {
                return Err(bridge_error(CoreError::new(
                    ErrorCode::InvalidInput,
                    "EH cursor GID must be positive",
                    false,
                )));
            }
            Ok(Some(crate::EhPageCursor { direction, gid }))
        }
        _ => Err(bridge_error(CoreError::new(
            ErrorCode::InvalidInput,
            "EH direction and gid must be supplied together",
            false,
        ))),
    }
}

fn to_json<T: Serialize>(result: Result<T, CoreError>) -> Result<String, String> {
    result
        .map_err(bridge_error)
        .and_then(|value| serde_json::to_string(&value).map_err(serialization_error))
}

fn bridge_error(error: CoreError) -> String {
    serde_json::to_string(&BridgeError {
        code: error.code().as_str(),
        message: error.message(),
        retryable: error.retryable(),
    })
    .unwrap_or_else(|_| {
        r#"{"code":"internal","message":"failed to serialize bridge error","retryable":false}"#
            .to_owned()
    })
}

fn serialization_error(error: serde_json::Error) -> String {
    bridge_error(CoreError::new(
        ErrorCode::Internal,
        format!("failed to serialize bridge payload: {error}"),
        false,
    ))
}

#[cfg(test)]
mod tests {
    use super::BridgeError;

    #[test]
    fn bridge_error_is_stable_json() {
        let encoded = serde_json::to_string(&BridgeError {
            code: "invalid_input",
            message: "bad input",
            retryable: false,
        })
        .unwrap();
        assert_eq!(
            encoded,
            r#"{"code":"invalid_input","message":"bad input","retryable":false}"#
        );
    }
}
