//! Immutable Runtime state exposed to embedded and HTTP callers.

use crate::{ProfileSnapshot, RuntimeId};
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
    /// Latest Runtime event sequence.
    pub latest_event_sequence: u64,
    /// Immutable snapshots of configured Provider session generations.
    pub profiles: Vec<ProfileSnapshot>,
}

/// Immutable summary of the four storage domains.
#[derive(Clone, Debug, Serialize)]
pub struct StorageSnapshot {
    /// Internal storage schema version.
    pub schema_version: u32,
    /// Canonical durable Data directory.
    pub data: String,
    /// Canonical disposable Cache directory.
    pub cache: String,
    /// Canonical durable Downloads directory.
    pub downloads: String,
    /// Canonical disposable Temp directory.
    pub temp: String,
    /// Core state database size in bytes.
    pub database_bytes: u64,
}
