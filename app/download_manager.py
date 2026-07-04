from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.storage import (
    DOWNLOADING_DIR,
    DOWNLOAD_TASKS_INDEX_PATH,
    ensure_download_dirs,
)


TASK_STATUSES = {"queued", "running", "completed", "failed", "cancelled", "consumed"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _rel_path(path: Path) -> str:
    return path.as_posix()


def _parse_filename_from_response(response, fallback: str) -> str:
    cd = response.headers.get("Content-Disposition", "")
    marker = "filename="
    if marker in cd:
        value = cd.split(marker, 1)[1].split(";", 1)[0].strip().strip('"')
        if value:
            return unquote(value)
    filename = Path(urlsplit(response.url).path).name
    return unquote(filename or fallback or "archive.zip")


@dataclass
class ResumeInfo:
    supported: bool = False
    etag: str = ""
    last_modified: str = ""
    accept_ranges: str = ""


@dataclass
class DownloadTask:
    id: str
    url: str
    filename: str
    kind: str = "large_file"
    status: str = "queued"
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    tag_data: dict = field(default_factory=dict)
    temp_dir: str = ""
    part_path: str = ""
    final_path: str = ""
    bytes_total: int = 0
    bytes_done: int = 0
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    updated_at: str = ""
    error: str | None = None
    consume_error: str | None = None
    resume: ResumeInfo = field(default_factory=ResumeInfo)

    @classmethod
    def from_dict(cls, data: dict) -> "DownloadTask":
        payload = dict(data)
        payload["resume"] = ResumeInfo(**payload.get("resume", {}))
        return cls(**payload)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def temp_dir_path(self) -> Path:
        return Path(self.temp_dir)

    @property
    def part_file_path(self) -> Path:
        return Path(self.part_path)

    @property
    def final_file_path(self) -> Path:
        return Path(self.final_path)

    @property
    def task_file_path(self) -> Path:
        return self.temp_dir_path / "task.json"


class DownloadManager:
    def __init__(self, max_workers: int = 1):
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fletviewer-download")
        self._tasks: dict[str, DownloadTask] = {}
        self._cancel_requested: set[str] = set()
        self._completion_handlers: list[Callable[[DownloadTask], None]] = []
        self._loaded = False

    def initialize(self) -> None:
        with self._lock:
            if self._loaded:
                return
            ensure_download_dirs()
            self._load_tasks_from_disk()
            self._loaded = True

    def create_task(
        self,
        url: str,
        filename: str,
        *,
        tags: list[str] | None = None,
        tag_data: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> DownloadTask:
        self.initialize()
        task_id = str(uuid.uuid4())
        task_dir = DOWNLOADING_DIR / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        created = now_iso()
        task = DownloadTask(
            id=task_id,
            url=url,
            filename=filename or "archive.zip",
            headers=dict(headers or {}),
            tags=list(tags or []),
            tag_data=dict(tag_data or {}),
            temp_dir=_rel_path(task_dir),
            part_path=_rel_path(task_dir / "payload.part"),
            final_path=_rel_path(task_dir / "payload.zip"),
            created_at=created,
            updated_at=created,
        )
        with self._lock:
            self._tasks[task.id] = task
            self._save_task_locked(task)
            self._save_index_locked()
        return task

    def start_task(self, task_id: str) -> None:
        self.initialize()
        task = self.get_task(task_id)
        if not task:
            return
        with self._lock:
            if task.status == "running":
                return
            self._cancel_requested.discard(task_id)
            task.status = "queued"
            task.error = None
            task.updated_at = now_iso()
            self._save_task_locked(task)
            self._save_index_locked()
        self._executor.submit(self._download_impl, task_id)

    def cancel_task(self, task_id: str) -> None:
        self.initialize()
        with self._lock:
            self._cancel_requested.add(task_id)
            task = self._tasks.get(task_id)
            if task and task.status == "queued":
                task.status = "cancelled"
                task.updated_at = now_iso()
                self._save_task_locked(task)
                self._save_index_locked()

    def retry_task(self, task_id: str) -> None:
        self.initialize()
        task = self.get_task(task_id)
        if not task:
            return
        if task.status in {"failed", "cancelled", "completed"}:
            self.start_task(task_id)

    def delete_task(self, task_id: str) -> None:
        self.initialize()
        with self._lock:
            task = self._tasks.pop(task_id, None)
            self._cancel_requested.add(task_id)
            if task:
                shutil.rmtree(task.temp_dir_path, ignore_errors=True)
            self._save_index_locked()

    def list_tasks(self) -> list[DownloadTask]:
        self.initialize()
        with self._lock:
            return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def get_task(self, task_id: str) -> DownloadTask | None:
        self.initialize()
        with self._lock:
            return self._tasks.get(task_id)

    def add_completion_handler(self, callback: Callable[[DownloadTask], None]) -> None:
        with self._lock:
            if callback not in self._completion_handlers:
                self._completion_handlers.append(callback)

    def mark_consumed(self, task_id: str, *, consume_error: str | None = None) -> None:
        self.initialize()
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if consume_error:
                task.consume_error = consume_error
            else:
                task.status = "consumed"
                task.consume_error = None
            task.updated_at = now_iso()
            self._save_task_locked(task)
            self._save_index_locked()

    def _load_tasks_from_disk(self) -> None:
        for task_file in DOWNLOADING_DIR.glob("*/task.json"):
            try:
                data = json.loads(task_file.read_text(encoding="utf-8"))
                task = DownloadTask.from_dict(data)
                if task.status == "running":
                    task.status = "failed"
                    task.error = "应用退出时任务仍在运行，请重试"
                    task.updated_at = now_iso()
                    self._save_task_locked(task)
                self._tasks[task.id] = task
            except Exception as ex:
                log_exception("download", f"load task failed {task_file}: {ex}")
        self._save_index_locked()
        for task in list(self._tasks.values()):
            if task.status == "completed":
                self._notify_completed(task)

    def _download_impl(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        try:
            task.temp_dir_path.mkdir(parents=True, exist_ok=True)
            part_path = task.part_file_path
            final_path = task.final_file_path
            offset = part_path.stat().st_size if part_path.exists() else 0
            headers = dict(task.headers)
            if offset > 0:
                headers["Range"] = f"bytes={offset}-"

            with self._lock:
                task.status = "running"
                task.started_at = task.started_at or now_iso()
                task.updated_at = now_iso()
                task.bytes_done = offset
                self._save_task_locked(task)
                self._save_index_locked()

            with Timer("download", f"GET stream {task.url}"):
                response = browser_session.get(task.url, headers=headers, stream=True, timeout=60)
            if offset > 0 and response.status_code == 200:
                offset = 0
                mode = "wb"
            elif response.status_code == 206:
                mode = "ab"
            elif response.status_code == 200:
                mode = "wb"
            else:
                response.raise_for_status()
                mode = "wb"

            total_header = int(response.headers.get("Content-Length") or 0)
            if total_header:
                task.bytes_total = total_header + offset
            task.filename = _parse_filename_from_response(response, task.filename)
            task.resume.accept_ranges = response.headers.get("Accept-Ranges", "")
            task.resume.supported = task.resume.accept_ranges.lower() == "bytes" or response.status_code == 206
            task.resume.etag = response.headers.get("ETag", "")
            task.resume.last_modified = response.headers.get("Last-Modified", "")
            with self._lock:
                task.updated_at = now_iso()
                self._save_task_locked(task)
                self._save_index_locked()

            last_save = time.monotonic()
            with open(part_path, mode + ("" if "b" in mode else "b")) as f:
                for chunk in response.iter_content(chunk_size=1024 * 512):
                    if not chunk:
                        continue
                    if task_id in self._cancel_requested:
                        with self._lock:
                            task.status = "cancelled"
                            task.updated_at = now_iso()
                            self._save_task_locked(task)
                            self._save_index_locked()
                        return
                    f.write(chunk)
                    offset += len(chunk)
                    task.bytes_done = offset
                    now = time.monotonic()
                    if now - last_save >= 2:
                        last_save = now
                        with self._lock:
                            task.updated_at = now_iso()
                            self._save_task_locked(task)
                            self._save_index_locked()

            if final_path.exists():
                final_path.unlink()
            part_path.replace(final_path)
            with self._lock:
                task.bytes_done = offset
                if not task.bytes_total:
                    task.bytes_total = offset
                task.status = "completed"
                task.completed_at = now_iso()
                task.updated_at = task.completed_at
                self._save_task_locked(task)
                self._save_index_locked()
            self._notify_completed(task)
        except Exception as ex:
            with self._lock:
                task.status = "failed"
                task.error = str(ex)
                task.updated_at = now_iso()
                self._save_task_locked(task)
                self._save_index_locked()
            log_exception("download", f"download failed {task_id}: {ex}")

    def _notify_completed(self, task: DownloadTask) -> None:
        with self._lock:
            handlers = list(self._completion_handlers)
        for handler in handlers:
            try:
                handler(task)
            except Exception as ex:
                log_exception("download", f"completion handler failed {task.id}: {ex}")

    def _save_task_locked(self, task: DownloadTask) -> None:
        task.temp_dir_path.mkdir(parents=True, exist_ok=True)
        task.task_file_path.write_text(
            json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_index_locked(self) -> None:
        DOWNLOAD_TASKS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "tasks": [
                {
                    "id": task.id,
                    "provider": task.tag_data.get("provider", ""),
                    "status": task.status,
                    "source_url": task.tag_data.get("gallery_url", task.url),
                    "title": task.tag_data.get("gallery_details", {}).get("title", task.filename),
                    "output_dir": task.temp_dir,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                }
                for task in sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
            ]
        }
        DOWNLOAD_TASKS_INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


download_manager = DownloadManager()
