from __future__ import annotations

import base64
import dataclasses
import threading
import time
import uuid
from typing import Callable, Protocol

from core.api.dto import JSONValue, json_safe
from core.api.errors import BackendError
from core.image.fetcher import ImageFetchCancelled, ImageLoadCoordinator, ImageLoadSubscription


class ImageFetcherPort(Protocol):
    def submit_fetch(self, url: str, *, kind: str = "unknown", cancel_event=None):
        ...

    def task_state(self, key: str):
        ...

    def mark_cancelling(self, key: str) -> None:
        ...


@dataclasses.dataclass(slots=True)
class ImageTaskDTO:
    id: str
    status: str
    kind: str
    url: str
    bytes_done: int = 0
    bytes_total: int = 0
    progress: float | None = None
    from_cache: bool = False
    mime: str = ""
    result_size: int = 0
    error: str = ""
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(dataclasses.asdict(self))


@dataclasses.dataclass(slots=True)
class ImageResultDTO:
    task_id: str
    mime: str
    data_base64: str
    byte_length: int
    from_cache: bool = False

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(dataclasses.asdict(self))


@dataclasses.dataclass(slots=True)
class _ImageTaskEntry:
    id: str
    url: str
    kind: str
    subscription: ImageLoadSubscription
    created_at: float
    cancelled: bool = False


class ImageTaskService:
    """Polling API for image work without exposing Future or subscription objects."""

    def __init__(
        self,
        fetcher: ImageFetcherPort,
        *,
        images_enabled: Callable[[], bool] | None = None,
    ):
        self._fetcher = fetcher
        self._coordinator = ImageLoadCoordinator(fetcher)
        self._images_enabled = images_enabled or (lambda: True)
        self._tasks: dict[str, _ImageTaskEntry] = {}
        self._lock = threading.RLock()

    def start(self, url: str, *, kind: str = "unknown") -> ImageTaskDTO:
        normalized = str(url or "").strip()
        if not normalized:
            raise BackendError("invalid_image_url", "图像 URL 为空")
        if not self._images_enabled():
            raise BackendError("images_disabled", "图像加载已关闭")
        subscription = self._coordinator.subscribe(normalized, kind=kind)
        task_id = uuid.uuid4().hex
        entry = _ImageTaskEntry(task_id, normalized, str(kind or "unknown"), subscription, time.time())
        with self._lock:
            self._tasks[task_id] = entry
        return self._to_dto(entry)

    def status(self, task_id: str) -> ImageTaskDTO:
        return self._to_dto(self._require(task_id))

    def list_tasks(self) -> list[ImageTaskDTO]:
        with self._lock:
            entries = list(self._tasks.values())
        return [self._to_dto(entry) for entry in entries]

    def cancel(self, task_id: str) -> ImageTaskDTO:
        entry = self._require(task_id)
        entry.subscription.cancel()
        entry.cancelled = True
        return self._to_dto(entry)

    def retry(self, task_id: str) -> ImageTaskDTO:
        entry = self._require(task_id)
        entry.subscription.cancel()
        entry.subscription = self._coordinator.retry(entry.url, kind=entry.kind)
        entry.created_at = time.time()
        entry.cancelled = False
        return self._to_dto(entry)

    def result(self, task_id: str) -> ImageResultDTO:
        entry = self._require(task_id)
        if entry.cancelled:
            raise BackendError("image_cancelled", f"图像任务已取消: {task_id}")
        if not entry.subscription.future.done():
            raise BackendError("image_not_ready", f"图像任务尚未完成: {task_id}", retryable=True)
        try:
            result = entry.subscription.future.result()
        except ImageFetchCancelled as ex:
            raise BackendError("image_cancelled", f"图像任务已取消: {task_id}") from ex
        except Exception as ex:
            raise BackendError("image_failed", str(ex) or "图像加载失败", retryable=True) from ex
        return ImageResultDTO(
            task_id=entry.id,
            mime=str(result.mime or "application/octet-stream"),
            data_base64=base64.b64encode(result.data).decode("ascii"),
            byte_length=len(result.data),
            from_cache=bool(result.from_cache),
        )

    def remove(self, task_id: str) -> None:
        entry = self._require(task_id)
        entry.subscription.cancel()
        with self._lock:
            self._tasks.pop(task_id, None)

    def _require(self, task_id: str) -> _ImageTaskEntry:
        with self._lock:
            entry = self._tasks.get(str(task_id))
        if entry is None:
            raise BackendError("image_task_not_found", f"图像任务不存在: {task_id}")
        return entry

    def _to_dto(self, entry: _ImageTaskEntry) -> ImageTaskDTO:
        future = entry.subscription.future
        state = entry.subscription.progress()
        status = str(getattr(state, "status", "queued") or "queued")
        error = str(getattr(state, "error", "") or "")
        mime = ""
        result_size = 0
        from_cache = bool(getattr(state, "from_cache", False))
        finished_at = float(getattr(state, "finished_at", 0.0) or 0.0)
        if entry.cancelled:
            status = "cancelled"
            finished_at = time.time()
        elif future.done():
            try:
                result = future.result()
            except ImageFetchCancelled:
                status = "cancelled"
            except Exception as ex:
                status = "failed"
                error = str(ex) or ex.__class__.__name__
            else:
                status = "completed"
                mime = str(result.mime or "")
                result_size = len(result.data)
                from_cache = bool(result.from_cache)
            finished_at = finished_at or time.time()
        bytes_done = max(0, int(getattr(state, "bytes_done", 0) or 0))
        bytes_total = max(0, int(getattr(state, "bytes_total", 0) or 0))
        if status == "completed" and not bytes_done:
            bytes_done = result_size
            bytes_total = bytes_total or result_size
        progress = min(1.0, bytes_done / bytes_total) if bytes_total else None
        return ImageTaskDTO(
            id=entry.id,
            status=status,
            kind=entry.kind,
            url=entry.url,
            bytes_done=bytes_done,
            bytes_total=bytes_total,
            progress=progress,
            from_cache=from_cache,
            mime=mime,
            result_size=result_size,
            error=error,
            created_at=entry.created_at,
            started_at=float(getattr(state, "started_at", 0.0) or 0.0),
            finished_at=finished_at,
        )
