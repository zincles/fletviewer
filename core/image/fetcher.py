from __future__ import annotations

import hashlib
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
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


class ImageFetchCancelled(Exception):
    """图像任务被协作取消。"""


@dataclass(slots=True)
class _ImageLoadEntry:
    url: str
    future: Future[ImageFetchResult]
    cancel_event: threading.Event
    subscribers: set[str]
    task_key: str = ""


class ImageLoadSubscription:
    def __init__(self, coordinator: "ImageLoadCoordinator", entry: _ImageLoadEntry, subscription_id: str):
        self._coordinator = coordinator
        self._entry = entry
        self.subscription_id = subscription_id
        self.cancelled = False

    @property
    def future(self) -> Future[ImageFetchResult]:
        return self._entry.future

    @property
    def url(self) -> str:
        return self._entry.url

    @property
    def task_key(self) -> str:
        return self._entry.task_key

    def progress(self) -> ImageFetchTaskState | None:
        return self._coordinator.progress(self._entry.task_key)

    def cancel(self) -> bool:
        if self.cancelled:
            return False
        self.cancelled = True
        return self._coordinator._unsubscribe(self._entry, self.subscription_id)

    def unsubscribe(self) -> bool:
        return self.cancel()


class ImageLoadCoordinator:
    """将同 URL 控件合并为一个底层任务，并独立管理订阅取消。"""

    def __init__(self, service: "ImageFetcherService"):
        self._service = service
        self._lock = threading.Lock()
        self._entries: dict[str, _ImageLoadEntry] = {}

    def subscribe(self, url: str, *, kind: str = "unknown") -> ImageLoadSubscription:
        normalized = url.strip()
        if not normalized:
            raise ValueError("图像 URL 为空")
        created_entry: _ImageLoadEntry | None = None
        with self._lock:
            entry = self._entries.get(normalized)
            if entry is None or entry.cancel_event.is_set() or entry.future.done():
                cancel_event = threading.Event()
                task_key, future = self._service.submit_fetch(normalized, kind=kind, cancel_event=cancel_event)
                entry = _ImageLoadEntry(normalized, future, cancel_event, set(), task_key)
                self._entries[normalized] = entry
                created_entry = entry
            subscription_id = uuid.uuid4().hex
            entry.subscribers.add(subscription_id)
        if created_entry is not None:
            created_entry.future.add_done_callback(lambda completed, current=created_entry: self._complete(current))
        return ImageLoadSubscription(self, entry, subscription_id)

    def retry(self, url: str, *, kind: str = "unknown") -> ImageLoadSubscription:
        return self.subscribe(url, kind=kind)

    def progress(self, task_key: str) -> ImageFetchTaskState | None:
        return self._service.task_state(task_key)

    def debug_entries(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "url": entry.url,
                    "task_key": entry.task_key,
                    "subscribers": len(entry.subscribers),
                    "cancelling": entry.cancel_event.is_set(),
                    "done": entry.future.done(),
                }
                for entry in self._entries.values()
            ]

    def subscriber_count(self, url: str) -> int:
        with self._lock:
            entry = self._entries.get(url.strip())
            return len(entry.subscribers) if entry is not None else 0

    def _unsubscribe(self, entry: _ImageLoadEntry, subscription_id: str) -> bool:
        with self._lock:
            if self._entries.get(entry.url) is not entry or subscription_id not in entry.subscribers:
                return False
            entry.subscribers.remove(subscription_id)
            if not entry.subscribers and not entry.future.done():
                entry.cancel_event.set()
                self._service.mark_cancelling(entry.task_key)
        return True

    def _complete(self, entry: _ImageLoadEntry) -> None:
        with self._lock:
            if self._entries.get(entry.url) is entry:
                self._entries.pop(entry.url, None)


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
        self._maintenance_call_lock = threading.Lock()
        self._maintenance = threading.Condition()
        self._maintenance_active = False
        self._active_workers = 0
        self._worker_local = threading.local()
        self._cancel_events: dict[str, threading.Event] = {}
        self._url_locks = tuple(threading.RLock() for _ in range(64))
        self._in_flight: dict[str, Future] = {}
        self._state_lock = threading.Lock()
        self._task_states: dict[str, ImageFetchTaskState] = {}
        self._recent_states: list[ImageFetchTaskState] = []
        self._recent_limit = 80

    def snapshot(self) -> ImageFetchSnapshot:
        with self._state_lock:
            active = [replace(s) for s in self._task_states.values() if s.status in {"running", "cancelling"}]
            queued = [replace(s) for s in self._task_states.values() if s.status == "queued"]
            recent = [replace(s) for s in self._recent_states[-self._recent_limit:]]
        active.sort(key=lambda s: s.started_at or s.created_at)
        queued.sort(key=lambda s: s.created_at)
        recent.sort(key=lambda s: s.finished_at or s.created_at, reverse=True)
        return ImageFetchSnapshot(active=active, queued=queued, recent=recent, max_workers=self._max_workers)

    def fetch(self, url: str, *, kind: str = "unknown") -> ImageFetchResult:
        return self.fetch_async(url, kind=kind).result()

    def fetch_async(
        self,
        url: str,
        *,
        kind: str = "unknown",
        cancel_event: threading.Event | None = None,
        deduplicate: bool = True,
    ) -> Future[ImageFetchResult]:
        normalized = url.strip()
        self._debug(f"请求 {normalized}")
        submitted = False
        with self._lock:
            future = self._in_flight.get(normalized) if deduplicate else None
            if future is None:
                self._debug(f"提交图像获取任务 {normalized}")
                task_key = self._new_task(normalized, kind)
                cancel_event = cancel_event or threading.Event()
                self._cancel_events[task_key] = cancel_event
                future = self._executor.submit(self._fetch_impl, normalized, kind, task_key, cancel_event)
                if deduplicate:
                    self._in_flight[normalized] = future
                submitted = True
            else:
                self._debug(f"加入进行中的图像获取任务 {normalized}")
        if submitted and deduplicate:
            future.add_done_callback(lambda completed, key=normalized: self._forget_in_flight(key, completed))
        elif submitted:
            future.add_done_callback(lambda completed, key=normalized: self._observe_completion(key, completed))
        return future

    def submit_fetch(
        self,
        url: str,
        *,
        kind: str = "unknown",
        cancel_event: threading.Event | None = None,
    ) -> tuple[str, Future[ImageFetchResult]]:
        normalized = url.strip()
        task_key = self._new_task(normalized, kind)
        cancel_event = cancel_event or threading.Event()
        try:
            with self._lock:
                self._cancel_events[task_key] = cancel_event
            future = self._executor.submit(self._fetch_impl, normalized, kind, task_key, cancel_event)
        except Exception as ex:
            with self._lock:
                self._cancel_events.pop(task_key, None)
            self._finish_task(task_key, status="failed", error=str(ex))
            raise
        future.add_done_callback(lambda completed, key=normalized: self._observe_completion(key, completed))
        return task_key, future

    def _observe_completion(self, normalized: str, future: Future[ImageFetchResult]) -> None:
        if future.cancelled():
            return
        try:
            future.result()
        except ImageFetchCancelled:
            return
        except Exception as ex:
            self._log_exception("图像", f"后台图像获取失败 URL={normalized}：{ex}")

    def _forget_in_flight(self, normalized: str, future: Future[ImageFetchResult]) -> None:
        with self._lock:
            if self._in_flight.get(normalized) is future:
                self._in_flight.pop(normalized, None)
        if future.cancelled():
            return
        try:
            future.result()
        except ImageFetchCancelled:
            return
        except Exception as ex:
            self._log_exception("图像", f"后台图像获取失败 URL={normalized}：{ex}")

    def run_cache_maintenance(self, callback: Callable[[], None]) -> None:
        """停止缓存 worker，在独占窗口内执行缓存维护。"""
        with self._maintenance_call_lock:
            with self._maintenance:
                self._maintenance_active = True
                with self._lock:
                    cancel_events = list(self._cancel_events.values())
                for event in cancel_events:
                    event.set()
                while self._active_workers:
                    self._maintenance.wait()
            try:
                callback()
            finally:
                with self._maintenance:
                    self._maintenance_active = False
                    self._maintenance.notify_all()

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def fetch_gallery_page(
        self,
        *,
        provider: str,
        gid: str,
        token: str,
        page_idx: int,
        resolve_url: Callable[[], str],
        kind: str = "original",
        cancel_event: threading.Event | None = None,
    ) -> ImageFetchResult:
        with self._cache_worker():
            self._raise_if_cancelled(cancel_event)
            cached_path = self._cache.get_gallery_page_cached_path(provider, gid, token, page_idx)
            if cached_path is not None:
                with self._timer("读取缓存", str(cached_path)):
                    data = cached_path.read_bytes()
                self._raise_if_cancelled(cancel_event)
                mime = self._guess_mime(cached_path)
                self._debug(f"画廊页面缓存命中 provider={provider} gid={gid} 索引={page_idx} 字节数={len(data)}")
                return ImageFetchResult(url="", path=cached_path, data=data, mime=mime, from_cache=True)

            cached_filename = self._cache.get_gallery_page_cached_filename(provider, gid, token, page_idx)
            if cached_filename:
                self._debug(f"已修复画廊失效索引 provider={provider} gid={gid} 索引={page_idx} 文件名={cached_filename}")
                self._cache.repair_gallery_page_entry(provider, gid, token, page_idx)

        url = resolve_url()
        self._raise_if_cancelled(cancel_event)
        result = self.fetch_async(url, kind=kind, cancel_event=cancel_event, deduplicate=False).result()
        self._raise_if_cancelled(cancel_event)
        with self._cache_worker():
            self._raise_if_cancelled(cancel_event)
            if result.path.exists():
                self._cache.put_gallery_page_cached_filename(provider, gid, token, page_idx, result.path.name, kind=kind)
        return result

    def _fetch_impl(self, url: str, kind: str, task_key: str | None = None, cancel_event: threading.Event | None = None) -> ImageFetchResult:
        try:
            with self._cache_worker():
                with self._url_lock(url):
                    try:
                        return self._fetch_impl_locked(url, kind, task_key, cancel_event)
                    except ImageFetchCancelled:
                        if task_key:
                            self._finish_task(task_key, status="cancelled")
                        raise
                    except Exception as ex:
                        if task_key:
                            self._finish_task(task_key, status="failed", error=str(ex))
                        raise
        finally:
            if task_key:
                with self._lock:
                    self._cancel_events.pop(task_key, None)

    @contextmanager
    def _cache_worker(self):
        depth = getattr(self._worker_local, "depth", 0)
        if depth:
            self._worker_local.depth = depth + 1
            try:
                yield
            finally:
                self._worker_local.depth -= 1
            return
        with self._maintenance:
            while self._maintenance_active:
                self._maintenance.wait()
            self._active_workers += 1
        self._worker_local.depth = 1
        try:
            yield
        finally:
            self._worker_local.depth = 0
            with self._maintenance:
                self._active_workers -= 1
                if not self._active_workers:
                    self._maintenance.notify_all()

    def _fetch_impl_locked(self, url: str, kind: str, task_key: str | None = None, cancel_event: threading.Event | None = None) -> ImageFetchResult:
        self._raise_if_cancelled(cancel_event)
        if task_key:
            self._update_task(task_key, status="running", started_at=time.time())
        cached_path = self._cache.get_cached_path(url)
        if cached_path is not None:
            with self._timer("读取缓存", str(cached_path)):
                data = cached_path.read_bytes()
            mime = self._guess_mime(cached_path)
            self._debug(f"缓存命中 URL={url} 字节数={len(data)} MIME={mime}")
            result = ImageFetchResult(url=url, path=cached_path, data=data, mime=mime, from_cache=True)
            if task_key:
                self._finish_task(task_key, status="cache_hit", bytes_done=len(data), bytes_total=len(data), from_cache=True)
            return result

        cached_filename = self._cache.get_cached_filename(url)
        if cached_filename:
            stale_path = self._cache.path_for_filename(cached_filename)
            if stale_path.exists():
                with self._timer("读取缓存", str(stale_path)):
                    data = stale_path.read_bytes()
                self._raise_if_cancelled(cancel_event)
                mime = self._guess_mime(stale_path)
                self._debug(f"失效索引对应的缓存文件命中 URL={url} 字节数={len(data)} MIME={mime}")
                result = ImageFetchResult(url=url, path=stale_path, data=data, mime=mime, from_cache=True)
                if task_key:
                    self._finish_task(task_key, status="cache_hit", bytes_done=len(data), bytes_total=len(data), from_cache=True)
                return result
            self._debug(f"已修复失效索引 URL={url} 文件名={cached_filename}")
            self._cache.repair_stale_entry(url)

        sprite_crop = self._parse_sprite_crop(url)
        if sprite_crop is not None:
            result = self._fetch_sprite_crop(url, *sprite_crop, cancel_event=cancel_event)
            if task_key:
                self._finish_task(task_key, status="completed", bytes_done=len(result.data), bytes_total=len(result.data), from_cache=result.from_cache)
            return result

        self._debug(f"缓存未命中 URL={url}")
        try:
            response = self._get_image_response(url, cancel_event)
            try:
                self._raise_if_cancelled(cancel_event)
                response.raise_for_status()
                mime = response.headers.get("Content-Type", "image/jpeg").split(";", 1)[0].strip()
                filename = self._cache.filename_for_url(url, mime=mime)
                path = self._cache.cached_path_for_url(url, mime=mime)
                path.parent.mkdir(parents=True, exist_ok=True)
                data = self._write_response_to_cache(response, path, task_key, cancel_event)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

            old_filename = self._cache.get_cached_filename(url)
            if old_filename and old_filename != filename:
                self._cache.drop_cached_filename(url)
            self._cache.put_cached_filename(url, filename, kind=kind)
            self._debug(f"网络获取完成 URL={url} 字节数={len(data)} MIME={mime} 路径={path}")
            if task_key:
                self._finish_task(task_key, status="completed", bytes_done=len(data), from_cache=False)
            return ImageFetchResult(url=url, path=path, data=data, mime=mime, from_cache=False)
        except ImageFetchCancelled:
            if task_key:
                self._finish_task(task_key, status="cancelled")
            raise
        except Exception as ex:
            if task_key:
                self._finish_task(task_key, status="failed", error=str(ex))
            raise

    def _get_image_response(self, url: str, cancel_event: threading.Event | None = None) -> requests.Response:
        headers = {"Referer": "https://e-hentai.org/", "Connection": "close"}
        last_error: Exception | None = None
        for attempt in range(1, 4):
            self._raise_if_cancelled(cancel_event)
            try:
                if attempt > 1:
                    self._debug(f"重试图像获取 尝试次数={attempt} URL={url}")
                return self._get_response(url, headers, 20)
            except requests.RequestException as ex:
                last_error = ex
                self._debug(f"图像获取暂时失败 尝试次数={attempt} URL={url}：{ex}")
                if attempt < 3:
                    delay = 0.5 * attempt
                    if cancel_event is not None and cancel_event.wait(delay):
                        raise ImageFetchCancelled("图像加载已取消")
                    time.sleep(delay if cancel_event is None else 0)
        assert last_error is not None
        raise last_error

    def _fetch_sprite_crop(self, url: str, base_url: str, left: int, top: int, right: int, bottom: int, *, cancel_event: threading.Event | None = None) -> ImageFetchResult:
        self._debug(f"裁剪 sprite URL={url} 基础URL={base_url} 区域={left},{top},{right},{bottom}")
        base_result = self._fetch_impl(base_url, "sprite", cancel_event=cancel_event)
        self._raise_if_cancelled(cancel_event)
        with self._timer("裁剪 sprite", base_url):
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
        tmp_path = self._temporary_path(path)
        with self._timer("写入缓存", str(path)):
            try:
                self._raise_if_cancelled(cancel_event)
                tmp_path.write_bytes(data)
                self._raise_if_cancelled(cancel_event)
                try:
                    tmp_path.replace(path)
                except PermissionError:
                    if not path.exists():
                        raise
                    data = path.read_bytes()
            finally:
                tmp_path.unlink(missing_ok=True)

        old_filename = self._cache.get_cached_filename(url)
        if old_filename and old_filename != filename:
            self._cache.drop_cached_filename(url)
        self._cache.put_cached_filename(url, filename, kind="sprite_crop")
        self._debug(f"sprite 裁剪完成 URL={url} 字节数={len(data)} MIME={mime} 路径={path}")
        return ImageFetchResult(url=url, path=path, data=data, mime=mime, from_cache=False)

    def _write_response_to_cache(self, response: requests.Response, path: Path, task_key: str | None, cancel_event: threading.Event | None = None) -> bytes:
        try:
            total = max(0, int(response.headers.get("Content-Length") or 0))
        except (TypeError, ValueError):
            total = 0
        if task_key:
            self._update_task(task_key, bytes_total=total)
        tmp_path = self._temporary_path(path)
        bytes_done = 0
        chunks: list[bytes] = []
        use_existing = False
        last_progress_bytes = 0
        last_progress_at = time.monotonic()
        with self._timer("写入缓存", str(path)):
            try:
                with open(tmp_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8 * 1024):
                        self._raise_if_cancelled(cancel_event)
                        if not chunk:
                            continue
                        f.write(chunk)
                        chunks.append(chunk)
                        bytes_done += len(chunk)
                        now = time.monotonic()
                        if task_key and (bytes_done - last_progress_bytes >= 64 * 1024 or now - last_progress_at >= 0.2):
                            self._update_task(task_key, bytes_done=bytes_done)
                            last_progress_bytes = bytes_done
                            last_progress_at = now
                self._raise_if_cancelled(cancel_event)
                try:
                    tmp_path.replace(path)
                except PermissionError:
                    if not path.exists():
                        raise
                    use_existing = True
            finally:
                tmp_path.unlink(missing_ok=True)
        data = path.read_bytes() if use_existing else b"".join(chunks)
        if task_key:
            self._update_task(task_key, bytes_done=len(data), bytes_total=len(data) if use_existing else total or len(data))
        return data

    @staticmethod
    def _temporary_path(path: Path) -> Path:
        return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")

    def _url_lock(self, url: str) -> threading.RLock:
        digest = hashlib.sha256(url.encode("utf-8")).digest()
        return self._url_locks[int.from_bytes(digest[:2], "big") % len(self._url_locks)]

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise ImageFetchCancelled("图像加载已取消")

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
        self._log_debug("图像", message)

    def _timer(self, name: str, detail: str):
        return self._timer_factory("图像", f"{name} {detail}")

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

    def task_state_for_url(self, url: str) -> ImageFetchTaskState | None:
        with self._state_lock:
            for state in self._task_states.values():
                if state.url == url:
                    return replace(state)
        return None

    def task_state(self, key: str) -> ImageFetchTaskState | None:
        with self._state_lock:
            state = self._task_states.get(key)
            return replace(state) if state is not None else None

    def mark_cancelling(self, key: str) -> None:
        self._update_task(key, status="cancelling")


class _NullTimer:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False
