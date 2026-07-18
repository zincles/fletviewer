//! Runtime-owned operation registry, workers and event journal.

use crate::{
    CoreError, CoreEvent, ErrorCode, ErrorSnapshot, EventBatch, EventConfig, FakeOperationRequest,
    FakeOutcome, OperationConfig, OperationId, OperationKind, OperationSnapshot, OperationState,
    RuntimeId,
};
use std::collections::{HashMap, VecDeque};
use std::time::Duration;
use time::OffsetDateTime;
use tokio::sync::{broadcast, mpsc};
use tokio_util::sync::CancellationToken;

#[derive(Clone)]
pub(crate) struct OperationCompletion {
    pub(crate) id: OperationId,
    pub(crate) result: WorkerResult,
}

#[derive(Clone)]
pub(crate) enum WorkerResult {
    Completed,
    Failed(ErrorSnapshot),
    Cancelled,
}

struct OperationEntry {
    snapshot: OperationSnapshot,
    request: FakeOperationRequest,
    cancellation: CancellationToken,
}

pub(crate) struct OperationService {
    runtime_id: RuntimeId,
    config: OperationConfig,
    operations: HashMap<OperationId, OperationEntry>,
    queued: VecDeque<OperationId>,
    terminal: VecDeque<OperationId>,
    active: usize,
    completion_tx: mpsc::Sender<OperationCompletion>,
    events: EventHub,
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
        completion_tx: mpsc::Sender<OperationCompletion>,
    ) -> Self {
        Self {
            runtime_id,
            config,
            operations: HashMap::new(),
            queued: VecDeque::new(),
            terminal: VecDeque::new(),
            active: 0,
            completion_tx,
            events: EventHub::new(event_config),
        }
    }

    pub(crate) fn start_fake(
        &mut self,
        request: FakeOperationRequest,
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
            kind: OperationKind::Fake,
            state: OperationState::Queued,
            phase: "queued".to_owned(),
            revision: 1,
            created_at: OffsetDateTime::now_utc(),
            started_at: None,
            finished_at: None,
            error: None,
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
            let completion_tx = self.completion_tx.clone();
            let default_deadline = self.config.default_deadline_seconds;
            tokio::spawn(async move {
                let result = run_fake(request, cancellation, default_deadline).await;
                let _ = completion_tx.send(OperationCompletion { id, result }).await;
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
    entry.snapshot.phase = "running".to_owned();
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
        WorkerResult::Completed => (OperationState::Completed, "completed", None),
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
                    FakeOutcome::Succeed => WorkerResult::Completed,
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
