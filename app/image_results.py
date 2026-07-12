from __future__ import annotations

import threading
import time
import weakref
from collections import deque
from typing import Callable

import flet as ft

from app.debug_log import log_exception
from app.ui_update import request_update


class ImageResultPump:
    """每个 Page 用单一 worker 小批量应用图片结果，避免耗尽 Flet 事件线程。"""

    def __init__(self, page: ft.Page, *, batch_size: int = 2) -> None:
        self._page_ref = weakref.ref(page)
        self._batch_size = max(1, batch_size)
        self._lock = threading.Lock()
        self._pending: deque[Callable[[], bool]] = deque()
        self._running = False
        self._navigation_priority_until = 0.0

    def enqueue(self, apply: Callable[[], bool]) -> None:
        with self._lock:
            self._pending.append(apply)
            if self._running:
                return
            self._running = True
        page = self._page_ref()
        if page is None:
            self._stop()
            return
        try:
            page.run_thread(self._run)
        except Exception:
            self._stop()
            raise

    def prioritize_navigation(self, seconds: float = 0.25) -> None:
        """短暂暂停图片 diff，让导航更新优先进入远程 session。"""
        with self._lock:
            self._navigation_priority_until = max(
                self._navigation_priority_until,
                time.monotonic() + max(0.0, seconds),
            )

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def _run(self) -> None:
        try:
            while True:
                with self._lock:
                    delay = self._navigation_priority_until - time.monotonic()
                    if delay <= 0:
                        batch = [self._pending.popleft() for _ in range(min(self._batch_size, len(self._pending)))]
                    else:
                        batch = []
                    if not batch and delay <= 0:
                        self._running = False
                        return
                if delay > 0:
                    time.sleep(min(delay, 0.05))
                    continue
                changed = False
                for apply in batch:
                    try:
                        changed = apply() or changed
                    except Exception as ex:
                        log_exception("异步图像", f"应用图片结果失败：{ex}")
                page = self._page_ref()
                if page is None:
                    return
                if changed and not request_update(page):
                    return
                # 给点击、路由和其他 UI handler 留出执行机会。
                time.sleep(0.01)
        finally:
            page = self._page_ref()
            restart = False
            with self._lock:
                self._running = False
                if self._pending and page is not None:
                    self._running = True
                    restart = True
            if restart:
                try:
                    page.run_thread(self._run)
                except Exception as ex:
                    self._stop()
                    log_exception("异步图像", f"重启图片结果泵失败：{ex}")

    def _stop(self) -> None:
        with self._lock:
            self._running = False



_PUMP_ATTRIBUTE = "_fletviewer_image_result_pump"
_PUMPS_LOCK = threading.Lock()


def image_result_pump(page: ft.Page) -> ImageResultPump:
    with _PUMPS_LOCK:
        pump = getattr(page, _PUMP_ATTRIBUTE, None)
        if pump is None:
            pump = ImageResultPump(page)
            setattr(page, _PUMP_ATTRIBUTE, pump)
        return pump


__all__ = ["ImageResultPump", "image_result_pump"]
