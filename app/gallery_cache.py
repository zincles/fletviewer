from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.debug_log import log_debug, log_exception
from app.storage import GALLERY_CACHE_DIR, ensure_gallery_cache_dirs
from lib.provider.ehgrabber import ComicDetails, ThumbnailItem, ThumbnailsResult, EHentaiClient


GALLERY_CACHE_TTL = timedelta(days=1)


@dataclass(slots=True)
class GalleryCacheEntry:
    details: ComicDetails
    thumbnails: ThumbnailsResult
    path: Path
    from_cache: bool = True


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


def _eh_cache_path(comic_url: str) -> Path:
    gid, token = EHentaiClient.parse_url(comic_url)
    return GALLERY_CACHE_DIR / "ehentai" / f"{gid}_{token}.json"


def get_eh_gallery_cache(comic_url: str) -> GalleryCacheEntry | None:
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

        details = ComicDetails(**data["details"])
        thumbs_data = data["thumbnails"]
        items = [ThumbnailItem(**item) for item in thumbs_data.get("items", [])]
        thumbnails = ThumbnailsResult(
            thumbnails=list(thumbs_data.get("thumbnails", [])),
            urls=list(thumbs_data.get("urls", [])),
            items=items,
            next_page=thumbs_data.get("next_page"),
        )
        log_debug("gallery_cache", f"hit {comic_url} path={path}")
        return GalleryCacheEntry(details=details, thumbnails=thumbnails, path=path)
    except Exception as ex:
        log_exception("gallery_cache", f"read failed {path}: {ex}")
        return None


def put_eh_gallery_cache(comic_url: str, details: ComicDetails, thumbnails: ThumbnailsResult) -> Path:
    ensure_gallery_cache_dirs()
    path = _eh_cache_path(comic_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    gid, token = EHentaiClient.parse_url(comic_url)
    payload = {
        "schema_version": 1,
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
