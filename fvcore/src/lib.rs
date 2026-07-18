//! Pure Rust application core for FletViewer and other frontends.

#![forbid(unsafe_code)]
#![warn(missing_docs)]

mod config;
mod control;
mod error;
mod id;
mod operation;
mod operation_service;
mod runtime;
mod session;
mod snapshot;
mod storage;

pub use config::{
    ControlConfig, CoreConfig, EventConfig, NetworkConfig, OperationConfig, ProviderProfileConfig,
    StorageConfig,
};
pub use error::{CoreError, ErrorCode};
pub use id::{OperationId, RuntimeId};
pub use operation::{
    CoreEvent, ErrorSnapshot, EventBatch, EventStreamItem, EventSubscription, FakeOperationRequest,
    FakeOutcome, OperationKind, OperationSnapshot, OperationState,
};
pub use runtime::{CoreBuilder, CoreHandle, CoreRuntime};
pub use session::{ProfileKey, ProfileProbeSnapshot, ProfileSnapshot};
pub use snapshot::{CoreSnapshot, RuntimeState, StorageSnapshot};

/// Crate version compiled into the current artifact.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Returns the semantic version of this `fvcore` build.
#[must_use]
pub const fn version() -> &'static str {
    VERSION
}

#[cfg(test)]
mod tests {
    #[test]
    fn version_matches_package_metadata() {
        assert_eq!(super::version(), env!("CARGO_PKG_VERSION"));
    }
}
