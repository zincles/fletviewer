from pathlib import Path

from app.lazy import LazyProxy
from app.storage import IMAGE_CACHE_LEGACY_INDEX_PATH, get_storage_layout
from core.cache.image_cache_db import ImageCacheDB, ImageCacheStats


def _create_image_cache_db() -> ImageCacheDB:
    layout = get_storage_layout()
    return ImageCacheDB(
        cache_dir=layout.paths.cache,
        files_dir=layout.cache_files,
        db_path=layout.cache_db,
        legacy_index_path=IMAGE_CACHE_LEGACY_INDEX_PATH,
    )


image_cache_db = LazyProxy(_create_image_cache_db)


IMAGE_CACHE_INDEX_PATH = IMAGE_CACHE_LEGACY_INDEX_PATH


def ensure_image_cache_dirs() -> None:
    image_cache_db.ensure_dirs()


def normalize_url(url: str) -> str:
    return image_cache_db.normalize_url(url)


def resource_id_for_url(url: str) -> str:
    return image_cache_db.resource_id_for_url(url)


def extension_from_mime_or_url(mime: str | None, url: str) -> str:
    return image_cache_db.extension_from_mime_or_url(mime, url)


def filename_for_url(url: str, mime: str | None = None) -> str:
    return image_cache_db.filename_for_url(url, mime=mime)


def path_for_filename(filename: str) -> Path:
    return image_cache_db.path_for_filename(filename)


def get_cached_filename(url: str) -> str | None:
    return image_cache_db.get_cached_filename(url)


def get_cached_path(url: str) -> Path | None:
    return image_cache_db.get_cached_path(url)


def drop_cached_filename(url: str) -> str | None:
    return image_cache_db.drop_cached_filename(url)


def repair_stale_entry(url: str) -> bool:
    return image_cache_db.repair_stale_entry(url)


def put_cached_filename(url: str, filename: str, *, kind: str = "unknown") -> None:
    image_cache_db.put_cached_filename(url, filename, kind=kind)


def cached_path_for_url(url: str, mime: str | None = None) -> Path:
    return image_cache_db.cached_path_for_url(url, mime=mime)


def get_gallery_page_cached_filename(provider: str, gid: str, token: str, page_idx: int) -> str | None:
    return image_cache_db.get_gallery_page_cached_filename(provider, gid, token, page_idx)


def get_gallery_page_cached_path(provider: str, gid: str, token: str, page_idx: int) -> Path | None:
    return image_cache_db.get_gallery_page_cached_path(provider, gid, token, page_idx)


def put_gallery_page_cached_filename(
    provider: str,
    gid: str,
    token: str,
    page_idx: int,
    filename: str,
    *,
    kind: str = "original",
) -> None:
    image_cache_db.put_gallery_page_cached_filename(provider, gid, token, page_idx, filename, kind=kind)


def drop_gallery_page_cached_filename(provider: str, gid: str, token: str, page_idx: int) -> str | None:
    return image_cache_db.drop_gallery_page_cached_filename(provider, gid, token, page_idx)


def repair_gallery_page_entry(provider: str, gid: str, token: str, page_idx: int) -> bool:
    return image_cache_db.repair_gallery_page_entry(provider, gid, token, page_idx)


def clear_image_cache() -> None:
    image_cache_db.clear()


def get_image_cache_stats() -> ImageCacheStats:
    return image_cache_db.stats()
