from pathlib import Path

from app.storage import (
    CACHE_DB_PATH,
    CACHE_FILES_DIR,
    ROOT_DIR,
    IMAGE_CACHE_LEGACY_INDEX_PATH,
)
from lib.cache.image_cache_db import ImageCacheDB


image_cache_db = ImageCacheDB(
    cache_dir=ROOT_DIR,
    files_dir=CACHE_FILES_DIR,
    db_path=CACHE_DB_PATH,
    legacy_index_path=IMAGE_CACHE_LEGACY_INDEX_PATH,
)


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
