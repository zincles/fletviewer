import hashlib
import json
import mimetypes
import shutil
import threading
from pathlib import Path
from urllib.parse import urlsplit

from app.storage import ROOT_DIR

IMAGE_CACHE_DIR = ROOT_DIR / "Data" / "ImageCache"
IMAGE_CACHE_FILES_DIR = IMAGE_CACHE_DIR / "files"
IMAGE_CACHE_INDEX_PATH = IMAGE_CACHE_DIR / "index.json"

_INDEX_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, str] | None = None


def ensure_image_cache_dirs() -> None:
    IMAGE_CACHE_FILES_DIR.mkdir(parents=True, exist_ok=True)


def normalize_url(url: str) -> str:
    return url.strip()


def resource_id_for_url(url: str) -> str:
    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extension_from_mime_or_url(mime: str | None, url: str) -> str:
    if mime:
        mime = mime.split(";", 1)[0].strip().lower()
        known = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
            "image/svg+xml": ".svg",
        }
        ext = known.get(mime)
        if ext:
            return ext
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed

    path = urlsplit(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".img"


def filename_for_url(url: str, mime: str | None = None) -> str:
    return f"{resource_id_for_url(url)}{extension_from_mime_or_url(mime, url)}"


def path_for_filename(filename: str) -> Path:
    shard1 = filename[:2]
    shard2 = filename[2:4]
    return IMAGE_CACHE_FILES_DIR / shard1 / shard2 / filename


def _load_index_unlocked() -> dict[str, str]:
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    ensure_image_cache_dirs()
    if IMAGE_CACHE_INDEX_PATH.exists():
        with open(IMAGE_CACHE_INDEX_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _INDEX_CACHE = {str(k): str(v) for k, v in data.items()}
        else:
            _INDEX_CACHE = {}
    else:
        _INDEX_CACHE = {}
    return _INDEX_CACHE


def _save_index_unlocked(index: dict[str, str]) -> None:
    ensure_image_cache_dirs()
    tmp_path = IMAGE_CACHE_INDEX_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False, sort_keys=True)
    tmp_path.replace(IMAGE_CACHE_INDEX_PATH)


def get_cached_filename(url: str) -> str | None:
    normalized = normalize_url(url)
    with _INDEX_LOCK:
        index = _load_index_unlocked()
        return index.get(normalized)


def get_cached_path(url: str) -> Path | None:
    filename = get_cached_filename(url)
    if not filename:
        return None
    path = path_for_filename(filename)
    if path.exists():
        return path
    return None


def drop_cached_filename(url: str) -> str | None:
    normalized = normalize_url(url)
    with _INDEX_LOCK:
        index = _load_index_unlocked()
        removed = index.pop(normalized, None)
        if removed is not None:
            _save_index_unlocked(index)
        return removed


def repair_stale_entry(url: str) -> bool:
    """删除指向缺失文件的索引项，避免后续反复命中脏引用。"""
    normalized = normalize_url(url)
    with _INDEX_LOCK:
        index = _load_index_unlocked()
        filename = index.get(normalized)
        if not filename:
            return False
        if path_for_filename(filename).exists():
            return False
        index.pop(normalized, None)
        _save_index_unlocked(index)
        return True


def put_cached_filename(url: str, filename: str) -> None:
    normalized = normalize_url(url)
    with _INDEX_LOCK:
        index = _load_index_unlocked()
        index[normalized] = filename
        _save_index_unlocked(index)


def cached_path_for_url(url: str, mime: str | None = None) -> Path:
    filename = filename_for_url(url, mime=mime)
    return path_for_filename(filename)


def clear_image_cache() -> None:
    """清空所有图片缓存文件和索引。"""
    global _INDEX_CACHE
    with _INDEX_LOCK:
        shutil.rmtree(IMAGE_CACHE_FILES_DIR, ignore_errors=True)
        if IMAGE_CACHE_INDEX_PATH.exists():
            IMAGE_CACHE_INDEX_PATH.unlink()
        _INDEX_CACHE = {}
        ensure_image_cache_dirs()
