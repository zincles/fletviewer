import flet as ft

from app.storage import should_show_error_toasts


MAX_TOAST_MESSAGE_LENGTH = 180


def _compact_message(message: object) -> str:
    text = " ".join(str(message).strip().split())
    if len(text) <= MAX_TOAST_MESSAGE_LENGTH:
        return text
    return f"{text[:MAX_TOAST_MESSAGE_LENGTH - 1]}..."


def show_toast(page: ft.Page, message: object, *, error: bool = False, duration_ms: int = 3600) -> None:
    """显示一个靠近屏幕底部的轻量提示，用于替代散落的错误状态文案。"""
    text = _compact_message(message)
    if not text:
        return

    content = ft.Row(
        [
            ft.Icon(
                ft.Icons.ERROR_OUTLINE if error else ft.Icons.INFO_OUTLINE,
                size=20,
                color=ft.Colors.ON_INVERSE_SURFACE,
            ),
            ft.Text(
                text,
                size=14,
                color=ft.Colors.ON_INVERSE_SURFACE,
                max_lines=3,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            ),
        ],
        spacing=10,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    toast = ft.SnackBar(
        content=content,
        behavior=ft.SnackBarBehavior.FLOATING,
        bgcolor=ft.Colors.INVERSE_SURFACE,
        duration=duration_ms,
        margin=ft.Margin(16, 0, 16, 24),
        elevation=6,
    )
    toast.open = True
    page.show_dialog(toast)


def show_error_toast(page: ft.Page, where: str, error: object | None = None) -> None:
    if not should_show_error_toasts():
        return
    detail = _compact_message(error) if error is not None else ""
    message = f"{where}: {detail}" if detail else where
    show_toast(page, message, error=True, duration_ms=4600)
