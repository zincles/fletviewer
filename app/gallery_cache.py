from __future__ import annotations

import dataclasses
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.debug_log import log_debug, log_exception
from app.storage import GALLERY_CACHE_DIR, ensure_gallery_cache_dirs
from lib.provider.ehgrabber import Comment, ComicDetails, GalleryVersion, ThumbnailItem, ThumbnailsResult, EHentaiClient


GALLERY_CACHE_TTL = timedelta(days=1)
GALLERY_CACHE_SCHEMA_VERSION = 2


@dataclass(slots=True)
class GalleryCacheEntry:
    """一次画廊详情缓存命中的返回结构。"""

    details: ComicDetails
    thumbnails: ThumbnailsResult
    path: Path
    from_cache: bool = True


def _now() -> datetime:
    """返回带本地时区信息的当前时间。"""
    return datetime.now(timezone.utc).astimezone()


def _iso(dt: datetime) -> str:
    """把时间格式化为秒级 ISO 字符串。"""
    return dt.isoformat(timespec="seconds")


def _parse_iso(value: str) -> datetime | None:
    """解析 ISO 时间；空值或非法值返回 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _eh_cache_path(comic_url: str) -> Path:
    """根据 EH 画廊 URL 计算本地详情缓存文件路径。"""
    gid, token = EHentaiClient.parse_url(comic_url)
    return GALLERY_CACHE_DIR / "ehentai" / f"{gid}_{token}.json"


def _dataclass_fields(cls) -> set[str]:
    """返回 dataclass 字段名集合，用于忽略旧/新缓存里的未知字段。"""
    return {field.name for field in dataclasses.fields(cls)}


def _comment_from_dict(value) -> Comment:
    """从 JSON 数据恢复 Comment。"""
    if isinstance(value, Comment):
        return value
    data = value if isinstance(value, dict) else {}
    fields = _dataclass_fields(Comment)
    return Comment(**{key: data.get(key) for key in fields if key in data})


def _gallery_version_from_dict(value) -> GalleryVersion:
    """从 JSON 数据恢复 GalleryVersion。"""
    if isinstance(value, GalleryVersion):
        return value
    data = value if isinstance(value, dict) else {}
    fields = _dataclass_fields(GalleryVersion)
    return GalleryVersion(**{key: data.get(key) for key in fields if key in data})


def _comic_details_from_dict(value) -> ComicDetails:
    """从缓存 JSON 恢复 provider 的 ComicDetails canonical model。"""
    data = dict(value or {})
    data["comments"] = [_comment_from_dict(item) for item in data.get("comments", [])]
    data["newer_versions"] = [_gallery_version_from_dict(item) for item in data.get("newer_versions", [])]
    fields = _dataclass_fields(ComicDetails)
    return ComicDetails(**{key: data.get(key) for key in fields if key in data})


def _thumbnails_result_from_dict(value) -> ThumbnailsResult:
    """从缓存 JSON 恢复 ThumbnailsResult。"""
    data = dict(value or {})
    items = [item if isinstance(item, ThumbnailItem) else ThumbnailItem(**item) for item in data.get("items", [])]
    return ThumbnailsResult(
        thumbnails=list(data.get("thumbnails", [])),
        urls=list(data.get("urls", [])),
        items=items,
        next_page=data.get("next_page"),
    )


def get_eh_gallery_cache(comic_url: str) -> GalleryCacheEntry | None:
    """读取 EH 画廊详情缓存；不存在、过期或损坏时返回 None。"""
    ensure_gallery_cache_dirs()
    path = _eh_cache_path(comic_url)
    if not path.exists():
        log_debug("gallery_cache", f"miss {comic_url}")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expires_at = _parse_iso(str(data.get("expires_at", "")))
        if expires_at is None or expires_at <= _now():
            log_debug("gallery_cache", f"expired {comic_url} path={path}")
            return None

        details = _comic_details_from_dict(data["details"])
        thumbnails = _thumbnails_result_from_dict(data["thumbnails"])
        log_debug("gallery_cache", f"hit {comic_url} path={path}")
        return GalleryCacheEntry(details=details, thumbnails=thumbnails, path=path)
    except Exception as ex:
        log_exception("gallery_cache", f"read failed {path}: {ex}")
        return None


def put_eh_gallery_cache(comic_url: str, details: ComicDetails, thumbnails: ThumbnailsResult) -> Path:
    """写入 EH 画廊详情缓存，默认有效期为 1 天。"""
    ensure_gallery_cache_dirs()
    path = _eh_cache_path(comic_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    gid, token = EHentaiClient.parse_url(comic_url)
    payload = {
        "schema_version": GALLERY_CACHE_SCHEMA_VERSION,
        "provider": "ehentai",
        "source": {
            "gid": str(gid),
            "token": token,
            "gallery_url": comic_url,
            "domain": urlsplit(comic_url).netloc or "e-hentai.org",
        },
        "details": dataclasses.asdict(details),
        "thumbnails": dataclasses.asdict(thumbnails),
        "created_at": _iso(now),
        "updated_at": _iso(now),
        "expires_at": _iso(now + GALLERY_CACHE_TTL),
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    log_debug("gallery_cache", f"written {comic_url} path={path}")
    return path


def clear_gallery_cache() -> None:
    """清空所有画廊详情缓存。"""
    shutil.rmtree(GALLERY_CACHE_DIR, ignore_errors=True)
    ensure_gallery_cache_dirs()
