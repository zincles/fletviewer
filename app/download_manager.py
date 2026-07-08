from app.browser_session import browser_session
from app.debug_log import Timer, log_exception
from app.storage import DATA_DB_PATH, DOWNLOADING_DIR, ensure_download_dirs
from lib.data.data_db import AppDataDB
from lib.download.manager import DownloadManager, DownloadTask, ResumeInfo, TASK_STATUSES, now_iso


def _stream_get(url: str, **kwargs):
    return browser_session.get(url, **kwargs)


download_manager = DownloadManager(
    downloading_dir=DOWNLOADING_DIR,
    data_db=AppDataDB(DATA_DB_PATH, ensure_dirs=ensure_download_dirs),
    ensure_dirs=ensure_download_dirs,
    stream_get=_stream_get,
    log_exception=log_exception,
    timer_factory=Timer,
)


__all__ = [
    "DownloadManager",
    "DownloadTask",
    "ResumeInfo",
    "TASK_STATUSES",
    "download_manager",
    "now_iso",
]
