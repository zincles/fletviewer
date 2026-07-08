from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
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


@dataclass(slots=True)
class ImageFetchTaskState:
    key: str
    url: str
    kind: str
    status: str
    bytes_done: int = 0
    bytes_total: int = 0
    from_cache: bool = False
    error: str = ""
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass(slots=True)
class ImageFetchSnapshot:
    active: list[ImageFetchTaskState]
    queued: list[ImageFetchTaskState]
    recent: list[ImageFetchTaskState]
    max_workers: int


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
        self._max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="image-fetch")
        self._lock = threading.Lock()
        self._in_flight: dict[str, Future] = {}
        self._state_lock = threading.Lock()
        self._task_states: dict[str, ImageFetchTaskState] = {}
        self._recent_states: list[ImageFetchTaskState] = []
        self._recent_limit = 80

    def snapshot(self) -> ImageFetchSnapshot:
        with self._state_lock:
            active = [replace(s) for s in self._task_states.values() if s.status == "running"]
            queued = [replace(s) for s in self._task_states.values() if s.status == "queued"]
            recent = [replace(s) for s in self._recent_states[-self._recent_limit:]]
        active.sort(key=lambda s: s.started_at or s.created_at)
        queued.sort(key=lambda s: s.created_at)
        recent.sort(key=lambda s: s.finished_at or s.created_at, reverse=True)
        return ImageFetchSnapshot(active=active, queued=queued, recent=recent, max_workers=self._max_workers)

    def fetch(self, url: str, *, kind: str = "unknown") -> ImageFetchResult:
        normalized = url.strip()
        self._debug(f"request {normalized}")
        with self._lock:
            future = self._in_flight.get(normalized)
            if future is None:
                self._debug(f"submit fetch {normalized}")
                task_key = self._new_task(normalized, kind)
                future = self._executor.submit(self._fetch_impl, normalized, kind, task_key)
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

    def _fetch_impl(self, url: str, kind: str, task_key: str | None = None) -> ImageFetchResult:
        if task_key:
            self._update_task(task_key, status="running", started_at=time.time())
        cached_path = self._cache.get_cached_path(url)
        if cached_path is not None:
            with self._timer("cache read", str(cached_path)):
                data = cached_path.read_bytes()
            mime = self._guess_mime(cached_path)
            self._debug(f"cache hit url={url} bytes={len(data)} mime={mime}")
            result = ImageFetchResult(url=url, path=cached_path, data=data, mime=mime, from_cache=True)
            if task_key:
                self._finish_task(task_key, status="cache_hit", bytes_done=len(data), bytes_total=len(data), from_cache=True)
            return result

        cached_filename = self._cache.get_cached_filename(url)
        if cached_filename:
            stale_path = self._cache.path_for_filename(cached_filename)
            if stale_path.exists():
                with self._timer("cache read", str(stale_path)):
                    data = stale_path.read_bytes()
                mime = self._guess_mime(stale_path)
                self._debug(f"cache hit stale-index url={url} bytes={len(data)} mime={mime}")
                result = ImageFetchResult(url=url, path=stale_path, data=data, mime=mime, from_cache=True)
                if task_key:
                    self._finish_task(task_key, status="cache_hit", bytes_done=len(data), bytes_total=len(data), from_cache=True)
                return result
            self._debug(f"stale index repaired url={url} filename={cached_filename}")
            self._cache.repair_stale_entry(url)

        sprite_crop = self._parse_sprite_crop(url)
        if sprite_crop is not None:
            result = self._fetch_sprite_crop(url, *sprite_crop)
            if task_key:
                self._finish_task(task_key, status="completed", bytes_done=len(result.data), bytes_total=len(result.data), from_cache=result.from_cache)
            return result

        self._debug(f"cache miss url={url}")
        try:
            response = self._get_image_response(url)
            response.raise_for_status()
            mime = response.headers.get("Content-Type", "image/jpeg").split(";", 1)[0].strip()
            filename = self._cache.filename_for_url(url, mime=mime)
            path = self._cache.cached_path_for_url(url, mime=mime)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = self._write_response_to_cache(response, path, task_key)

            old_filename = self._cache.get_cached_filename(url)
            if old_filename and old_filename != filename:
                self._cache.drop_cached_filename(url)
            self._cache.put_cached_filename(url, filename, kind=kind)
            self._debug(f"network fetched url={url} bytes={len(data)} mime={mime} path={path}")
            if task_key:
                self._finish_task(task_key, status="completed", bytes_done=len(data), from_cache=False)
            return ImageFetchResult(url=url, path=path, data=data, mime=mime, from_cache=False)
        except Exception as ex:
            if task_key:
                self._finish_task(task_key, status="failed", error=str(ex))
            raise

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

    def _write_response_to_cache(self, response: requests.Response, path: Path, task_key: str | None) -> bytes:
        total = int(response.headers.get("Content-Length") or 0)
        if task_key:
            self._update_task(task_key, bytes_total=total)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        bytes_done = 0
        with self._timer("cache write", str(path)):
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    bytes_done += len(chunk)
                    if task_key:
                        self._update_task(task_key, bytes_done=bytes_done)
            tmp_path.replace(path)
        data = path.read_bytes()
        if task_key:
            self._update_task(task_key, bytes_done=len(data), bytes_total=total or len(data))
        return data

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

    def _new_task(self, url: str, kind: str) -> str:
        key = uuid.uuid4().hex[:12]
        with self._state_lock:
            self._task_states[key] = ImageFetchTaskState(key=key, url=url, kind=kind, status="queued", created_at=time.time())
        return key

    def _update_task(self, key: str, **changes) -> None:
        with self._state_lock:
            state = self._task_states.get(key)
            if not state:
                return
            for name, value in changes.items():
                setattr(state, name, value)

    def _finish_task(self, key: str, *, status: str, bytes_done: int | None = None, bytes_total: int | None = None, from_cache: bool = False, error: str = "") -> None:
        with self._state_lock:
            state = self._task_states.pop(key, None)
            if not state:
                return
            state.status = status
            state.finished_at = time.time()
            state.from_cache = from_cache
            state.error = error
            if bytes_done is not None:
                state.bytes_done = bytes_done
            if bytes_total is not None:
                state.bytes_total = bytes_total
            elif state.bytes_total <= 0 and state.bytes_done > 0:
                state.bytes_total = state.bytes_done
            self._recent_states.append(replace(state))
            if len(self._recent_states) > self._recent_limit:
                self._recent_states = self._recent_states[-self._recent_limit:]


class _NullTimer:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False
