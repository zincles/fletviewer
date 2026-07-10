from datetime import timedelta

from app.debug_log import log_debug, log_exception
from app.storage import CACHE_DB_PATH, ensure_dirs
from core.cache.gallery_cache import EHGalleryCache, GalleryCacheEntry
from core.provider.ehgrabber import ComicDetails, ThumbnailsResult


GALLERY_CACHE_TTL = timedelta(days=1)
GALLERY_CACHE_SCHEMA_VERSION = 2


gallery_cache = EHGalleryCache(
    CACHE_DB_PATH,
    ttl=GALLERY_CACHE_TTL,
    ensure_dirs=ensure_dirs,
    log_debug=log_debug,
    log_exception=log_exception,
)


def get_eh_gallery_cache(comic_url: str) -> GalleryCacheEntry | None:
    return gallery_cache.get(comic_url)


def put_eh_gallery_cache(comic_url: str, details: ComicDetails, thumbnails: ThumbnailsResult):
    return gallery_cache.put(comic_url, details, thumbnails)


def clear_gallery_cache() -> None:
    gallery_cache.clear()


__all__ = [
    "GALLERY_CACHE_TTL",
    "GALLERY_CACHE_SCHEMA_VERSION",
    "GalleryCacheEntry",
    "clear_gallery_cache",
    "get_eh_gallery_cache",
    "put_eh_gallery_cache",
]
