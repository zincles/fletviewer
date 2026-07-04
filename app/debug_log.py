import os
import time
import traceback


_QUIET_AREAS = {"image", "async_image"}
_CACHE_KEYWORDS = ("cache", "缓存", "gallery_cache", "命中", "cache read", "cache write")
_WEB_KEYWORDS = ("GET", "POST", "HEAD", "抓取", "请求", "浏览器会话", "EH解析", "network fetched")


def _enabled(area: str) -> bool:
    if os.environ.get("FLETVIEWER_DEBUG_ALL") == "1":
        return True
    enabled = {
        item.strip()
        for item in os.environ.get("FLETVIEWER_DEBUG_AREAS", "").split(",")
        if item.strip()
    }
    if enabled:
        return area in enabled
    return area not in _QUIET_AREAS


def log_debug(area: str, message: str) -> None:
    if not _enabled(area):
        return
    now = time.strftime("%H:%M:%S")
    print(f"[{now}][{_prefix(area, message)}{area}] {message}", flush=True)


def _prefix(area: str, message: str) -> str:
    text = f"{area} {message}"
    if any(keyword in text for keyword in _CACHE_KEYWORDS):
        return "💾 "
    if any(keyword in text for keyword in _WEB_KEYWORDS):
        return "🌐 "
    return ""


def log_exception(area: str, message: str) -> None:
    now = time.strftime("%H:%M:%S")
    print(f"[{now}][{_prefix(area, message)}{area}] {message}", flush=True)
    traceback.print_exc()


class Timer:
    def __init__(self, area: str, message: str):
        self.area = area
        self.message = message
        self.started_at = 0.0

    def __enter__(self):
        self.started_at = time.perf_counter()
        log_debug(self.area, f"START {self.message}")
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed_ms = (time.perf_counter() - self.started_at) * 1000
        status = "ERROR" if exc_type else "END"
        log_debug(self.area, f"{status} {self.message} ({elapsed_ms:.0f} ms)")
        return False
