import logging
import os
import sys
import time
import traceback

from app.storage import ROOT_DIR


_QUIET_AREAS = {"image"}
_CACHE_KEYWORDS = ("cache", "缓存", "gallery_cache", "命中", "cache read", "cache write")
_WEB_KEYWORDS = ("GET", "POST", "HEAD", "抓取", "请求", "浏览器会话", "EH解析", "network fetched")
DEBUG_LOG_PATH = ROOT_DIR / "debug_log.md"
_LOGGER = logging.getLogger("fletviewer")


def _setup_logger() -> None:
    """配置标准库 logging：终端和数据根目录日志文件双写。"""
    _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.handlers.clear()
    _LOGGER.propagate = False
    formatter = logging.Formatter("%(message)s")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    _LOGGER.addHandler(console_handler)

    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(DEBUG_LOG_PATH, mode="w", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        _LOGGER.addHandler(file_handler)
        _LOGGER.info("# FletViewer Debug Log")
        _LOGGER.info("")
        _LOGGER.info("Started at %s", time.strftime("%Y-%m-%d %H:%M:%S"))
        _LOGGER.info("")
    except Exception:
        pass


_setup_logger()


def _write_log_line(line: str) -> None:
    """输出一行日志；实际双写由 logging handlers 完成。"""
    _LOGGER.info(line)


def _enabled(area: str) -> bool:
    """判断指定日志区域是否应该输出。"""
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
    """输出普通调试日志；高频图片日志默认静音。"""
    if not _enabled(area):
        return
    now = time.strftime("%H:%M:%S")
    _write_log_line(f"[{now}][{_prefix(area, message)}{area}] {message}")


def _format_bytes_binary(value: int) -> str:
    """把字节数格式化为 KiB/MiB 等二进制单位。"""
    size = float(value or 0)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.3f} {unit}"
        size /= 1024
    return f"{int(value or 0)} B"


def format_duration_ms(value: float) -> str:
    """格式化毫秒耗时；超过 1 秒时使用秒并保留两位小数。"""
    elapsed = float(value or 0)
    if elapsed >= 1000:
        return f"{elapsed / 1000:.2f}s"
    return f"{elapsed:.0f}ms"


def log_image_served(source: str, elapsed_ms: float, url: str, bytes_count: int) -> None:
    """输出单行图片任务摘要。"""
    now = time.strftime("%H:%M:%S")
    _write_log_line(f"[{now}][async_image][{source}][{format_duration_ms(elapsed_ms)}][{_format_bytes_binary(bytes_count)}] {url}")


def _prefix(area: str, message: str) -> str:
    """按日志内容返回缓存/Web 前缀图标。"""
    text = f"{area} {message}"
    if any(keyword in text for keyword in _CACHE_KEYWORDS):
        return "💾 "
    if any(keyword in text for keyword in _WEB_KEYWORDS):
        return "🌐 "
    return ""


def log_exception(area: str, message: str) -> None:
    """输出异常日志和 traceback；异常不受区域静音影响。"""
    now = time.strftime("%H:%M:%S")
    _write_log_line(f"[{now}][{_prefix(area, message)}{area}] {message}")
    trace = traceback.format_exc()
    _LOGGER.info("```text")
    for line in trace.rstrip("\n").splitlines():
        _LOGGER.info(line)
    _LOGGER.info("```")


class Timer:
    """简单耗时日志上下文管理器。"""

    def __init__(self, area: str, message: str):
        """记录日志区域和计时说明。"""
        self.area = area
        self.message = message
        self.started_at = 0.0

    def __enter__(self):
        """开始计时。"""
        self.started_at = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        """结束计时并输出 END/ERROR 日志。"""
        elapsed_ms = (time.perf_counter() - self.started_at) * 1000
        status = "ERROR " if exc_type else ""
        log_debug(self.area, f"{status}{self.message} 用时={format_duration_ms(elapsed_ms)}")
        return False
