//! Pure Rust application core for FletViewer and other frontends.

#![deny(unsafe_code)]
#![warn(missing_docs)]

/// Narrow flutter_rust_bridge API exposed to Flutter desktop and Android.
pub mod api;
mod archive;
mod config;
mod control;
mod download_view;
mod error;
#[allow(unsafe_code)]
#[allow(missing_docs)]
mod frb_generated;
mod gallery;
mod id;
mod image;
mod image_download;
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
    ControlConfig, CoreConfig, EffectiveConfigSnapshot, EffectiveNetworkConfig,
    EffectiveProviderProfileConfig, EventConfig, ImageConfig, ImageDownloadConfig, NetworkConfig,
    OperationConfig, ProviderProfileConfig, StorageConfig,
};
pub use control::{ApiContract, ApiRouteContract, ErrorBody, EventContract, ResourceContract};
pub use download_view::{DownloadTaskStatus, DownloadTaskView};
pub use error::{CoreError, ErrorCode};
pub use gallery::{
    ComicInfoSnapshot, LocalGalleryDeleteConfirmation, LocalGalleryDeleteRequest,
    LocalGalleryDeleteResult, LocalGalleryDetail, LocalGalleryExport, LocalGalleryExportDescriptor,
    LocalGalleryInventory, LocalGalleryInventoryEntry, LocalGalleryInventoryIssue,
    LocalGalleryInventoryStatus, LocalGalleryPage, LocalGalleryResource,
    LocalGalleryResourceDescriptor, LocalGalleryResourceKind, LocalGallerySummary,
};
pub use id::{OperationId, RuntimeId};
pub use image::{
    ContentMd5, ImageCacheMaintenance, ImageCacheSemanticSnapshot, ImageCacheSnapshot,
    ImageResource, ImageResourceDescriptor, ResourceKey, ResourceSource,
};
pub use image_download::{
    BooruImageDownloadRequest, ImageDownloadKind, ImageDownloadState, ImageDownloadStats,
    ImageDownloadTaskSnapshot, PixivImageDownloadRequest,
};
pub use operation::{
    BooruOriginalFetchRequest, CoreEvent, CoreEventSubject, EhPageFetchRequest, ErrorSnapshot,
    EventBatch, EventStreamItem, EventSubscription, FakeOperationRequest, FakeOutcome,
    OperationKind, OperationSnapshot, OperationState, PixivPageFetchRequest,
};
pub use provider::booru::{
    BooruPost, BooruSearchResult, BooruTagSuggestion, BooruTagSuggestions, ImageVariant,
};
pub use provider::eh::{
    EhArchiveDelivery, EhArchiveOption, EhArchiveOptions, EhArchiveVariant, EhComment,
    EhGalleryDetail, EhGalleryRef, EhGallerySummary, EhGalleryVersion, EhHomePage,
    EhImageResolution, EhPageCursor, EhPageDirection, EhThumbnail, EhThumbnailPage,
};
pub use provider::pixiv::{
    PixivBookmarkVisibility, PixivBookmarksResult, PixivFollowingResult, PixivFollowingVisibility,
    PixivIllust, PixivPage, PixivRankingItem, PixivRankingResult, PixivRecommendationResult,
    PixivSearchItem, PixivSearchResult, PixivUser,
};
pub use runtime::{CoreBuilder, CoreHandle, CoreRuntime};
pub use session::{ProfileKey, ProfileProbeSnapshot, ProfileSnapshot};
pub use snapshot::{CoreSnapshot, RuntimeState, StorageSnapshot};
pub use storage::FavoriteSearch;

/// Installs the default stderr tracing subscriber once for Core entry points.
///
/// `RUST_LOG` controls filtering. If an embedding host has already installed a
/// global subscriber, that subscriber remains authoritative.
pub fn init_tracing() {
    use tracing_subscriber::EnvFilter;

    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    let _ = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(std::io::stderr)
        .try_init();
}

/// Crate version compiled into the current artifact.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Stable HTTP/SSE/resource protocol implemented by this build.
///
/// Additive optional response fields do not change this value. Breaking route,
/// field type, or semantic changes require a new protocol version.
pub const API_PROTOCOL_VERSION: u32 = 1;

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
