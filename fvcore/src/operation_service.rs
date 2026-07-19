//! Runtime-owned operation registry, workers and event journal.

use crate::{
    BooruOriginalFetchRequest, CoreError, CoreEvent, ErrorCode, ErrorSnapshot, EventBatch,
    EventConfig, FakeOperationRequest, FakeOutcome, ImageResourceDescriptor, OperationConfig,
    OperationId, OperationKind, OperationSnapshot, OperationState, PixivPageFetchRequest,
    ResourceKey, RuntimeId,
    image::{ContentMd5, ImageFetchSpec, ImageProgress, ImageService},
    provider::booru::BooruService,
    provider::pixiv::PixivService,
    session::SessionRegistry,
};
use std::{
    collections::{HashMap, VecDeque},
    str::FromStr,
    sync::Arc,
    time::Duration,
};
use time::OffsetDateTime;
use tokio::sync::{broadcast, mpsc};
use tokio_util::sync::CancellationToken;

#[derive(Clone)]
pub(crate) enum OperationMessage {
    Progress {
        id: OperationId,
        progress: ImageProgress,
    },
    Completion {
        id: OperationId,
        result: WorkerResult,
    },
}

#[derive(Clone)]
pub(crate) enum OperationRequest {
    Fake(FakeOperationRequest),
    BooruOriginal(BooruOriginalFetchRequest),
    PixivPage(PixivPageFetchRequest),
}

#[derive(Clone)]
pub(crate) struct OperationCompletion {
    pub(crate) id: OperationId,
    pub(crate) result: WorkerResult,
}

#[derive(Clone)]
pub(crate) enum WorkerResult {
    Completed(Option<ImageResourceDescriptor>),
    Failed(ErrorSnapshot),
    Cancelled,
}

struct OperationEntry {
    snapshot: OperationSnapshot,
    request: OperationRequest,
    cancellation: CancellationToken,
}

pub(crate) struct OperationService {
    runtime_id: RuntimeId,
    config: OperationConfig,
    operations: HashMap<OperationId, OperationEntry>,
    queued: VecDeque<OperationId>,
    terminal: VecDeque<OperationId>,
    active: usize,
    message_tx: mpsc::Sender<OperationMessage>,
    events: EventHub,
    sessions: Arc<SessionRegistry>,
    images: Arc<ImageService>,
}

pub(crate) struct EventHub {
    next_sequence: u64,
    retained: usize,
    journal: VecDeque<CoreEvent>,
    live: broadcast::Sender<CoreEvent>,
}

impl EventHub {
    pub(crate) fn new(config: &EventConfig) -> Self {
        let (live, _) = broadcast::channel(config.capacity);
        Self {
            next_sequence: 1,
            retained: config.retained,
            journal: VecDeque::with_capacity(config.retained),
            live,
        }
    }

    fn publish(&mut self, runtime_id: RuntimeId, snapshot: &OperationSnapshot) {
        let event = CoreEvent {
            sequence: self.next_sequence,
            runtime_id,
            operation_id: snapshot.id,
            revision: snapshot.revision,
            state: snapshot.state,
            phase: snapshot.phase.clone(),
            bytes_done: snapshot.bytes_done,
            bytes_total: snapshot.bytes_total,
            source: snapshot.source,
            shared: snapshot.shared,
            resource: snapshot.resource.clone(),
        };
        self.next_sequence += 1;
        self.journal.push_back(event.clone());
        while self.journal.len() > self.retained {
            self.journal.pop_front();
        }
        let _ = self.live.send(event);
    }

    pub(crate) fn batch_after(&self, cursor: u64) -> EventBatch {
        let latest_sequence = self.next_sequence.saturating_sub(1);
        let earliest = self
            .journal
            .front()
            .map_or(self.next_sequence, |event| event.sequence);
        let resync_required = cursor > 0 && cursor.saturating_add(1) < earliest;
        let events = if resync_required {
            Vec::new()
        } else {
            self.journal
                .iter()
                .filter(|event| event.sequence > cursor)
                .cloned()
                .collect()
        };
        EventBatch {
            events,
            latest_sequence,
            resync_required,
        }
    }

    pub(crate) fn subscribe(&self) -> broadcast::Receiver<CoreEvent> {
        self.live.subscribe()
    }

    pub(crate) fn latest_sequence(&self) -> u64 {
        self.next_sequence.saturating_sub(1)
    }
}

impl OperationService {
    pub(crate) fn new(
        runtime_id: RuntimeId,
        config: OperationConfig,
        event_config: &EventConfig,
        message_tx: mpsc::Sender<OperationMessage>,
        sessions: Arc<SessionRegistry>,
        images: Arc<ImageService>,
    ) -> Self {
        Self {
            runtime_id,
            config,
            operations: HashMap::new(),
            queued: VecDeque::new(),
            terminal: VecDeque::new(),
            active: 0,
            message_tx,
            events: EventHub::new(event_config),
            sessions,
            images,
        }
    }

    pub(crate) fn start_fake(
        &mut self,
        request: FakeOperationRequest,
        runtime_shutdown: &CancellationToken,
    ) -> Result<OperationSnapshot, CoreError> {
        self.start(
            OperationKind::Fake,
            OperationRequest::Fake(request),
            runtime_shutdown,
        )
    }

    pub(crate) fn start_booru_original(
        &mut self,
        request: BooruOriginalFetchRequest,
        runtime_shutdown: &CancellationToken,
    ) -> Result<OperationSnapshot, CoreError> {
        if request.post_id == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Booru post ID must be greater than zero",
                false,
            ));
        }
        if !matches!(request.profile.provider.as_str(), "danbooru" | "gelbooru") {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Booru original fetch supports danbooru and gelbooru profiles",
                false,
            ));
        }
        self.start(
            OperationKind::ImageFetch,
            OperationRequest::BooruOriginal(request),
            runtime_shutdown,
        )
    }

    pub(crate) fn start_pixiv_page(
        &mut self,
        request: PixivPageFetchRequest,
        runtime_shutdown: &CancellationToken,
    ) -> Result<OperationSnapshot, CoreError> {
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
        self.start(
            OperationKind::ImageFetch,
            OperationRequest::PixivPage(request),
            runtime_shutdown,
        )
    }

    fn start(
        &mut self,
        kind: OperationKind,
        request: OperationRequest,
        runtime_shutdown: &CancellationToken,
    ) -> Result<OperationSnapshot, CoreError> {
        if self.active >= self.config.max_active && self.queued.len() >= self.config.max_queued {
            return Err(CoreError::new(
                ErrorCode::Overloaded,
                "operation queue is full",
                true,
            ));
        }
        let id = OperationId::new();
        let snapshot = OperationSnapshot {
            id,
            kind,
            state: OperationState::Queued,
            phase: "queued".to_owned(),
            revision: 1,
            created_at: OffsetDateTime::now_utc(),
            started_at: None,
            finished_at: None,
            error: None,
            bytes_done: 0,
            bytes_total: None,
            source: None,
            shared: false,
            resource: None,
        };
        self.operations.insert(
            id,
            OperationEntry {
                snapshot: snapshot.clone(),
                request,
                cancellation: runtime_shutdown.child_token(),
            },
        );
        self.events.publish(self.runtime_id, &snapshot);
        self.queued.push_back(id);
        self.schedule();
        Ok(self.operations[&id].snapshot.clone())
    }

    pub(crate) fn get(&self, id: OperationId) -> Result<OperationSnapshot, CoreError> {
        self.operations
            .get(&id)
            .map(|entry| entry.snapshot.clone())
            .ok_or_else(operation_not_found)
    }

    pub(crate) fn list(&self) -> Vec<OperationSnapshot> {
        let mut snapshots: Vec<_> = self
            .operations
            .values()
            .map(|entry| entry.snapshot.clone())
            .collect();
        snapshots.sort_by_key(|snapshot| snapshot.created_at);
        snapshots
    }

    pub(crate) fn cancel(&mut self, id: OperationId) -> Result<OperationSnapshot, CoreError> {
        let entry = self
            .operations
            .get_mut(&id)
            .ok_or_else(operation_not_found)?;
        if entry.snapshot.state.is_terminal() {
            return Err(CoreError::new(
                ErrorCode::OperationFinished,
                "operation has already finished",
                false,
            ));
        }
        entry.cancellation.cancel();
        if entry.snapshot.state == OperationState::Queued {
            self.queued.retain(|queued_id| *queued_id != id);
            transition_terminal(entry, WorkerResult::Cancelled)?;
            let snapshot = entry.snapshot.clone();
            self.events.publish(self.runtime_id, &snapshot);
            self.retain_terminal(id);
            self.schedule();
        }
        self.get(id)
    }

    pub(crate) fn complete(&mut self, completion: OperationCompletion) {
        let Some(entry) = self.operations.get_mut(&completion.id) else {
            return;
        };
        if entry.snapshot.state != OperationState::Running {
            return;
        }
        if transition_terminal(entry, completion.result).is_err() {
            return;
        }
        self.active = self.active.saturating_sub(1);
        let snapshot = entry.snapshot.clone();
        self.events.publish(self.runtime_id, &snapshot);
        self.retain_terminal(completion.id);
        self.schedule();
    }

    pub(crate) fn progress(&mut self, id: OperationId, progress: ImageProgress) {
        let Some(entry) = self.operations.get_mut(&id) else {
            return;
        };
        if entry.snapshot.state != OperationState::Running {
            return;
        }
        entry.snapshot.phase = progress.phase.to_owned();
        entry.snapshot.bytes_done = progress.bytes_done;
        entry.snapshot.bytes_total = progress.bytes_total;
        entry.snapshot.source = progress.source;
        entry.snapshot.shared = progress.shared;
        entry.snapshot.revision += 1;
        self.events.publish(self.runtime_id, &entry.snapshot);
    }

    pub(crate) fn events_after(&self, cursor: u64) -> EventBatch {
        self.events.batch_after(cursor)
    }

    pub(crate) fn subscribe(&self) -> broadcast::Receiver<CoreEvent> {
        self.events.subscribe()
    }

    pub(crate) fn counts(&self) -> (usize, usize, usize, u64) {
        (
            self.active,
            self.queued.len(),
            self.terminal.len(),
            self.events.latest_sequence(),
        )
    }

    fn schedule(&mut self) {
        while self.active < self.config.max_active {
            let Some(id) = self.queued.pop_front() else {
                break;
            };
            let Some(entry) = self.operations.get_mut(&id) else {
                continue;
            };
            if transition_running(entry).is_err() {
                continue;
            }
            self.active += 1;
            let snapshot = entry.snapshot.clone();
            self.events.publish(self.runtime_id, &snapshot);
            let request = entry.request.clone();
            let cancellation = entry.cancellation.clone();
            let message_tx = self.message_tx.clone();
            let sessions = self.sessions.clone();
            let images = self.images.clone();
            let default_deadline = self.config.default_deadline_seconds;
            tokio::spawn(async move {
                let result = match request {
                    OperationRequest::Fake(request) => {
                        run_fake(request, cancellation, default_deadline).await
                    }
                    OperationRequest::BooruOriginal(request) => {
                        match tokio::time::timeout(
                            Duration::from_secs(default_deadline),
                            run_booru_original(
                                id,
                                request,
                                cancellation,
                                sessions,
                                images,
                                message_tx.clone(),
                            ),
                        )
                        .await
                        {
                            Ok(result) => result,
                            Err(_) => WorkerResult::Failed(ErrorSnapshot {
                                code: ErrorCode::DeadlineExceeded,
                                message: "operation deadline exceeded".to_owned(),
                                retryable: true,
                            }),
                        }
                    }
                    OperationRequest::PixivPage(request) => {
                        match tokio::time::timeout(
                            Duration::from_secs(default_deadline),
                            run_pixiv_page(
                                id,
                                request,
                                cancellation,
                                sessions,
                                images,
                                message_tx.clone(),
                            ),
                        )
                        .await
                        {
                            Ok(result) => result,
                            Err(_) => WorkerResult::Failed(ErrorSnapshot {
                                code: ErrorCode::DeadlineExceeded,
                                message: "operation deadline exceeded".to_owned(),
                                retryable: true,
                            }),
                        }
                    }
                };
                let _ = message_tx
                    .send(OperationMessage::Completion { id, result })
                    .await;
            });
        }
    }

    fn retain_terminal(&mut self, id: OperationId) {
        self.terminal.push_back(id);
        while self.terminal.len() > self.config.retained_terminal {
            if let Some(expired) = self.terminal.pop_front() {
                self.operations.remove(&expired);
            }
        }
    }
}

fn transition_running(entry: &mut OperationEntry) -> Result<(), CoreError> {
    if entry.snapshot.state != OperationState::Queued {
        return Err(invalid_transition());
    }
    entry.snapshot.state = OperationState::Running;
    entry.snapshot.phase = match entry.snapshot.kind {
        OperationKind::Fake => "running",
        OperationKind::ImageFetch => "resolving",
    }
    .to_owned();
    entry.snapshot.revision += 1;
    entry.snapshot.started_at = Some(OffsetDateTime::now_utc());
    Ok(())
}

fn transition_terminal(entry: &mut OperationEntry, result: WorkerResult) -> Result<(), CoreError> {
    if !matches!(
        entry.snapshot.state,
        OperationState::Queued | OperationState::Running
    ) {
        return Err(invalid_transition());
    }
    let (state, phase, error) = match result {
        WorkerResult::Completed(resource) => {
            entry.snapshot.resource = resource;
            (OperationState::Completed, "completed", None)
        }
        WorkerResult::Cancelled => (OperationState::Cancelled, "cancelled", None),
        WorkerResult::Failed(error) => (OperationState::Failed, "failed", Some(error)),
    };
    entry.snapshot.state = state;
    entry.snapshot.phase = phase.to_owned();
    entry.snapshot.revision += 1;
    entry.snapshot.finished_at = Some(OffsetDateTime::now_utc());
    entry.snapshot.error = error;
    Ok(())
}

async fn run_fake(
    request: FakeOperationRequest,
    cancellation: CancellationToken,
    default_deadline_seconds: u64,
) -> WorkerResult {
    let deadline = request
        .deadline_ms
        .map(Duration::from_millis)
        .unwrap_or_else(|| Duration::from_secs(default_deadline_seconds));
    tokio::select! {
        biased;
        () = cancellation.cancelled() => WorkerResult::Cancelled,
        result = tokio::time::timeout(deadline, tokio::time::sleep(Duration::from_millis(request.duration_ms))) => {
            match result {
                Err(_) => WorkerResult::Failed(ErrorSnapshot {
                    code: ErrorCode::DeadlineExceeded,
                    message: "operation deadline exceeded".to_owned(),
                    retryable: true,
                }),
                Ok(()) => match request.outcome {
                    FakeOutcome::Succeed => WorkerResult::Completed(None),
                    FakeOutcome::Fail => WorkerResult::Failed(ErrorSnapshot {
                        code: ErrorCode::Internal,
                        message: "fake operation failed".to_owned(),
                        retryable: false,
                    }),
                },
            }
        }
    }
}

async fn run_booru_original(
    id: OperationId,
    request: BooruOriginalFetchRequest,
    cancellation: CancellationToken,
    sessions: Arc<SessionRegistry>,
    images: Arc<ImageService>,
    messages: mpsc::Sender<OperationMessage>,
) -> WorkerResult {
    let booru = BooruService::new(sessions);
    let post = match request.profile.provider.as_str() {
        "danbooru" => {
            booru
                .get_danbooru_post(
                    &request.profile,
                    request.post_id,
                    cancellation.child_token(),
                )
                .await
        }
        "gelbooru" => {
            booru
                .get_gelbooru_post(
                    &request.profile,
                    request.post_id,
                    cancellation.child_token(),
                )
                .await
        }
        _ => unreachable!("validated before scheduling"),
    };
    let post = match post {
        Ok(post) => post,
        Err(error) => return worker_error(error),
    };
    let Some(url) = post.original.url else {
        return worker_error(CoreError::new(
            ErrorCode::UnexpectedResponse,
            "Booru post has no original image URL",
            false,
        ));
    };
    let Some(md5) = post.original_md5 else {
        return worker_error(CoreError::new(
            ErrorCode::UnexpectedResponse,
            "Booru post has no original content MD5",
            false,
        ));
    };
    let expected_md5 = match ContentMd5::from_str(&md5) {
        Ok(md5) => md5,
        Err(error) => return worker_error(error),
    };
    let mut last_phase = "";
    let mut last_bytes = 0_u64;
    let mut last_update = std::time::Instant::now();
    let result = images
        .fetch(
            ImageFetchSpec {
                profile: request.profile,
                url,
                expected_md5: Some(expected_md5),
                resource_key: None,
                expected_bytes: post.original.byte_length,
                referer: Some(post.page_url),
            },
            cancellation,
            |progress| {
                let publish = progress.phase != last_phase
                    || progress.bytes_done.saturating_sub(last_bytes) >= 64 * 1024
                    || last_update.elapsed() >= Duration::from_millis(100);
                if publish {
                    last_phase = progress.phase;
                    last_bytes = progress.bytes_done;
                    last_update = std::time::Instant::now();
                    let _ = messages.try_send(OperationMessage::Progress { id, progress });
                }
            },
        )
        .await;
    match result {
        Ok(resource) => WorkerResult::Completed(Some(resource.descriptor().clone())),
        Err(error) => worker_error(error),
    }
}

async fn run_pixiv_page(
    id: OperationId,
    request: PixivPageFetchRequest,
    cancellation: CancellationToken,
    sessions: Arc<SessionRegistry>,
    images: Arc<ImageService>,
    messages: mpsc::Sender<OperationMessage>,
) -> WorkerResult {
    let illust = match PixivService::new(sessions)
        .illust(
            &request.profile,
            &request.illust_id,
            cancellation.child_token(),
        )
        .await
    {
        Ok(illust) => illust,
        Err(error) => return worker_error(error),
    };
    let Some(page) = illust.pages.get(request.page as usize) else {
        return worker_error(CoreError::new(
            ErrorCode::InvalidInput,
            format!("Pixiv page {} is outside the illustration", request.page),
            false,
        ));
    };
    let resource_key = match ResourceKey::new("pixiv", &request.illust_id, request.page, "original")
    {
        Ok(key) => key,
        Err(error) => return worker_error(error),
    };
    let mut last_phase = "";
    let mut last_bytes = 0_u64;
    let mut last_update = std::time::Instant::now();
    let result = images
        .fetch(
            ImageFetchSpec {
                profile: request.profile,
                url: page.original_url.clone(),
                expected_md5: None,
                resource_key: Some(resource_key),
                expected_bytes: None,
                referer: Some(illust.page_url),
            },
            cancellation,
            |progress| {
                let publish = progress.phase != last_phase
                    || progress.bytes_done.saturating_sub(last_bytes) >= 64 * 1024
                    || last_update.elapsed() >= Duration::from_millis(100);
                if publish {
                    last_phase = progress.phase;
                    last_bytes = progress.bytes_done;
                    last_update = std::time::Instant::now();
                    let _ = messages.try_send(OperationMessage::Progress { id, progress });
                }
            },
        )
        .await;
    match result {
        Ok(resource) => WorkerResult::Completed(Some(resource.descriptor().clone())),
        Err(error) => worker_error(error),
    }
}

fn worker_error(error: CoreError) -> WorkerResult {
    if error.code() == ErrorCode::Cancelled {
        WorkerResult::Cancelled
    } else {
        WorkerResult::Failed(ErrorSnapshot {
            code: error.code(),
            message: error.message().to_owned(),
            retryable: error.retryable(),
        })
    }
}

fn operation_not_found() -> CoreError {
    CoreError::new(
        ErrorCode::OperationNotFound,
        "operation was not found",
        false,
    )
}

fn invalid_transition() -> CoreError {
    CoreError::new(
        ErrorCode::Internal,
        "invalid operation state transition",
        false,
    )
}
