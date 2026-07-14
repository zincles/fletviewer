from __future__ import annotations

import dataclasses
from typing import Protocol

from core.api.dto import JSONValue, json_safe
from core.api.errors import BackendError


class DownloadTaskManager(Protocol):
    def list_tasks(self) -> list[object]:
        ...

    def get_task(self, task_id: str) -> object | None:
        ...

    def cancel_task(self, task_id: str) -> None:
        ...

    def retry_task(self, task_id: str) -> None:
        ...

    def delete_task(self, task_id: str) -> None:
        ...


@dataclasses.dataclass(slots=True)
class DownloadTaskDTO:
    id: str
    provider: str
    kind: str
    status: str
    title: str
    filename: str = ""
    bytes_total: int = 0
    bytes_done: int = 0
    progress: float | None = None
    error: str = ""
    consume_error: str = ""
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    updated_at: str = ""
    resume_supported: bool = False
    media: dict[str, JSONValue] = dataclasses.field(default_factory=dict)
    expiry: dict[str, JSONValue] = dataclasses.field(default_factory=dict)
    metadata: dict[str, JSONValue] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(dataclasses.asdict(self))


class DownloadTaskService:
    """Frontend-safe task views and commands over a Python download manager."""

    def __init__(self, manager: DownloadTaskManager):
        self._manager = manager

    def list_tasks(self, *, provider: str = "", kind: str = "") -> list[DownloadTaskDTO]:
        tasks = [self._to_dto(task) for task in self._manager.list_tasks()]
        if provider:
            tasks = [task for task in tasks if task.provider == provider]
        if kind:
            tasks = [task for task in tasks if task.kind == kind]
        return tasks

    def get_task(self, task_id: str) -> DownloadTaskDTO:
        return self._to_dto(self._require_task(task_id))

    def cancel_task(self, task_id: str) -> DownloadTaskDTO:
        self._require_task(task_id)
        self._manager.cancel_task(task_id)
        return self.get_task(task_id)

    def retry_task(self, task_id: str) -> DownloadTaskDTO:
        self._require_task(task_id)
        self._manager.retry_task(task_id)
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> None:
        self._require_task(task_id)
        self._manager.delete_task(task_id)

    def _require_task(self, task_id: str) -> object:
        task = self._manager.get_task(str(task_id))
        if task is None:
            raise BackendError("task_not_found", f"下载任务不存在: {task_id}")
        return task

    @staticmethod
    def _to_dto(task: object) -> DownloadTaskDTO:
        tag_data = dict(getattr(task, "tag_data", {}) or {})
        gallery = dict(tag_data.get("gallery_details") or {})
        tags = list(getattr(task, "tags", []) or [])
        kind = "eh_archive" if "eh_archive" in tags else str(getattr(task, "kind", "download") or "download")
        provider = str(tag_data.get("provider") or ("ehentai" if kind == "eh_archive" else ""))
        bytes_total = max(0, int(getattr(task, "bytes_total", 0) or 0))
        bytes_done = max(0, int(getattr(task, "bytes_done", 0) or 0))
        progress = min(1.0, bytes_done / bytes_total) if bytes_total else None
        media = {
            "gallery_url": str(tag_data.get("gallery_url") or ""),
            "gallery_id": str(tag_data.get("gid") or ""),
            "gallery_token": str(tag_data.get("token") or ""),
            "gallery_title": str(gallery.get("title") or ""),
            "archive_id": str(tag_data.get("archive_id") or ""),
            "archive_title": str(tag_data.get("archive_title") or ""),
            "archive_description": str(tag_data.get("archive_description") or ""),
        }
        expiry = {
            "acquired_at": str(tag_data.get("download_url_acquired_at") or ""),
            "valid_seconds": int(tag_data.get("download_url_valid_seconds") or 0),
            "max_ip_count": int(tag_data.get("max_ip_count") or 0),
        }
        title = media["gallery_title"] or media["archive_title"] or str(getattr(task, "filename", "") or "")
        resume = getattr(task, "resume", None)
        return DownloadTaskDTO(
            id=str(getattr(task, "id", "")),
            provider=provider,
            kind=kind,
            status=str(getattr(task, "status", "")),
            title=str(title),
            filename=str(getattr(task, "filename", "") or ""),
            bytes_total=bytes_total,
            bytes_done=bytes_done,
            progress=progress,
            error=str(getattr(task, "error", "") or ""),
            consume_error=str(getattr(task, "consume_error", "") or ""),
            created_at=str(getattr(task, "created_at", "") or ""),
            started_at=str(getattr(task, "started_at", "") or ""),
            completed_at=str(getattr(task, "completed_at", "") or ""),
            updated_at=str(getattr(task, "updated_at", "") or ""),
            resume_supported=bool(getattr(resume, "supported", False)),
            media=json_safe(media),
            expiry=json_safe(expiry),
            metadata={"tags": json_safe(tags)},
        )
