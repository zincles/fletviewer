//! Persistent single-image downloads backed by the shared image service.

use crate::{
    ContentMd5, CoreError, ErrorCode, ProfileKey, ResourceKey,
    image::{ImageFetchSpec, ImageService},
    operation_service::OperationMessage,
    provider::booru::BooruService,
    provider::pixiv::PixivService,
    session::SessionRegistry,
};
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, path::PathBuf, str::FromStr, sync::Arc};
use time::OffsetDateTime;
use tokio::sync::Mutex;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

/// Persistent lifecycle of one single-image download.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ImageDownloadState {
    /// Metadata resolution or shared image fetch is running.
    Running,
    /// Immutable image bytes were atomically published into Downloads.
    Completed,
    /// The task failed and may be retried by creating a new task.
    Failed,
    /// The caller cancelled this task subscription.
    Cancelled,
}

/// Request for one durable Booru original image download.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BooruImageDownloadRequest {
    /// Configured Booru profile.
    pub profile: ProfileKey,
    /// Provider post identifier.
    pub post_id: u64,
}

/// Request for one durable Pixiv original page download.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PixivImageDownloadRequest {
    /// Configured Pixiv profile.
    pub profile: ProfileKey,
    /// Pixiv illustration identifier.
    pub illust_id: String,
    /// Zero-based page index.
    pub page: u32,
}

/// Provider resource represented by one persistent image download task.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ImageDownloadKind {
    /// One Booru post original.
    #[default]
    BooruOriginal,
    /// One Pixiv illustration original page.
    PixivOriginal,
}

/// Public immutable image download task state without server absolute paths.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ImageDownloadTaskSnapshot {
    /// UUID v7 task identifier.
    pub id: Uuid,
    /// Current task state.
    pub state: ImageDownloadState,
    /// Monotonic task revision.
    pub revision: u64,
    /// Provider resource kind.
    #[serde(default)]
    pub kind: ImageDownloadKind,
    /// Provider profile used by the task.
    pub profile: ProfileKey,
    /// Provider post identifier for a Booru task.
    pub post_id: Option<u64>,
    /// Illustration identifier for a Pixiv task.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub illust_id: Option<String>,
    /// Zero-based illustration page for a Pixiv task.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub page: Option<u32>,
    /// Downloaded immutable byte count after completion.
    pub byte_length: Option<u64>,
    /// Verified real-content MD5 after completion.
    pub content_md5: Option<String>,
    /// Downloads-relative managed output name.
    pub output: Option<String>,
    /// Safe terminal error.
    pub error: Option<String>,
    /// Task creation timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub created_at: OffsetDateTime,
    /// Last state persistence timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub updated_at: OffsetDateTime,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct PersistedImageDownloadTask {
    snapshot: ImageDownloadTaskSnapshot,
}

pub(crate) struct ImageDownloadService {
    tasks_root: PathBuf,
    images_root: PathBuf,
    sessions: Arc<SessionRegistry>,
    images: Arc<ImageService>,
    tasks: Mutex<HashMap<Uuid, PersistedImageDownloadTask>>,
    cancellations: Mutex<HashMap<Uuid, CancellationToken>>,
    shutdown: CancellationToken,
    message_tx: mpsc::Sender<OperationMessage>,
}

impl ImageDownloadService {
    pub(crate) async fn open(
        downloads: PathBuf,
        sessions: Arc<SessionRegistry>,
        images: Arc<ImageService>,
        shutdown: CancellationToken,
        message_tx: mpsc::Sender<OperationMessage>,
    ) -> Result<Arc<Self>, CoreError> {
        let tasks_root = downloads.join("ImageTasks");
        let images_root = downloads.join("Images");
        tokio::fs::create_dir_all(&tasks_root)
            .await
            .map_err(|error| io_error("create image task directory", &tasks_root, error))?;
        tokio::fs::create_dir_all(&images_root)
            .await
            .map_err(|error| io_error("create image download directory", &images_root, error))?;
        let mut tasks = HashMap::new();
        let mut entries = tokio::fs::read_dir(&tasks_root)
            .await
            .map_err(|error| io_error("read image task directory", &tasks_root, error))?;
        while let Some(entry) = entries
            .next_entry()
            .await
            .map_err(|error| io_error("read image task entry", &tasks_root, error))?
        {
            let path = entry.path().join("task.json");
            let Ok(bytes) = tokio::fs::read(&path).await else {
                continue;
            };
            let Ok(mut task) = serde_json::from_slice::<PersistedImageDownloadTask>(&bytes) else {
                continue;
            };
            if task.snapshot.state == ImageDownloadState::Running {
                task.snapshot.state = ImageDownloadState::Failed;
                task.snapshot.revision += 1;
                task.snapshot.error = Some("Runtime stopped during image download".to_owned());
                task.snapshot.updated_at = OffsetDateTime::now_utc();
                persist(&tasks_root, &task).await?;
            }
            tasks.insert(task.snapshot.id, task);
        }
        Ok(Arc::new(Self {
            tasks_root,
            images_root,
            sessions,
            images,
            tasks: Mutex::new(tasks),
            cancellations: Mutex::new(HashMap::new()),
            shutdown,
            message_tx,
        }))
    }

    pub(crate) async fn start(
        self: &Arc<Self>,
        request: BooruImageDownloadRequest,
    ) -> Result<ImageDownloadTaskSnapshot, CoreError> {
        if request.post_id == 0 || request.profile.provider == "pixiv" {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Booru profile and post ID greater than zero are required",
                false,
            ));
        }
        let id = Uuid::now_v7();
        let now = OffsetDateTime::now_utc();
        let task = PersistedImageDownloadTask {
            snapshot: ImageDownloadTaskSnapshot {
                id,
                state: ImageDownloadState::Running,
                revision: 1,
                kind: ImageDownloadKind::BooruOriginal,
                profile: request.profile,
                post_id: Some(request.post_id),
                illust_id: None,
                page: None,
                byte_length: None,
                content_md5: None,
                output: None,
                error: None,
                created_at: now,
                updated_at: now,
            },
        };
        self.start_task(task).await
    }

    pub(crate) async fn start_pixiv(
        self: &Arc<Self>,
        request: PixivImageDownloadRequest,
    ) -> Result<ImageDownloadTaskSnapshot, CoreError> {
        if request.profile.provider != "pixiv"
            || request.illust_id.is_empty()
            || !request.illust_id.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Pixiv profile and numeric illustration ID are required",
                false,
            ));
        }
        let id = Uuid::now_v7();
        let now = OffsetDateTime::now_utc();
        let task = PersistedImageDownloadTask {
            snapshot: ImageDownloadTaskSnapshot {
                id,
                state: ImageDownloadState::Running,
                revision: 1,
                kind: ImageDownloadKind::PixivOriginal,
                profile: request.profile,
                post_id: None,
                illust_id: Some(request.illust_id),
                page: Some(request.page),
                byte_length: None,
                content_md5: None,
                output: None,
                error: None,
                created_at: now,
                updated_at: now,
            },
        };
        self.start_task(task).await
    }

    async fn start_task(
        self: &Arc<Self>,
        task: PersistedImageDownloadTask,
    ) -> Result<ImageDownloadTaskSnapshot, CoreError> {
        let id = task.snapshot.id;
        tokio::fs::create_dir_all(self.tasks_root.join(id.to_string()))
            .await
            .map_err(|error| io_error("create image task", &self.tasks_root, error))?;
        persist(&self.tasks_root, &task).await?;
        self.tasks.lock().await.insert(id, task.clone());
        let _ = self
            .message_tx
            .send(OperationMessage::ImageDownloadTask(task.snapshot.clone()))
            .await;
        let cancellation = self.shutdown.child_token();
        self.cancellations
            .lock()
            .await
            .insert(id, cancellation.clone());
        let service = self.clone();
        tokio::spawn(async move { service.run(task, cancellation).await });
        Ok(self.tasks.lock().await[&id].snapshot.clone())
    }

    pub(crate) async fn list(&self) -> Vec<ImageDownloadTaskSnapshot> {
        let mut tasks = self
            .tasks
            .lock()
            .await
            .values()
            .map(|task| task.snapshot.clone())
            .collect::<Vec<_>>();
        tasks.sort_by_key(|task| task.created_at);
        tasks
    }

    pub(crate) async fn get(&self, id: Uuid) -> Result<ImageDownloadTaskSnapshot, CoreError> {
        self.tasks
            .lock()
            .await
            .get(&id)
            .map(|task| task.snapshot.clone())
            .ok_or_else(task_not_found)
    }

    pub(crate) async fn cancel(&self, id: Uuid) -> Result<ImageDownloadTaskSnapshot, CoreError> {
        let cancellation = self
            .cancellations
            .lock()
            .await
            .get(&id)
            .cloned()
            .ok_or_else(|| {
                CoreError::new(
                    ErrorCode::InvalidInput,
                    "image download task is not running",
                    false,
                )
            })?;
        cancellation.cancel();
        self.get(id).await
    }

    pub(crate) async fn retry(
        self: &Arc<Self>,
        id: Uuid,
    ) -> Result<ImageDownloadTaskSnapshot, CoreError> {
        let task = {
            let mut tasks = self.tasks.lock().await;
            let mut task = tasks.get(&id).cloned().ok_or_else(task_not_found)?;
            if task.snapshot.state == ImageDownloadState::Running {
                return Err(CoreError::new(
                    ErrorCode::InvalidInput,
                    "running image download task cannot be retried",
                    false,
                ));
            }
            task.snapshot.state = ImageDownloadState::Running;
            task.snapshot.revision += 1;
            task.snapshot.byte_length = None;
            task.snapshot.content_md5 = None;
            task.snapshot.output = None;
            task.snapshot.error = None;
            task.snapshot.updated_at = OffsetDateTime::now_utc();
            persist(&self.tasks_root, &task).await?;
            tasks.insert(id, task.clone());
            task
        };
        let _ = self
            .message_tx
            .send(OperationMessage::ImageDownloadTask(task.snapshot.clone()))
            .await;
        let cancellation = self.shutdown.child_token();
        self.cancellations
            .lock()
            .await
            .insert(id, cancellation.clone());
        let service = self.clone();
        tokio::spawn(async move { service.run(task, cancellation).await });
        Ok(self.tasks.lock().await[&id].snapshot.clone())
    }

    pub(crate) async fn delete(&self, id: Uuid) -> Result<(), CoreError> {
        let mut tasks = self.tasks.lock().await;
        let task = tasks.get(&id).ok_or_else(task_not_found)?;
        if task.snapshot.state == ImageDownloadState::Running {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "running image download task cannot be deleted",
                false,
            ));
        }
        let directory = self.tasks_root.join(id.to_string());
        tokio::fs::remove_dir_all(&directory)
            .await
            .map_err(|error| io_error("delete image task", &directory, error))?;
        tasks.remove(&id);
        Ok(())
    }

    pub(crate) async fn shutdown(&self, timeout: std::time::Duration) -> Result<(), CoreError> {
        self.shutdown.cancel();
        tokio::time::timeout(timeout, async {
            loop {
                if self.cancellations.lock().await.is_empty() {
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_millis(5)).await;
            }
        })
        .await
        .map_err(|_| {
            CoreError::new(
                ErrorCode::DeadlineExceeded,
                "image download workers did not stop before shutdown deadline",
                false,
            )
        })
    }

    async fn run(
        self: Arc<Self>,
        mut task: PersistedImageDownloadTask,
        cancellation: CancellationToken,
    ) {
        let result = self
            .fetch_and_publish(&task.snapshot, cancellation.clone())
            .await;
        task.snapshot.revision += 1;
        task.snapshot.updated_at = OffsetDateTime::now_utc();
        match result {
            Ok((output, resource)) => {
                task.snapshot.state = ImageDownloadState::Completed;
                task.snapshot.byte_length = Some(resource.descriptor().byte_length as u64);
                task.snapshot.content_md5 = Some(resource.descriptor().content_md5.to_string());
                task.snapshot.output = Some(output);
            }
            Err(error) if error.code() == ErrorCode::Cancelled || cancellation.is_cancelled() => {
                task.snapshot.state = ImageDownloadState::Cancelled;
                task.snapshot.error = Some("image download was cancelled".to_owned());
            }
            Err(error) => {
                task.snapshot.state = ImageDownloadState::Failed;
                task.snapshot.error = Some(error.message().to_owned());
            }
        }
        let _ = persist(&self.tasks_root, &task).await;
        self.cancellations.lock().await.remove(&task.snapshot.id);
        self.tasks
            .lock()
            .await
            .insert(task.snapshot.id, task.clone());
        let _ = self
            .message_tx
            .send(OperationMessage::ImageDownloadTask(task.snapshot.clone()))
            .await;
    }

    async fn fetch_and_publish(
        &self,
        task: &ImageDownloadTaskSnapshot,
        cancellation: CancellationToken,
    ) -> Result<(String, crate::ImageResource), CoreError> {
        let (url, expected_md5, resource_key, expected_bytes, referer, stem) = match task.kind {
            ImageDownloadKind::BooruOriginal => {
                let post_id = task
                    .post_id
                    .ok_or_else(|| invalid_task("missing Booru post ID"))?;
                let post = BooruService::new(self.sessions.clone())
                    .get_post(&task.profile, post_id, cancellation.child_token())
                    .await?;
                let url = post.original.url.ok_or_else(|| {
                    CoreError::new(
                        ErrorCode::UnexpectedResponse,
                        "Booru post has no original image URL",
                        false,
                    )
                })?;
                let expected_md5 = post
                    .original_md5
                    .as_deref()
                    .map(ContentMd5::from_str)
                    .transpose()?;
                let resource_key = expected_md5
                    .is_none()
                    .then(|| {
                        ResourceKey::new(&task.profile.provider, post_id.to_string(), 0, "original")
                    })
                    .transpose()?;
                (
                    url,
                    expected_md5,
                    resource_key,
                    post.original.byte_length,
                    Some(post.page_url),
                    post_id.to_string(),
                )
            }
            ImageDownloadKind::PixivOriginal => {
                let illust_id = task
                    .illust_id
                    .as_deref()
                    .ok_or_else(|| invalid_task("missing Pixiv illustration ID"))?;
                let page_index = task
                    .page
                    .ok_or_else(|| invalid_task("missing Pixiv page index"))?;
                let illust = PixivService::new(self.sessions.clone())
                    .illust(&task.profile, illust_id, cancellation.child_token())
                    .await?;
                let page = illust.pages.get(page_index as usize).ok_or_else(|| {
                    CoreError::new(
                        ErrorCode::InvalidInput,
                        format!("Pixiv page {page_index} is outside the illustration"),
                        false,
                    )
                })?;
                (
                    page.original_url.clone(),
                    None,
                    Some(ResourceKey::new(
                        "pixiv", illust_id, page_index, "original",
                    )?),
                    None,
                    Some(illust.page_url),
                    format!("{illust_id}-p{page_index}"),
                )
            }
        };
        let resource = self
            .images
            .fetch(
                ImageFetchSpec {
                    profile: task.profile.clone(),
                    url,
                    expected_md5,
                    resource_key,
                    expected_bytes,
                    referer,
                },
                cancellation,
                |_| {},
            )
            .await?;
        let provider_root = self.images_root.join(&task.profile.provider);
        tokio::fs::create_dir_all(&provider_root)
            .await
            .map_err(|error| io_error("create Provider image directory", &provider_root, error))?;
        let filename = format!(
            "{}-{}.{}",
            stem,
            resource.descriptor().content_md5,
            resource.descriptor().extension
        );
        let final_path = provider_root.join(&filename);
        if tokio::fs::try_exists(&final_path)
            .await
            .map_err(|error| io_error("inspect existing image download", &final_path, error))?
        {
            let existing = tokio::fs::read(&final_path)
                .await
                .map_err(|error| io_error("read existing image download", &final_path, error))?;
            if existing == resource.bytes().as_ref() {
                return Ok((
                    format!("Images/{}/{filename}", task.profile.provider),
                    resource,
                ));
            }
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "managed image download conflicts with verified content",
                false,
            ));
        }
        let part_path = provider_root.join(format!(".{filename}.{}.part", task.id));
        tokio::fs::write(&part_path, resource.bytes())
            .await
            .map_err(|error| io_error("write image download part", &part_path, error))?;
        tokio::fs::rename(&part_path, &final_path)
            .await
            .map_err(|error| io_error("publish image download", &final_path, error))?;
        Ok((
            format!("Images/{}/{filename}", task.profile.provider),
            resource,
        ))
    }
}

async fn persist(
    root: &std::path::Path,
    task: &PersistedImageDownloadTask,
) -> Result<(), CoreError> {
    let directory = root.join(task.snapshot.id.to_string());
    let path = directory.join("task.json");
    let temporary = directory.join("task.json.tmp");
    let mut bytes = serde_json::to_vec_pretty(task).map_err(|error| {
        CoreError::new(
            ErrorCode::Internal,
            format!("encode image download task: {error}"),
            false,
        )
    })?;
    bytes.push(b'\n');
    tokio::fs::write(&temporary, bytes)
        .await
        .map_err(|error| io_error("write image task", &temporary, error))?;
    tokio::fs::rename(&temporary, &path)
        .await
        .map_err(|error| io_error("publish image task", &path, error))
}

fn io_error(action: &str, path: &std::path::Path, error: std::io::Error) -> CoreError {
    CoreError::new(
        ErrorCode::Io,
        format!("failed to {action} {}: {error}", path.display()),
        false,
    )
}

fn invalid_task(message: &str) -> CoreError {
    CoreError::new(
        ErrorCode::Internal,
        format!("invalid image task: {message}"),
        false,
    )
}

fn task_not_found() -> CoreError {
    CoreError::new(
        ErrorCode::ResourceNotFound,
        "image download task was not found",
        false,
    )
}
