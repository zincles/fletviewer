import threading
import time
import weakref

import flet as ft

from app.debug_log import log_exception
from app.ui_update import request_update


class ImageProgressPump:
    """每个 Page 使用一个 worker，批量刷新所有已挂载图像的进度。"""

    def __init__(self, page: ft.Page):
        self._page_ref = weakref.ref(page)
        self._lock = threading.Lock()
        self._controls: dict[int, weakref.ReferenceType] = {}
        self._running = False

    def register(self, control) -> None:
        with self._lock:
            control_id = id(control)
            self._controls[control_id] = weakref.ref(
                control,
                lambda _ref, key=control_id: self._remove_dead_control(key),
            )
            if self._running:
                return
            self._running = True
        page = self._page_ref()
        if page is not None:
            try:
                page.run_thread(self._run)
            except Exception:
                with self._lock:
                    self._running = False
                raise

    def unregister(self, control) -> None:
        with self._lock:
            self._controls.pop(id(control), None)

    def _remove_dead_control(self, control_id: int) -> None:
        with self._lock:
            self._controls.pop(control_id, None)

    def _run(self) -> None:
        try:
            while True:
                with self._lock:
                    controls = [control for ref in self._controls.values() if (control := ref()) is not None]
                    if not controls:
                        self._running = False
                        return
                changed = False
                for control in controls:
                    changed = control._refresh_progress() or changed
                page = self._page_ref()
                if page is None:
                    return
                if changed and not request_update(page):
                    return
                time.sleep(0.2)
        except Exception as ex:
            log_exception("图像进度", f"刷新图像进度失败：{ex}")
        finally:
            with self._lock:
                self._running = False


_PUMPS_LOCK = threading.Lock()
_PUMP_ATTRIBUTE = "_fletviewer_image_progress_pump"


def image_progress_pump(page: ft.Page) -> ImageProgressPump:
    with _PUMPS_LOCK:
        pump = getattr(page, _PUMP_ATTRIBUTE, None)
        if pump is None:
            pump = ImageProgressPump(page)
            setattr(page, _PUMP_ATTRIBUTE, pump)
        return pump
