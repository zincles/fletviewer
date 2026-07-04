from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.browser_session import browser_session
from app.debug_log import Timer, log_debug
from app.image_cache import (
    cached_path_for_url,
    drop_cached_filename,
    ensure_image_cache_dirs,
    filename_for_url,
    get_cached_filename,
    get_cached_path,
    path_for_filename,
    put_cached_filename,
    repair_stale_entry,
)


@dataclass(slots=True)
class ImageFetchResult:
    url: str
    path: Path
    data: bytes
    mime: str
    from_cache: bool


class ImageFetcherService:
    def __init__(self, max_workers: int = 6):
        ensure_image_cache_dirs()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="image-fetch")
        self._lock = threading.Lock()
        self._in_flight: dict[str, Future] = {}

    def fetch(self, url: str) -> ImageFetchResult:
        normalized = url.strip()
        log_debug("image", f"request {normalized}")
        with self._lock:
            future = self._in_flight.get(normalized)
            if future is None:
                log_debug("image", f"submit fetch {normalized}")
                future = self._executor.submit(self._fetch_impl, normalized)
                self._in_flight[normalized] = future
            else:
                log_debug("image", f"join in-flight {normalized}")
        try:
            return future.result()
        finally:
            with self._lock:
                if self._in_flight.get(normalized) is future:
                    self._in_flight.pop(normalized, None)

    def _fetch_impl(self, url: str) -> ImageFetchResult:
        cached_path = get_cached_path(url)
        if cached_path is not None:
            with Timer("image", f"cache read {cached_path}"):
                data = cached_path.read_bytes()
            mime = self._guess_mime(cached_path)
            log_debug("image", f"cache hit url={url} bytes={len(data)} mime={mime}")
            return ImageFetchResult(url=url, path=cached_path, data=data, mime=mime, from_cache=True)

        cached_filename = get_cached_filename(url)
        if cached_filename:
            stale_path = path_for_filename(cached_filename)
            if stale_path.exists():
                with Timer("image", f"cache read {stale_path}"):
                    data = stale_path.read_bytes()
                mime = self._guess_mime(stale_path)
                log_debug("image", f"cache hit stale-index url={url} bytes={len(data)} mime={mime}")
                return ImageFetchResult(url=url, path=stale_path, data=data, mime=mime, from_cache=True)
            log_debug("image", f"stale index repaired url={url} filename={cached_filename}")
            repair_stale_entry(url)

        log_debug("image", f"cache miss url={url}")
        response = browser_session.get(url, headers={"Referer": "https://e-hentai.org/"}, timeout=20)
        response.raise_for_status()
        mime = response.headers.get("Content-Type", "image/jpeg").split(";", 1)[0].strip()
        filename = filename_for_url(url, mime=mime)
        path = cached_path_for_url(url, mime=mime)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with Timer("image", f"cache write {path}"):
            tmp_path.write_bytes(response.content)
            tmp_path.replace(path)

        # 若同一 URL 之前指向了别的旧文件名，先清掉脏映射再写新值。
        old_filename = get_cached_filename(url)
        if old_filename and old_filename != filename:
            drop_cached_filename(url)
        put_cached_filename(url, filename)
        log_debug("image", f"network fetched url={url} bytes={len(response.content)} mime={mime} path={path}")
        return ImageFetchResult(url=url, path=path, data=response.content, mime=mime, from_cache=False)

    @staticmethod
    def _guess_mime(path: Path) -> str:
        suffix = path.suffix.lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")


image_fetcher = ImageFetcherService()
