from app.browser_session import browser_session
from app.backend import runtime
from app.debug_log import Timer, log_exception
from app.lazy import LazyProxy
from app.notifications import notifier
from app.storage import ensure_download_dirs, get_storage_layout
from core.data.data_db import AppDataDB
from core.download.manager import DownloadManager, DownloadTask, ResumeInfo, TASK_STATUSES, now_iso


def _stream_get(url: str, **kwargs):
    return browser_session.get(url, **kwargs)


def _create_download_manager() -> DownloadManager:
    layout = get_storage_layout()
    return DownloadManager(
        downloading_dir=layout.downloading_dir,
        data_db=AppDataDB(layout.data_db, ensure_dirs=ensure_download_dirs),
        ensure_dirs=ensure_download_dirs,
        stream_get=_stream_get,
        log_exception=log_exception,
        timer_factory=Timer,
        notify=notifier.send,
    )


download_manager = LazyProxy(_create_download_manager)
runtime.configure_download_manager(download_manager)


__all__ = [
    "DownloadManager",
    "DownloadTask",
    "ResumeInfo",
    "TASK_STATUSES",
    "download_manager",
    "now_iso",
]
