//! Frontend-safe unified views over persistent download task families.

use crate::{
    ArchiveTaskSnapshot, ArchiveTaskState, ImageDownloadKind, ImageDownloadState,
    ImageDownloadTaskSnapshot,
};
use serde::Serialize;
use std::path::Path;
use time::OffsetDateTime;
use uuid::Uuid;

/// Stable common lifecycle used by download-list frontends.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DownloadTaskStatus {
    /// Waiting for a bounded download slot.
    Queued,
    /// Provider resolution or byte transfer is running.
    Running,
    /// A durable output completed successfully.
    Completed,
    /// The task failed and may require user action.
    Failed,
    /// The user cancelled the task.
    Cancelled,
}

/// Frontend-safe unified persistent download task view.
#[derive(Clone, Debug, Serialize)]
pub struct DownloadTaskView {
    /// Stable task identifier.
    pub id: Uuid,
    /// Provider implementation identifier.
    pub provider: String,
    /// Provider-specific task kind.
    pub kind: String,
    /// Stable common lifecycle.
    pub status: DownloadTaskStatus,
    /// Human-readable title or resource identity.
    pub title: String,
    /// Safe filename or managed Downloads-relative output.
    pub filename: String,
    /// Current provider/cache/transfer phase.
    pub phase: String,
    /// Bytes currently available.
    pub bytes_done: u64,
    /// Expected total bytes when known.
    pub bytes_total: Option<u64>,
    /// Normalized progress in `0.0..=1.0` when total bytes are known.
    pub progress: Option<f64>,
    /// Safe terminal error.
    pub error: String,
    /// Secondary local-gallery consumption error.
    pub consume_error: String,
    /// Whether ordinary transport resume is supported.
    pub resume_supported: bool,
    /// Whether the current state accepts cancellation.
    pub can_cancel: bool,
    /// Whether the current state accepts retry.
    pub can_retry: bool,
    /// Whether this task family supports deleting only the task record.
    pub can_delete: bool,
    /// Task creation timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub created_at: OffsetDateTime,
    /// Last task update timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub updated_at: OffsetDateTime,
    /// Provider-specific safe identifiers and limits.
    pub metadata: serde_json::Value,
}

impl DownloadTaskView {
    pub(crate) fn from_archive(task: ArchiveTaskSnapshot) -> Self {
        let status = match task.state {
            ArchiveTaskState::Queued => DownloadTaskStatus::Queued,
            ArchiveTaskState::Submitting
            | ArchiveTaskState::Ready
            | ArchiveTaskState::Downloading => DownloadTaskStatus::Running,
            ArchiveTaskState::Completed | ArchiveTaskState::Consumed => {
                DownloadTaskStatus::Completed
            }
            ArchiveTaskState::Failed | ArchiveTaskState::CostUnknown => DownloadTaskStatus::Failed,
            ArchiveTaskState::Cancelled => DownloadTaskStatus::Cancelled,
        };
        let filename = task
            .final_path
            .as_deref()
            .and_then(|path| Path::new(path).file_name())
            .and_then(|name| name.to_str())
            .unwrap_or("")
            .to_owned();
        Self {
            id: task.id,
            provider: "eh".to_owned(),
            kind: "eh_archive".to_owned(),
            status,
            title: task.title,
            filename,
            phase: format!("{:?}", task.state).to_ascii_lowercase(),
            bytes_done: task.bytes_done,
            bytes_total: task.bytes_total,
            progress: progress(task.bytes_done, task.bytes_total),
            error: task.error.unwrap_or_default(),
            consume_error: task.consume_error.unwrap_or_default(),
            resume_supported: task.resume_supported,
            can_cancel: matches!(
                task.state,
                ArchiveTaskState::Queued
                    | ArchiveTaskState::Submitting
                    | ArchiveTaskState::Ready
                    | ArchiveTaskState::Downloading
            ),
            can_retry: task.retry_supported,
            can_delete: false,
            created_at: task.created_at,
            updated_at: task.updated_at,
            metadata: serde_json::json!({
                "gallery_id": task.gallery.gid.to_string(),
                "gallery_token": task.gallery.token,
                "variant": format!("{:?}", task.variant).to_ascii_lowercase(),
                "archive_state": format!("{:?}", task.state).to_ascii_lowercase(),
                "url_acquired_at": task.url_acquired_at,
                "url_valid_seconds": task.url_valid_seconds,
                "max_ip_count": task.max_ip_count,
            }),
        }
    }

    pub(crate) fn from_image(task: ImageDownloadTaskSnapshot) -> Self {
        let status = match task.state {
            ImageDownloadState::Queued => DownloadTaskStatus::Queued,
            ImageDownloadState::Running => DownloadTaskStatus::Running,
            ImageDownloadState::Completed => DownloadTaskStatus::Completed,
            ImageDownloadState::Failed => DownloadTaskStatus::Failed,
            ImageDownloadState::Cancelled => DownloadTaskStatus::Cancelled,
        };
        let (kind, title, media) = match task.kind {
            ImageDownloadKind::BooruOriginal => {
                let post_id = task
                    .post_id
                    .map_or_else(|| "?".to_owned(), |id| id.to_string());
                (
                    "booru_original",
                    format!("{} post {post_id}", task.profile.provider),
                    serde_json::json!({"post_id": task.post_id}),
                )
            }
            ImageDownloadKind::PixivOriginal => {
                let illust_id = task.illust_id.as_deref().unwrap_or("?");
                let page = task.page.unwrap_or(0);
                (
                    "pixiv_original",
                    format!("Pixiv {illust_id} p{page}"),
                    serde_json::json!({"illust_id": task.illust_id, "page": task.page}),
                )
            }
        };
        Self {
            id: task.id,
            provider: task.profile.provider.clone(),
            kind: kind.to_owned(),
            status,
            title,
            filename: task.output.unwrap_or_default(),
            phase: task.phase,
            bytes_done: task.bytes_done,
            bytes_total: task.bytes_total,
            progress: progress(task.bytes_done, task.bytes_total),
            error: task.error.unwrap_or_default(),
            consume_error: String::new(),
            resume_supported: false,
            can_cancel: matches!(
                task.state,
                ImageDownloadState::Queued | ImageDownloadState::Running
            ),
            can_retry: matches!(
                task.state,
                ImageDownloadState::Completed
                    | ImageDownloadState::Failed
                    | ImageDownloadState::Cancelled
            ),
            can_delete: matches!(
                task.state,
                ImageDownloadState::Completed
                    | ImageDownloadState::Failed
                    | ImageDownloadState::Cancelled
            ),
            created_at: task.created_at,
            updated_at: task.updated_at,
            metadata: serde_json::json!({
                "profile": task.profile.profile,
                "media": media,
                "content_md5": task.content_md5,
            }),
        }
    }
}

fn progress(done: u64, total: Option<u64>) -> Option<f64> {
    total
        .filter(|total| *total > 0)
        .map(|total| (done as f64 / total as f64).clamp(0.0, 1.0))
}
