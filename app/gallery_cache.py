from datetime import timedelta

from app.debug_log import log_debug, log_exception
from app.lazy import LazyProxy
from app.storage import ensure_gallery_cache_dirs, get_storage_layout
from core.cache.gallery_cache import EHGalleryCache, GalleryCacheEntry
from core.provider.ehgrabber import ComicDetails, ThumbnailsResult


GALLERY_CACHE_TTL = timedelta(days=1)
GALLERY_CACHE_SCHEMA_VERSION = 2


def _create_gallery_cache() -> EHGalleryCache:
    return EHGalleryCache(
        get_storage_layout().cache_db,
        ttl=GALLERY_CACHE_TTL,
        ensure_dirs=ensure_gallery_cache_dirs,
        log_debug=log_debug,
        log_exception=log_exception,
    )


gallery_cache = LazyProxy(_create_gallery_cache)


def get_eh_gallery_cache(comic_url: str) -> GalleryCacheEntry | None:
    try:
        return gallery_cache.get(comic_url)
    except Exception as ex:
        log_exception("画廊缓存", f"无法读取，按缓存未命中处理：{ex}")
        return None


def put_eh_gallery_cache(comic_url: str, details: ComicDetails, thumbnails: ThumbnailsResult):
    try:
        return gallery_cache.put(comic_url, details, thumbnails)
    except Exception as ex:
        log_exception("画廊缓存", f"无法写入，将在不使用缓存的情况下继续：{ex}")
        return None


def clear_gallery_cache() -> None:
    try:
        gallery_cache.clear()
    except Exception as ex:
        log_exception("画廊缓存", f"无法清除：{ex}")


__all__ = [
    "GALLERY_CACHE_TTL",
    "GALLERY_CACHE_SCHEMA_VERSION",
    "GalleryCacheEntry",
    "clear_gallery_cache",
    "get_eh_gallery_cache",
    "put_eh_gallery_cache",
]
