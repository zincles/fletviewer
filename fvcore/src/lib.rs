//! Pure Rust application core for FletViewer and other frontends.

#![forbid(unsafe_code)]
#![warn(missing_docs)]

mod archive;
mod config;
mod control;
mod download_view;
mod error;
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
