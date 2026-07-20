//! Immutable operation and event contracts.

use crate::{
    ArchiveTaskSnapshot, EhGalleryRef, ErrorCode, ImageResourceDescriptor, OperationId, ProfileKey,
    ResourceSource, RuntimeId,
};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use time::OffsetDateTime;
use tokio::sync::broadcast;

/// Operation categories exposed by the Core.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationKind {
    /// Deterministic Foundation test operation.
    Fake,
    /// Fetches and verifies one image resource.
    ImageFetch,
}

/// Lifecycle state for one operation.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationState {
    /// Waiting for an execution slot.
    Queued,
    /// Worker is executing.
    Running,
    /// Worker completed successfully.
    Completed,
    /// Worker terminated with an error.
    Failed,
    /// Caller or Runtime cancelled the operation.
    Cancelled,
}

impl OperationState {
    /// Returns whether no further transition is allowed.
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Completed | Self::Failed | Self::Cancelled)
    }
}

/// Safe serialized error attached to a failed operation.
#[derive(Clone, Debug, Serialize)]
pub struct ErrorSnapshot {
    /// Stable machine-readable error code.
    pub code: ErrorCode,
    /// Safe human-readable message.
    pub message: String,
    /// Whether retrying a new operation may succeed.
    pub retryable: bool,
}

/// Immutable state of one operation.
#[derive(Clone, Debug, Serialize)]
pub struct OperationSnapshot {
    /// Operation identifier.
    pub id: OperationId,
    /// Operation category.
    pub kind: OperationKind,
    /// Current lifecycle state.
    pub state: OperationState,
    /// Stable phase identifier.
    pub phase: String,
    /// Monotonically increasing operation revision.
    pub revision: u64,
    /// UTC creation timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub created_at: OffsetDateTime,
    /// UTC worker start timestamp.
    #[serde(with = "time::serde::rfc3339::option")]
    pub started_at: Option<OffsetDateTime>,
    /// UTC terminal timestamp.
    #[serde(with = "time::serde::rfc3339::option")]
    pub finished_at: Option<OffsetDateTime>,
    /// Error for failed operations.
    pub error: Option<ErrorSnapshot>,
    /// Bytes processed by the current resource phase.
    pub bytes_done: u64,
    /// Expected total bytes when known.
    pub bytes_total: Option<u64>,
    /// Cache or transfer layer currently serving the operation.
    pub source: Option<ResourceSource>,
    /// Whether this caller joined a transfer used by multiple operations.
    pub shared: bool,
    /// Verified resource descriptor after a successful fetch.
    pub resource: Option<ImageResourceDescriptor>,
}

/// Terminal behavior for a fake operation.
#[derive(Clone, Copy, Debug, Default, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FakeOutcome {
    /// Complete successfully.
    #[default]
    Succeed,
    /// Fail with a deterministic internal error.
    Fail,
}

/// Request used to exercise operation infrastructure before Providers exist.
#[derive(Clone, Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct FakeOperationRequest {
    /// Worker duration in milliseconds. Defaults to `100`.
    pub duration_ms: u64,
    /// Optional deadline override in milliseconds. Defaults to `None`.
    pub deadline_ms: Option<u64>,
    /// Terminal behavior. Defaults to [`FakeOutcome::Succeed`].
    pub outcome: FakeOutcome,
}

/// Request for one Provider-declared Booru original image.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BooruOriginalFetchRequest {
    /// Configured Danbooru or Gelbooru profile.
    pub profile: ProfileKey,
    /// Provider post identifier.
    pub post_id: u64,
}

/// Request for one original page of a Pixiv illustration.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PixivPageFetchRequest {
    /// Configured Pixiv profile.
    pub profile: ProfileKey,
    /// Numeric illustration ID.
    pub illust_id: String,
    /// Zero-based page index.
    pub page: u32,
}

/// Request for one original page of an EH gallery.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EhPageFetchRequest {
    /// Configured EH profile.
    pub profile: ProfileKey,
    /// Stable EH gallery identity.
    pub gallery: EhGalleryRef,
    /// Zero-based gallery page index.
    pub page: u32,
    /// Optional EH reload nonce returned by a previous resolution attempt.
    pub nl: Option<String>,
}

impl Default for FakeOperationRequest {
    fn default() -> Self {
        Self {
            duration_ms: 100,
            deadline_ms: None,
            outcome: FakeOutcome::Succeed,
        }
    }
}

/// One revisioned Runtime event.
#[derive(Clone, Debug, Serialize)]
pub struct CoreEvent {
    /// Monotonic sequence within one Runtime.
    pub sequence: u64,
    /// Runtime that emitted this event.
    pub runtime_id: RuntimeId,
    /// Subject revision represented by this event.
    pub revision: u64,
    /// Revisioned subject represented by this event.
    #[serde(flatten)]
    pub subject: CoreEventSubject,
}

/// Revisioned Runtime event subject.
#[derive(Clone, Debug, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum CoreEventSubject {
    /// Temporary operation transition or progress.
    Operation {
        /// Operation affected by this event.
        operation_id: OperationId,
        /// Current operation state.
        state: OperationState,
        /// Current operation phase.
        phase: String,
        /// Bytes processed at this revision.
        bytes_done: u64,
        /// Expected total bytes when known.
        bytes_total: Option<u64>,
        /// Cache or transfer layer represented by this event.
        source: Option<ResourceSource>,
        /// Whether the operation currently shares a transfer.
        shared: bool,
        /// Verified resource descriptor when the operation completed successfully.
        resource: Option<ImageResourceDescriptor>,
    },
    /// Persistent EH Archive task transition or progress.
    ArchiveTask {
        /// Complete immutable Archive task snapshot at this revision.
        task: ArchiveTaskSnapshot,
    },
}

/// Cursor-based event replay result.
#[derive(Clone, Debug, Serialize)]
pub struct EventBatch {
    /// Events after the requested cursor.
    pub events: Vec<CoreEvent>,
    /// Latest emitted sequence.
    pub latest_sequence: u64,
    /// Whether the cursor is older than the retained journal.
    pub resync_required: bool,
}

/// Next item produced by a live Core event subscription.
#[derive(Clone, Debug)]
pub enum EventStreamItem {
    /// One operation event.
    Event(Box<CoreEvent>),
    /// Subscriber lagged and must query snapshots before continuing.
    ResyncRequired,
    /// Runtime closed the event stream.
    Closed,
}

/// Live event subscription without exposing Tokio channel types.
pub struct EventSubscription {
    replay: VecDeque<CoreEvent>,
    receiver: broadcast::Receiver<CoreEvent>,
}

impl EventSubscription {
    pub(crate) fn new(replay: Vec<CoreEvent>, receiver: broadcast::Receiver<CoreEvent>) -> Self {
        Self {
            replay: replay.into(),
            receiver,
        }
    }

    /// Waits for the next replayed or live event.
    pub async fn next(&mut self) -> EventStreamItem {
        if let Some(event) = self.replay.pop_front() {
            return EventStreamItem::Event(Box::new(event));
        }
        match self.receiver.recv().await {
            Ok(event) => EventStreamItem::Event(Box::new(event)),
            Err(broadcast::error::RecvError::Lagged(_)) => EventStreamItem::ResyncRequired,
            Err(broadcast::error::RecvError::Closed) => EventStreamItem::Closed,
        }
    }
}
