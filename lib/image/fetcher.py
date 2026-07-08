from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import parse_qs

import requests
from PIL import Image


class ImageCacheBackend(Protocol):
    def ensure_image_cache_dirs(self) -> None: ...
    def get_cached_filename(self, url: str) -> str | None: ...
    def get_cached_path(self, url: str) -> Path | None: ...
    def path_for_filename(self, filename: str) -> Path: ...
    def repair_stale_entry(self, url: str) -> bool: ...
    def filename_for_url(self, url: str, mime: str | None = None) -> str: ...
    def cached_path_for_url(self, url: str, mime: str | None = None) -> Path: ...
    def drop_cached_filename(self, url: str) -> str | None: ...
    def put_cached_filename(self, url: str, filename: str, *, kind: str = "unknown") -> None: ...
    def get_gallery_page_cached_filename(self, provider: str, gid: str, token: str, page_idx: int) -> str | None: ...
    def get_gallery_page_cached_path(self, provider: str, gid: str, token: str, page_idx: int) -> Path | None: ...
    def repair_gallery_page_entry(self, provider: str, gid: str, token: str, page_idx: int) -> bool: ...
    def put_gallery_page_cached_filename(self, provider: str, gid: str, token: str, page_idx: int, filename: str, *, kind: str = "original") -> None: ...


@dataclass(slots=True)
class ImageFetchResult:
    url: str
    path: Path
    data: bytes
    mime: str
    from_cache: bool


class ImageFetcherService:
    def __init__(
        self,
        *,
        cache: ImageCacheBackend,
        get_response: Callable[[str, dict[str, str], int], requests.Response],
        log_debug: Callable[[str, str], None] | None = None,
        log_exception: Callable[[str, str], None] | None = None,
        timer_factory: Callable[[str, str], object] | None = None,
        max_workers: int = 6,
    ):
        cache.ensure_image_cache_dirs()
        self._cache = cache
        self._get_response = get_response
        self._log_debug = log_debug or (lambda _scope, _message: None)
        self._log_exception = log_exception or (lambda _scope, _message: None)
        self._timer_factory = timer_factory or _NullTimer
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="image-fetch")
        self._lock = threading.Lock()
        self._in_flight: dict[str, Future] = {}

    def fetch(self, url: str, *, kind: str = "unknown") -> ImageFetchResult:
        normalized = url.strip()
        self._debug(f"request {normalized}")
        with self._lock:
            future = self._in_flight.get(normalized)
            if future is None:
                self._debug(f"submit fetch {normalized}")
                future = self._executor.submit(self._fetch_impl, normalized, kind)
                self._in_flight[normalized] = future
            else:
                self._debug(f"join in-flight {normalized}")
        try:
            return future.result()
        finally:
            with self._lock:
                if self._in_flight.get(normalized) is future:
                    self._in_flight.pop(normalized, None)

    def fetch_gallery_page(
        self,
        *,
        provider: str,
        gid: str,
        token: str,
        page_idx: int,
        resolve_url: Callable[[], str],
        kind: str = "original",
    ) -> ImageFetchResult:
        cached_path = self._cache.get_gallery_page_cached_path(provider, gid, token, page_idx)
        if cached_path is not None:
            with self._timer("cache read", str(cached_path)):
                data = cached_path.read_bytes()
            mime = self._guess_mime(cached_path)
            self._debug(f"gallery page cache hit provider={provider} gid={gid} index={page_idx} bytes={len(data)}")
            return ImageFetchResult(url="", path=cached_path, data=data, mime=mime, from_cache=True)

        cached_filename = self._cache.get_gallery_page_cached_filename(provider, gid, token, page_idx)
        if cached_filename:
            self._debug(f"gallery stale index repaired provider={provider} gid={gid} index={page_idx} filename={cached_filename}")
            self._cache.repair_gallery_page_entry(provider, gid, token, page_idx)

        url = resolve_url()
        result = self.fetch(url, kind=kind)
        self._cache.put_gallery_page_cached_filename(provider, gid, token, page_idx, result.path.name, kind=kind)
        return result

    def _fetch_impl(self, url: str, kind: str) -> ImageFetchResult:
        cached_path = self._cache.get_cached_path(url)
        if cached_path is not None:
            with self._timer("cache read", str(cached_path)):
                data = cached_path.read_bytes()
            mime = self._guess_mime(cached_path)
            self._debug(f"cache hit url={url} bytes={len(data)} mime={mime}")
            return ImageFetchResult(url=url, path=cached_path, data=data, mime=mime, from_cache=True)

        cached_filename = self._cache.get_cached_filename(url)
        if cached_filename:
            stale_path = self._cache.path_for_filename(cached_filename)
            if stale_path.exists():
                with self._timer("cache read", str(stale_path)):
                    data = stale_path.read_bytes()
                mime = self._guess_mime(stale_path)
                self._debug(f"cache hit stale-index url={url} bytes={len(data)} mime={mime}")
                return ImageFetchResult(url=url, path=stale_path, data=data, mime=mime, from_cache=True)
            self._debug(f"stale index repaired url={url} filename={cached_filename}")
            self._cache.repair_stale_entry(url)

        sprite_crop = self._parse_sprite_crop(url)
        if sprite_crop is not None:
            return self._fetch_sprite_crop(url, *sprite_crop)

        self._debug(f"cache miss url={url}")
        response = self._get_image_response(url)
        response.raise_for_status()
        mime = response.headers.get("Content-Type", "image/jpeg").split(";", 1)[0].strip()
        filename = self._cache.filename_for_url(url, mime=mime)
        path = self._cache.cached_path_for_url(url, mime=mime)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with self._timer("cache write", str(path)):
            tmp_path.write_bytes(response.content)
            tmp_path.replace(path)

        old_filename = self._cache.get_cached_filename(url)
        if old_filename and old_filename != filename:
            self._cache.drop_cached_filename(url)
        self._cache.put_cached_filename(url, filename, kind=kind)
        self._debug(f"network fetched url={url} bytes={len(response.content)} mime={mime} path={path}")
        return ImageFetchResult(url=url, path=path, data=response.content, mime=mime, from_cache=False)

    def _get_image_response(self, url: str) -> requests.Response:
        headers = {"Referer": "https://e-hentai.org/", "Connection": "close"}
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                if attempt > 1:
                    self._debug(f"retry image fetch attempt={attempt} url={url}")
                return self._get_response(url, headers, 20)
            except requests.RequestException as ex:
                last_error = ex
                self._debug(f"transient image fetch failed attempt={attempt} url={url}: {ex}")
                if attempt < 3:
                    time.sleep(0.5 * attempt)
        assert last_error is not None
        raise last_error

    def _fetch_sprite_crop(self, url: str, base_url: str, left: int, top: int, right: int, bottom: int) -> ImageFetchResult:
        self._debug(f"sprite crop url={url} base={base_url} box={left},{top},{right},{bottom}")
        base_result = self._fetch_impl(base_url, "sprite")
        with self._timer("sprite crop", base_url):
            with Image.open(BytesIO(base_result.data)) as image:
                cropped = image.crop((left, top, right, bottom))
                output = BytesIO()
                fmt = image.format or "WEBP"
                cropped.save(output, format=fmt)
                data = output.getvalue()

        mime = base_result.mime if base_result.mime.startswith("image/") else "image/webp"
        filename = self._cache.filename_for_url(url, mime=mime)
        path = self._cache.cached_path_for_url(url, mime=mime)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with self._timer("cache write", str(path)):
            tmp_path.write_bytes(data)
            tmp_path.replace(path)

        old_filename = self._cache.get_cached_filename(url)
        if old_filename and old_filename != filename:
            self._cache.drop_cached_filename(url)
        self._cache.put_cached_filename(url, filename, kind="sprite_crop")
        self._debug(f"sprite cropped url={url} bytes={len(data)} mime={mime} path={path}")
        return ImageFetchResult(url=url, path=path, data=data, mime=mime, from_cache=False)

    @staticmethod
    def _parse_sprite_crop(url: str) -> tuple[str, int, int, int, int] | None:
        if "@" not in url:
            return None
        base_url, crop_spec = url.rsplit("@", 1)
        if not base_url or not crop_spec:
            return None
        params = parse_qs(crop_spec, keep_blank_values=False)
        x_values = params.get("x")
        y_values = params.get("y")
        if not x_values or not y_values:
            return None

        def parse_range(value: str) -> tuple[int, int] | None:
            parts = value.split("-", 1)
            if len(parts) != 2:
                return None
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                return None
            if start < 0 or end <= start:
                return None
            return start, end

        x_range = parse_range(x_values[0])
        y_range = parse_range(y_values[0])
        if x_range is None or y_range is None:
            return None
        return base_url, x_range[0], y_range[0], x_range[1], y_range[1]

    @staticmethod
    def _guess_mime(path: Path) -> str:
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }.get(path.suffix.lower(), "application/octet-stream")

    def _debug(self, message: str) -> None:
        self._log_debug("image", message)

    def _timer(self, name: str, detail: str):
        return self._timer_factory("image", f"{name} {detail}")


class _NullTimer:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False
