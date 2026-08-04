//! Immutable Runtime state exposed to embedded and HTTP callers.

use crate::{ImageDownloadStats, ProfileSnapshot, RuntimeId};
use serde::Serialize;

/// Runtime lifecycle visible through every control adapter.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeState {
    /// Runtime resources are being initialized.
    Starting,
    /// Runtime accepts commands and queries.
    Ready,
    /// Runtime is rejecting new work and draining services.
    Stopping,
    /// Runtime has released all supervised services.
    Stopped,
}

/// Immutable summary of one Runtime instance.
#[derive(Clone, Debug, Serialize)]
pub struct CoreSnapshot {
    /// Stable HTTP/SSE/resource protocol version implemented by this Runtime.
    pub api_protocol_version: u32,
    /// Semantic version of the running Core build.
    pub core_version: String,
    /// Runtime identifier.
    pub runtime_id: RuntimeId,
    /// Human-readable instance name.
    pub instance_name: String,
    /// Current lifecycle state.
    pub state: RuntimeState,
    /// Monotonically increasing state revision.
    pub revision: u64,
    /// Seconds elapsed since this Runtime was created.
    pub uptime_seconds: u64,
    /// Whether the integrated HTTP control plane is listening.
    pub control_enabled: bool,
    /// Listening address when the control plane is enabled.
    pub control_listen: Option<String>,
    /// Number of commands currently waiting for the Runtime.
    pub queued_commands: usize,
    /// Current Core-owned storage state.
    pub storage: StorageSnapshot,
    /// Number of actively running operations.
    pub active_operations: usize,
    /// Number of operations waiting for a worker slot.
    pub queued_operations: usize,
    /// Number of terminal operation snapshots retained in memory.
    pub retained_operations: usize,
    /// Persistent single-image download task accounting.
    pub image_downloads: ImageDownloadStats,
    /// Latest Runtime event sequence.
    pub latest_event_sequence: u64,
    /// Immutable snapshots of configured Provider session generations.
    pub profiles: Vec<ProfileSnapshot>,
}

/// Immutable summary of the four storage domains without exposing server paths.
#[derive(Clone, Debug, Serialize)]
pub struct StorageSnapshot {
    /// Internal storage schema version.
    pub schema_version: u32,
    /// Opaque identity of the canonical durable Data directory.
    pub data_identity: String,
    /// Opaque identity of the canonical disposable Cache directory.
    pub cache_identity: String,
    /// Opaque identity of the canonical durable Downloads directory.
    pub downloads_identity: String,
    /// Opaque identity of the canonical disposable Temp directory.
    pub temp_identity: String,
    /// Core state database size in bytes.
    pub database_bytes: u64,
}
