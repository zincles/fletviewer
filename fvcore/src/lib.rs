//! Pure Rust application core for FletViewer and other frontends.

#![forbid(unsafe_code)]
#![warn(missing_docs)]

mod archive;
mod config;
mod control;
mod error;
mod gallery;
mod id;
mod image;
mod operation;
mod operation_service;
mod provider;
mod runtime;
mod session;
mod snapshot;
mod storage;
mod webui;

pub use archive::{ArchiveTaskSnapshot, ArchiveTaskState, EhArchiveDownloadRequest};
pub use config::{
    ControlConfig, CoreConfig, EventConfig, ImageConfig, NetworkConfig, OperationConfig,
    ProviderProfileConfig, StorageConfig,
};
pub use error::{CoreError, ErrorCode};
pub use gallery::LocalGallerySnapshot;
pub use id::{OperationId, RuntimeId};
pub use image::{ContentMd5, ImageResource, ImageResourceDescriptor, ResourceKey, ResourceSource};
pub use operation::{
    BooruOriginalFetchRequest, CoreEvent, CoreEventSubject, EhPageFetchRequest, ErrorSnapshot,
    EventBatch, EventStreamItem, EventSubscription, FakeOperationRequest, FakeOutcome,
    OperationKind, OperationSnapshot, OperationState, PixivPageFetchRequest,
};
pub use provider::booru::{BooruPost, BooruSearchResult, ImageVariant};
pub use provider::eh::{
    EhArchiveDelivery, EhArchiveOption, EhArchiveOptions, EhArchiveVariant, EhComment,
    EhGalleryDetail, EhGalleryRef, EhGallerySummary, EhGalleryVersion, EhHomePage,
    EhImageResolution, EhPageCursor, EhPageDirection, EhThumbnail, EhThumbnailPage,
};
pub use provider::pixiv::{PixivIllust, PixivPage, PixivUser};
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
