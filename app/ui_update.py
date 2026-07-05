import flet as ft


def request_update(page: ft.Page) -> None:
    """在事件 handler 之外修改 Flet 控件后，强制把 diff 推送到前端。"""
    try:
        page.update()
    except Exception:
        try:
            schedule_update = getattr(page, "schedule_update", None)
            if callable(schedule_update):
                schedule_update()
        except Exception:
            pass
