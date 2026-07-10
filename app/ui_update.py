import flet as ft

from app.debug_log import log_exception


def request_update(page: ft.Page) -> bool:
    """在事件 handler 之外修改 Flet 控件后，强制把 diff 推送到前端。"""
    try:
        page.update()
        return True
    except Exception as ex:
        log_exception("ui_update", f"page.update failed: {ex}")
        return False
