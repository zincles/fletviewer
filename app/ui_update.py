import flet as ft


def request_update(page: ft.Page) -> None:
    try:
        page.update()
    except Exception:
        try:
            schedule_update = getattr(page, "schedule_update", None)
            if callable(schedule_update):
                schedule_update()
        except Exception:
            pass
