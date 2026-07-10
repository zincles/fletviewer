from __future__ import annotations

import dataclasses
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from core.provider.ehgrabber import Comment, ComicDetails, EHentaiClient, GalleryVersion, ThumbnailItem, ThumbnailsResult


GALLERY_CACHE_SCHEMA_VERSION = 2


@dataclass(slots=True)
class GalleryCacheEntry:
    details: ComicDetails
    thumbnails: ThumbnailsResult
    path: Path
    from_cache: bool = True


class EHGalleryCache:
    def __init__(
        self,
        db_path: Path,
        *,
        ttl: timedelta = timedelta(days=1),
        ensure_dirs: Callable[[], None] | None = None,
        log_debug: Callable[[str, str], None] | None = None,
        log_exception: Callable[[str, str], None] | None = None,
    ):
        self.db_path = db_path
        self.ttl = ttl
        self._ensure_dirs = ensure_dirs
        self._log_debug = log_debug or (lambda _area, _message: None)
        self._log_exception = log_exception or (lambda _area, _message: None)

    def get(self, comic_url: str) -> GalleryCacheEntry | None:
        self._ensure()
        gid, token = EHentaiClient.parse_url(comic_url)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT gallery_url, details_json, thumbnails_json, expires_at, schema_version
                FROM eh_gallery_cache WHERE gid = ? AND token = ?
                """,
                (str(gid), token),
            ).fetchone()
        if not row:
            self._debug(f"miss {comic_url}")
            return None
        try:
            gallery_url, details_json, thumbnails_json, expires_at_raw, schema_version = row
            if int(schema_version or 0) != GALLERY_CACHE_SCHEMA_VERSION:
                self._debug(f"schema miss {comic_url}")
                return None
            expires_at = _parse_iso(str(expires_at_raw or ""))
            if expires_at is None or expires_at <= _now():
                self._debug(f"expired {comic_url}")
                return None
            details = _comic_details_from_dict(json.loads(details_json))
            thumbnails = _thumbnails_result_from_dict(json.loads(thumbnails_json))
            self._debug(f"hit {comic_url}")
            return GalleryCacheEntry(details=details, thumbnails=thumbnails, path=self.db_path)
        except Exception as ex:
            self._exception(f"read failed {comic_url}: {ex}")
            return None

    def put(self, comic_url: str, details: ComicDetails, thumbnails: ThumbnailsResult) -> Path:
        self._ensure()
        now = _now()
        gid, token = EHentaiClient.parse_url(comic_url)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO eh_gallery_cache(
                    gid, token, gallery_url, domain, details_json, thumbnails_json,
                    created_at, expires_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gid, token) DO UPDATE SET
                    gallery_url = excluded.gallery_url,
                    domain = excluded.domain,
                    details_json = excluded.details_json,
                    thumbnails_json = excluded.thumbnails_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at,
                    schema_version = excluded.schema_version
                """,
                (
                    str(gid),
                    token,
                    comic_url,
                    urlsplit(comic_url).netloc or "e-hentai.org",
                    json.dumps(dataclasses.asdict(details), ensure_ascii=False),
                    json.dumps(dataclasses.asdict(thumbnails), ensure_ascii=False),
                    _iso(now),
                    _iso(now + self.ttl),
                    GALLERY_CACHE_SCHEMA_VERSION,
                ),
            )
        self._debug(f"written {comic_url}")
        return self.db_path

    def clear(self) -> None:
        self._ensure()
        with self._connect() as conn:
            conn.execute("DELETE FROM eh_gallery_cache")

    def _ensure(self) -> None:
        if self._ensure_dirs:
            self._ensure_dirs()
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eh_gallery_cache (
                    gid TEXT NOT NULL,
                    token TEXT NOT NULL,
                    gallery_url TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    thumbnails_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 2,
                    PRIMARY KEY (gid, token)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _debug(self, message: str) -> None:
        self._log_debug("gallery_cache", message)

    def _exception(self, message: str) -> None:
        self._log_exception("gallery_cache", message)


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _dataclass_fields(cls) -> set[str]:
    return {field.name for field in dataclasses.fields(cls)}


def _comment_from_dict(value) -> Comment:
    if isinstance(value, Comment):
        return value
    data = value if isinstance(value, dict) else {}
    fields = _dataclass_fields(Comment)
    return Comment(**{key: data.get(key) for key in fields if key in data})


def _gallery_version_from_dict(value) -> GalleryVersion:
    if isinstance(value, GalleryVersion):
        return value
    data = value if isinstance(value, dict) else {}
    fields = _dataclass_fields(GalleryVersion)
    return GalleryVersion(**{key: data.get(key) for key in fields if key in data})


def _comic_details_from_dict(value) -> ComicDetails:
    data = dict(value or {})
    data["comments"] = [_comment_from_dict(item) for item in data.get("comments", [])]
    data["newer_versions"] = [_gallery_version_from_dict(item) for item in data.get("newer_versions", [])]
    fields = _dataclass_fields(ComicDetails)
    return ComicDetails(**{key: data.get(key) for key in fields if key in data})


def _thumbnails_result_from_dict(value) -> ThumbnailsResult:
    data = dict(value or {})
    items = [item if isinstance(item, ThumbnailItem) else ThumbnailItem(**item) for item in data.get("items", [])]
    return ThumbnailsResult(
        thumbnails=list(data.get("thumbnails", [])),
        urls=list(data.get("urls", [])),
        items=items,
        next_page=data.get("next_page"),
    )
