//! Persistent EH Archive submission and bounded streaming downloads.

use crate::{
    CoreError, EhArchiveVariant, EhGalleryRef, ErrorCode, ProfileKey,
    provider::eh::EhService,
    session::{DownloadRequest, SessionRegistry},
};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::Duration,
};
use time::OffsetDateTime;
use tokio::sync::mpsc;
use tokio::sync::{Mutex, Semaphore};
use tokio_util::sync::CancellationToken;
use url::Url;
use uuid::Uuid;

const ARCHIVE_VALID_SECONDS: i64 = 86_400;

/// Persistent lifecycle of one EH Archive task.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArchiveTaskState {
    /// Durable task exists but the paid submission has not started.
    Queued,
    /// EH submission may consume GP; interruption becomes [`Self::CostUnknown`].
    Submitting,
    /// Signed URL is durable and waiting for the download slot.
    Ready,
    /// Archive bytes are streaming into the part file.
    Downloading,
    /// Original ZIP was downloaded successfully.
    Completed,
    /// Completed ZIP was committed into the local gallery library.
    Consumed,
    /// Download failed without automatically submitting Archive cost again.
    Failed,
    /// Caller cancelled submission or download.
    Cancelled,
    /// EH may have charged the account but no signed URL was durably recorded.
    CostUnknown,
}

impl ArchiveTaskState {
    /// Returns whether the task has no automatic transition remaining.
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Completed | Self::Consumed | Self::Failed | Self::Cancelled | Self::CostUnknown
        )
    }
}

/// Request that explicitly authorizes one EH Archive submission.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EhArchiveDownloadRequest {
    /// Configured EH profile.
    pub profile: ProfileKey,
    /// Stable EH gallery identity.
    pub gallery: EhGalleryRef,
    /// Official Original or Resample variant.
    pub variant: EhArchiveVariant,
}

/// Public immutable snapshot without exposing the signed Archive URL.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ArchiveTaskSnapshot {
    /// UUID v7 task identifier.
    pub id: Uuid,
    /// Current task lifecycle state.
    pub state: ArchiveTaskState,
    /// Monotonic task revision.
    pub revision: u64,
    /// EH profile used by this task.
    pub profile: ProfileKey,
    /// Gallery identity.
    pub gallery: EhGalleryRef,
    /// Submitted Archive variant.
    pub variant: EhArchiveVariant,
    /// Gallery title captured before paid submission.
    pub title: String,
    /// Downloaded bytes currently retained in the part or final file.
    pub bytes_done: u64,
    /// Expected Archive size when supplied by HTTP.
    pub bytes_total: Option<u64>,
    /// Whether the server supports ordinary HTTP Range resume.
    pub resume_supported: bool,
    /// Safe server-side final ZIP path after completion.
    pub final_path: Option<String>,
    /// Safe terminal or recovery error.
    pub error: Option<String>,
    /// Local gallery consumption error while retaining completed task state.
    pub consume_error: Option<String>,
    /// Task creation timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub created_at: OffsetDateTime,
    /// Last state/progress persistence timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub updated_at: OffsetDateTime,
    /// Signed URL acquisition timestamp, when durable.
    #[serde(with = "time::serde::rfc3339::option")]
    pub url_acquired_at: Option<OffsetDateTime>,
    /// Signed URL validity in seconds. Always `86400` for EH.
    pub url_valid_seconds: u64,
    /// Maximum IP count documented by EH. Always `2`.
    pub max_ip_count: u8,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct PersistedArchiveTask {
    snapshot: ArchiveTaskSnapshot,
    signed_url: Option<Url>,
    referer: Url,
    part_path: PathBuf,
    final_path: PathBuf,
    etag: Option<String>,
    last_modified: Option<String>,
}

pub(crate) struct ArchiveService {
    root: PathBuf,
    sessions: Arc<SessionRegistry>,
    tasks: Mutex<HashMap<Uuid, PersistedArchiveTask>>,
    cancellations: Mutex<HashMap<Uuid, CancellationToken>>,
    download_slot: Semaphore,
    shutdown: CancellationToken,
    events: mpsc::Sender<crate::operation_service::OperationMessage>,
}

impl ArchiveService {
    pub(crate) async fn open(
        downloads: PathBuf,
        sessions: Arc<SessionRegistry>,
        shutdown: CancellationToken,
        events: mpsc::Sender<crate::operation_service::OperationMessage>,
    ) -> Result<Arc<Self>, CoreError> {
        let root = downloads.join("Downloading");
        tokio::fs::create_dir_all(&root)
            .await
            .map_err(|error| io_error("create Archive task directory", &root, error))?;
        let mut tasks = HashMap::new();
        let mut entries = tokio::fs::read_dir(&root)
            .await
            .map_err(|error| io_error("read Archive task directory", &root, error))?;
        while let Some(entry) = entries
            .next_entry()
            .await
            .map_err(|error| io_error("read Archive task entry", &root, error))?
        {
            let path = entry.path().join("task.json");
            if !path.is_file() {
                continue;
            }
            let Ok(bytes) = tokio::fs::read(&path).await else {
                continue;
            };
            let Ok(mut task) = serde_json::from_slice::<PersistedArchiveTask>(&bytes) else {
                continue;
            };
            match task.snapshot.state {
                ArchiveTaskState::Submitting => {
                    task.snapshot.state = ArchiveTaskState::CostUnknown;
                    task.snapshot.error = Some(
                        "Runtime stopped during paid Archive submission; submission was not replayed"
                            .to_owned(),
                    );
                }
                ArchiveTaskState::Downloading => {
                    task.snapshot.state = ArchiveTaskState::Failed;
                    task.snapshot.error = Some(
                        "Runtime stopped during Archive download; retry can resume without resubmitting cost"
                            .to_owned(),
                    );
                }
                ArchiveTaskState::Queued => {
                    task.snapshot.state = ArchiveTaskState::Cancelled;
                    task.snapshot.error =
                        Some("Runtime stopped before Archive submission".to_owned());
                }
                _ => {}
            }
            task.snapshot.updated_at = OffsetDateTime::now_utc();
            persist(&task).await?;
            tasks.insert(task.snapshot.id, task);
        }
        Ok(Arc::new(Self {
            root,
            sessions,
            tasks: Mutex::new(tasks),
            cancellations: Mutex::new(HashMap::new()),
            download_slot: Semaphore::new(1),
            shutdown,
            events,
        }))
    }

    pub(crate) async fn start(
        self: &Arc<Self>,
        request: EhArchiveDownloadRequest,
    ) -> Result<ArchiveTaskSnapshot, CoreError> {
        if request.profile.provider != "eh" || request.gallery.gid == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "EH Archive download requires an EH profile and valid gallery",
                false,
            ));
        }
        let title = EhService::new(self.sessions.clone())
            .gallery_detail(
                &request.profile,
                request.gallery.clone(),
                self.shutdown.child_token(),
            )
            .await?
            .title;
        let id = Uuid::now_v7();
        let directory = self.root.join(id.to_string());
        tokio::fs::create_dir_all(&directory)
            .await
            .map_err(|error| io_error("create Archive task", &directory, error))?;
        let now = OffsetDateTime::now_utc();
        let referer = gallery_url(&request.profile, &request.gallery, &self.sessions)?;
        let task = PersistedArchiveTask {
            snapshot: ArchiveTaskSnapshot {
                id,
                state: ArchiveTaskState::Submitting,
                revision: 1,
                profile: request.profile,
                gallery: request.gallery,
                variant: request.variant,
                title,
                bytes_done: 0,
                bytes_total: None,
                resume_supported: false,
                final_path: None,
                error: None,
                consume_error: None,
                created_at: now,
                updated_at: now,
                url_acquired_at: None,
                url_valid_seconds: ARCHIVE_VALID_SECONDS as u64,
                max_ip_count: 2,
            },
            signed_url: None,
            referer,
            part_path: directory.join("payload.part"),
            final_path: directory.join("payload.zip"),
            etag: None,
            last_modified: None,
        };
        persist(&task).await?;
        let snapshot = task.snapshot.clone();
        self.tasks.lock().await.insert(id, task);
        self.publish(snapshot.clone()).await;
        let cancellation = self.shutdown.child_token();
        self.cancellations
            .lock()
            .await
            .insert(id, cancellation.clone());
        let service = self.clone();
        tokio::spawn(async move {
            service.run_submission(id, cancellation).await;
        });
        Ok(snapshot)
    }

    pub(crate) async fn get(&self, id: Uuid) -> Result<ArchiveTaskSnapshot, CoreError> {
        self.tasks
            .lock()
            .await
            .get(&id)
            .map(|task| task.snapshot.clone())
            .ok_or_else(task_not_found)
    }

    pub(crate) async fn list(&self) -> Vec<ArchiveTaskSnapshot> {
        let mut tasks: Vec<_> = self
            .tasks
            .lock()
            .await
            .values()
            .map(|task| task.snapshot.clone())
            .collect();
        tasks.sort_by_key(|task| task.created_at);
        tasks
    }

    pub(crate) async fn cancel(&self, id: Uuid) -> Result<ArchiveTaskSnapshot, CoreError> {
        let token = self
            .cancellations
            .lock()
            .await
            .get(&id)
            .cloned()
            .ok_or_else(task_not_found)?;
        token.cancel();
        self.get(id).await
    }

    pub(crate) async fn retry(
        self: &Arc<Self>,
        id: Uuid,
    ) -> Result<ArchiveTaskSnapshot, CoreError> {
        let cancellation = self.shutdown.child_token();
        let snapshot = {
            let mut tasks = self.tasks.lock().await;
            let task = tasks.get_mut(&id).ok_or_else(task_not_found)?;
            if !matches!(
                task.snapshot.state,
                ArchiveTaskState::Failed | ArchiveTaskState::Cancelled
            ) || task.signed_url.is_none()
            {
                return Err(CoreError::new(
                    ErrorCode::InvalidInput,
                    "only failed or cancelled tasks with a durable signed URL can be retried",
                    false,
                ));
            }
            let acquired = task.snapshot.url_acquired_at.ok_or_else(|| {
                CoreError::new(
                    ErrorCode::InvalidInput,
                    "Archive signed URL timestamp is missing",
                    false,
                )
            })?;
            if OffsetDateTime::now_utc() - acquired
                >= time::Duration::seconds(ARCHIVE_VALID_SECONDS)
            {
                return Err(CoreError::new(
                    ErrorCode::AccessDenied,
                    "EH Archive signed URL has expired; cost was not resubmitted",
                    false,
                ));
            }
            transition(task, ArchiveTaskState::Ready, None);
            persist(task).await?;
            let snapshot = task.snapshot.clone();
            self.publish(snapshot.clone()).await;
            snapshot
        };
        self.cancellations
            .lock()
            .await
            .insert(id, cancellation.clone());
        let service = self.clone();
        tokio::spawn(async move { service.run_download(id, cancellation).await });
        Ok(snapshot)
    }

    pub(crate) async fn shutdown(&self, deadline: Duration) -> Result<(), CoreError> {
        self.shutdown.cancel();
        tokio::time::timeout(deadline, async {
            loop {
                if self.cancellations.lock().await.is_empty() {
                    return;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .map_err(|_| {
            CoreError::new(
                ErrorCode::DeadlineExceeded,
                "Archive tasks did not stop before the shutdown deadline",
                false,
            )
        })
    }

    pub(crate) async fn completed_for_consumption(&self) -> Vec<ArchiveConsumption> {
        self.tasks
            .lock()
            .await
            .values()
            .filter(|task| task.snapshot.state == ArchiveTaskState::Completed)
            .map(|task| ArchiveConsumption {
                task: task.snapshot.clone(),
                archive_path: task.final_path.clone(),
            })
            .collect()
    }

    pub(crate) async fn mark_consumed(
        &self,
        id: Uuid,
        gallery_path: Option<String>,
        error: Option<String>,
    ) -> Result<ArchiveTaskSnapshot, CoreError> {
        let mut tasks = self.tasks.lock().await;
        let task = tasks.get_mut(&id).ok_or_else(task_not_found)?;
        if task.snapshot.state != ArchiveTaskState::Completed {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "only completed Archive tasks can be consumed",
                false,
            ));
        }
        if let Some(error) = error {
            task.snapshot.consume_error = Some(error);
            task.snapshot.revision += 1;
            task.snapshot.updated_at = OffsetDateTime::now_utc();
        } else {
            task.snapshot.final_path = gallery_path;
            task.snapshot.consume_error = None;
            transition(task, ArchiveTaskState::Consumed, None);
        }
        persist(task).await?;
        let snapshot = task.snapshot.clone();
        drop(tasks);
        self.publish(snapshot.clone()).await;
        Ok(snapshot)
    }

    pub(crate) async fn mark_local_gallery_deleted(
        &self,
        id: Uuid,
    ) -> Result<Option<ArchiveTaskSnapshot>, CoreError> {
        let mut tasks = self.tasks.lock().await;
        let Some(task) = tasks.get_mut(&id) else {
            return Ok(None);
        };
        if task.snapshot.state != ArchiveTaskState::Consumed {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "only consumed Archive tasks can release a deleted local gallery",
                false,
            ));
        }
        if task.snapshot.final_path.is_none() {
            return Ok(Some(task.snapshot.clone()));
        }
        task.snapshot.final_path = None;
        task.snapshot.revision += 1;
        task.snapshot.updated_at = OffsetDateTime::now_utc();
        persist(task).await?;
        let snapshot = task.snapshot.clone();
        drop(tasks);
        self.publish(snapshot.clone()).await;
        Ok(Some(snapshot))
    }

    async fn run_submission(self: Arc<Self>, id: Uuid, cancellation: CancellationToken) {
        let (profile, gallery, variant) = {
            let tasks = self.tasks.lock().await;
            let Some(task) = tasks.get(&id) else { return };
            (
                task.snapshot.profile.clone(),
                task.snapshot.gallery.clone(),
                task.snapshot.variant,
            )
        };
        let result = EhService::new(self.sessions.clone())
            .submit_archive(&profile, gallery, variant, cancellation.child_token())
            .await;
        match result {
            Ok(url) => {
                let mut tasks = self.tasks.lock().await;
                let Some(task) = tasks.get_mut(&id) else {
                    return;
                };
                task.signed_url = Some(url);
                task.final_path = task
                    .final_path
                    .parent()
                    .expect("Archive final path has parent")
                    .join(remote_archive_filename(
                        task.signed_url.as_ref().expect("URL set"),
                    ));
                task.snapshot.url_acquired_at = Some(OffsetDateTime::now_utc());
                transition(task, ArchiveTaskState::Ready, None);
                if persist(task).await.is_err() {
                    transition(
                        task,
                        ArchiveTaskState::CostUnknown,
                        Some("Archive URL was resolved but could not be durably saved".to_owned()),
                    );
                    let _ = persist(task).await;
                    self.cancellations.lock().await.remove(&id);
                    return;
                }
                drop(tasks);
                self.publish(self.get(id).await.expect("Archive task remains registered"))
                    .await;
                self.run_download(id, cancellation).await;
            }
            Err(error) => {
                let mut tasks = self.tasks.lock().await;
                let Some(task) = tasks.get_mut(&id) else {
                    return;
                };
                transition(
                    task,
                    ArchiveTaskState::CostUnknown,
                    Some(error.message().to_owned()),
                );
                let _ = persist(task).await;
                let snapshot = task.snapshot.clone();
                drop(tasks);
                self.publish(snapshot).await;
                self.cancellations.lock().await.remove(&id);
            }
        }
    }

    async fn run_download(self: Arc<Self>, id: Uuid, cancellation: CancellationToken) {
        let permit = tokio::select! {
            biased;
            () = cancellation.cancelled() => {
                self.finish_cancelled(id).await;
                return;
            }
            permit = self.download_slot.acquire() => match permit {
                Ok(permit) => permit,
                Err(_) => return,
            }
        };
        let (profile, url, referer, part_path, offset) = {
            let mut tasks = self.tasks.lock().await;
            let Some(task) = tasks.get_mut(&id) else {
                return;
            };
            transition(task, ArchiveTaskState::Downloading, None);
            let _ = persist(task).await;
            let snapshot = task.snapshot.clone();
            let offset = tokio::fs::metadata(&task.part_path)
                .await
                .map(|metadata| metadata.len())
                .unwrap_or(0);
            self.publish(snapshot).await;
            (
                task.snapshot.profile.clone(),
                task.signed_url.clone().expect("ready task has signed URL"),
                task.referer.clone(),
                task.part_path.clone(),
                offset,
            )
        };
        let done = Arc::new(AtomicU64::new(offset));
        let total = Arc::new(AtomicU64::new(0));
        let download = self.sessions.download_to(
            &profile,
            DownloadRequest {
                url: &url,
                referer: &referer,
                offset,
                path: &part_path,
            },
            cancellation.clone(),
            {
                let done = done.clone();
                let total = total.clone();
                move |value, expected| {
                    done.store(value, Ordering::Relaxed);
                    total.store(expected.unwrap_or(0), Ordering::Relaxed);
                }
            },
        );
        tokio::pin!(download);
        let mut interval = tokio::time::interval(Duration::from_secs(2));
        let mut last_saved = offset;
        let result = loop {
            tokio::select! {
                result = &mut download => break result,
                _ = interval.tick() => {
                    let current = done.load(Ordering::Relaxed);
                    if current.saturating_sub(last_saved) >= 1024 * 1024 || current != last_saved {
                        last_saved = current;
                        self.save_progress(id, current, total.load(Ordering::Relaxed)).await;
                    }
                }
            }
        };
        drop(permit);
        match result {
            Ok(response) => {
                let mut tasks = self.tasks.lock().await;
                let Some(task) = tasks.get_mut(&id) else {
                    return;
                };
                task.snapshot.bytes_done = response.bytes_done;
                task.snapshot.bytes_total = response.bytes_total;
                task.snapshot.resume_supported = response.accept_ranges || response.resumed;
                task.etag = response.etag;
                task.last_modified = response.last_modified;
                if let Err(error) = tokio::fs::rename(&task.part_path, &task.final_path).await {
                    transition(
                        task,
                        ArchiveTaskState::Failed,
                        Some(format!("failed to finalize Archive ZIP: {error}")),
                    );
                } else {
                    task.snapshot.final_path = Some(task.final_path.to_string_lossy().into_owned());
                    transition(task, ArchiveTaskState::Completed, None);
                }
                let _ = persist(task).await;
                let snapshot = task.snapshot.clone();
                drop(tasks);
                self.publish(snapshot).await;
            }
            Err(error) => {
                let mut tasks = self.tasks.lock().await;
                let Some(task) = tasks.get_mut(&id) else {
                    return;
                };
                let state = if error.code() == ErrorCode::Cancelled {
                    ArchiveTaskState::Cancelled
                } else {
                    ArchiveTaskState::Failed
                };
                transition(task, state, Some(error.message().to_owned()));
                let _ = persist(task).await;
                let snapshot = task.snapshot.clone();
                drop(tasks);
                self.publish(snapshot).await;
            }
        }
        self.cancellations.lock().await.remove(&id);
    }

    async fn save_progress(&self, id: Uuid, done: u64, total: u64) {
        let mut tasks = self.tasks.lock().await;
        let Some(task) = tasks.get_mut(&id) else {
            return;
        };
        task.snapshot.bytes_done = done;
        task.snapshot.bytes_total = (total > 0).then_some(total);
        task.snapshot.revision += 1;
        task.snapshot.updated_at = OffsetDateTime::now_utc();
        let _ = persist(task).await;
        let snapshot = task.snapshot.clone();
        drop(tasks);
        self.publish(snapshot).await;
    }

    async fn finish_cancelled(&self, id: Uuid) {
        let mut tasks = self.tasks.lock().await;
        let Some(task) = tasks.get_mut(&id) else {
            return;
        };
        transition(task, ArchiveTaskState::Cancelled, None);
        let _ = persist(task).await;
        let snapshot = task.snapshot.clone();
        drop(tasks);
        self.publish(snapshot).await;
        self.cancellations.lock().await.remove(&id);
    }

    async fn publish(&self, snapshot: ArchiveTaskSnapshot) {
        let _ = self
            .events
            .send(crate::operation_service::OperationMessage::ArchiveTask(
                snapshot,
            ))
            .await;
    }
}

pub(crate) struct ArchiveConsumption {
    pub(crate) task: ArchiveTaskSnapshot,
    pub(crate) archive_path: PathBuf,
}

fn transition(task: &mut PersistedArchiveTask, state: ArchiveTaskState, error: Option<String>) {
    task.snapshot.state = state;
    task.snapshot.error = error;
    task.snapshot.revision += 1;
    task.snapshot.updated_at = OffsetDateTime::now_utc();
}

async fn persist(task: &PersistedArchiveTask) -> Result<(), CoreError> {
    let path = task
        .part_path
        .parent()
        .expect("task part path has parent")
        .join("task.json");
    let temporary = path.with_extension("json.tmp");
    let bytes = serde_json::to_vec_pretty(task).map_err(|error| {
        CoreError::new(
            ErrorCode::Internal,
            format!("failed to serialize Archive task: {error}"),
            false,
        )
    })?;
    tokio::fs::write(&temporary, bytes)
        .await
        .map_err(|error| io_error("write Archive task snapshot", &temporary, error))?;
    tokio::fs::rename(&temporary, &path)
        .await
        .map_err(|error| io_error("replace Archive task snapshot", &path, error))
}

fn gallery_url(
    profile: &ProfileKey,
    gallery: &EhGalleryRef,
    sessions: &SessionRegistry,
) -> Result<Url, CoreError> {
    let snapshot = sessions
        .snapshots()?
        .into_iter()
        .find(|snapshot| snapshot.key == *profile)
        .ok_or_else(task_not_found)?;
    Url::parse(&snapshot.base_url)
        .and_then(|base| base.join(&format!("g/{}/{}/", gallery.gid, gallery.token)))
        .map_err(|_| {
            CoreError::new(
                ErrorCode::InvalidInput,
                "failed to build EH gallery URL",
                false,
            )
        })
}

fn remote_archive_filename(url: &Url) -> String {
    let candidate = url
        .path_segments()
        .and_then(Iterator::last)
        .filter(|value| !value.is_empty())
        .unwrap_or("archive.zip");
    let mut filename: String = candidate
        .chars()
        .map(|character| {
            if character.is_ascii_control()
                || matches!(
                    character,
                    '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*'
                )
            {
                '_'
            } else {
                character
            }
        })
        .take(180)
        .collect();
    filename = filename.trim_matches([' ', '.']).to_owned();
    if filename.is_empty() {
        filename = "archive.zip".to_owned();
    }
    if !filename.to_ascii_lowercase().ends_with(".zip") {
        filename.push_str(".zip");
    }
    filename
}

fn task_not_found() -> CoreError {
    CoreError::new(
        ErrorCode::ResourceNotFound,
        "Archive task was not found",
        false,
    )
}

fn io_error(action: &str, path: &Path, error: std::io::Error) -> CoreError {
    CoreError::new(
        ErrorCode::Io,
        format!("failed to {action} {}: {error}", path.display()),
        false,
    )
}

#[cfg(test)]
mod tests {
    use super::{ArchiveService, ArchiveTaskState, EhArchiveDownloadRequest};
    use crate::{
        EhArchiveVariant, EhGalleryRef, NetworkConfig, ProfileKey, ProviderProfileConfig,
        session::SessionRegistry,
    };
    use axum::{
        Router,
        body::Body,
        extract::RawQuery,
        http::{HeaderMap, StatusCode, header},
        response::Response,
        routing::{get, post},
    };
    use std::{
        collections::BTreeMap,
        sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        },
    };
    use tempfile::TempDir;
    use tokio::net::TcpListener;
    use tokio_util::sync::CancellationToken;
    use url::Url;

    const SUBMITTED: &str = include_str!("../tests/fixtures/eh/archive_submitted.html");
    const INTERMEDIATE: &str = include_str!("../tests/fixtures/eh/archive_intermediate.html");

    async fn wait_terminal(service: &ArchiveService, id: uuid::Uuid) -> crate::ArchiveTaskSnapshot {
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            loop {
                let task = service.get(id).await.unwrap();
                if task.state.is_terminal() {
                    return task;
                }
                tokio::time::sleep(std::time::Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap()
    }

    #[tokio::test]
    async fn submits_once_streams_zip_and_recovers_without_replaying_cost() {
        let submissions = Arc::new(AtomicUsize::new(0));
        let archive = Arc::new(
            vec![0x50, 0x4b, 0x03, 0x04]
                .into_iter()
                .chain(std::iter::repeat_n(0x5a, 64 * 1024))
                .collect::<Vec<_>>(),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let listen = listener.local_addr().unwrap();
        let router = Router::new()
            .route(
                "/g/123456/abcdef1234/",
                get(|| async {
                    (
                        [(header::CONTENT_TYPE, "text/html")],
                        "<h1 id=\"gn\">Archive Fixture</h1>",
                    )
                }),
            )
            .route(
                "/archiver.php",
                post({
                    let submissions = submissions.clone();
                    move |RawQuery(query): RawQuery, body: String| {
                        let submissions = submissions.clone();
                        async move {
                            assert_eq!(query.as_deref(), Some("gid=123456&token=abcdef1234"));
                            assert!(body.contains("dltype=res"));
                            submissions.fetch_add(1, Ordering::SeqCst);
                            ([(header::CONTENT_TYPE, "text/html")], SUBMITTED)
                        }
                    }
                }),
            )
            .route(
                "/archive-intermediate",
                get(|| async { ([(header::CONTENT_TYPE, "text/html")], INTERMEDIATE) }),
            )
            .route(
                "/signed/archive.zip",
                get({
                    let archive = archive.clone();
                    move |headers: HeaderMap| {
                        let archive = archive.clone();
                        async move {
                            let offset = headers
                                .get(header::RANGE)
                                .and_then(|value| value.to_str().ok())
                                .and_then(|value| value.strip_prefix("bytes="))
                                .and_then(|value| value.strip_suffix('-'))
                                .and_then(|value| value.parse::<usize>().ok())
                                .unwrap_or(0);
                            let status = if offset > 0 {
                                StatusCode::PARTIAL_CONTENT
                            } else {
                                StatusCode::OK
                            };
                            let mut response =
                                Response::new(Body::from(archive[offset..].to_vec()));
                            *response.status_mut() = status;
                            response
                                .headers_mut()
                                .insert(header::CONTENT_TYPE, "application/zip".parse().unwrap());
                            response
                                .headers_mut()
                                .insert(header::ACCEPT_RANGES, "bytes".parse().unwrap());
                            response
                        }
                    }
                }),
            );
        tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
        let temp = TempDir::new().unwrap();
        let profile = ProviderProfileConfig {
            provider: "eh".to_owned(),
            base_url: Url::parse(&format!("http://{listen}/")).unwrap(),
            ..ProviderProfileConfig::default()
        };
        let sessions = Arc::new(
            SessionRegistry::new(
                &BTreeMap::from([("eh".to_owned(), profile)]),
                &NetworkConfig::default(),
            )
            .unwrap(),
        );
        let shutdown = CancellationToken::new();
        let (event_tx, _event_rx) = tokio::sync::mpsc::channel(32);
        let service = ArchiveService::open(
            temp.path().join("Downloads"),
            sessions.clone(),
            shutdown.clone(),
            event_tx.clone(),
        )
        .await
        .unwrap();
        let task = service
            .start(EhArchiveDownloadRequest {
                profile: ProfileKey::new("eh", "default"),
                gallery: EhGalleryRef {
                    gid: 123456,
                    token: "abcdef1234".to_owned(),
                },
                variant: EhArchiveVariant::Resample,
            })
            .await
            .unwrap();
        let task = wait_terminal(&service, task.id).await;
        assert_eq!(task.state, ArchiveTaskState::Completed);
        assert_eq!(submissions.load(Ordering::SeqCst), 1);
        assert!(std::path::Path::new(task.final_path.as_ref().unwrap()).is_file());
        drop(service);

        let task_path = temp
            .path()
            .join("Downloads/Downloading")
            .join(task.id.to_string())
            .join("task.json");
        let mut persisted: serde_json::Value =
            serde_json::from_slice(&tokio::fs::read(&task_path).await.unwrap()).unwrap();
        persisted["snapshot"]["state"] = serde_json::Value::String("submitting".to_owned());
        tokio::fs::write(&task_path, serde_json::to_vec_pretty(&persisted).unwrap())
            .await
            .unwrap();
        let recovered =
            ArchiveService::open(temp.path().join("Downloads"), sessions, shutdown, event_tx)
                .await
                .unwrap();
        let recovered = recovered.get(task.id).await.unwrap();
        assert_eq!(recovered.state, ArchiveTaskState::CostUnknown);
        assert_eq!(submissions.load(Ordering::SeqCst), 1);
    }
}
