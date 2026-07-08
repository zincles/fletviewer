import time

import flet as ft


def _event_value(event, name: str):
    value = getattr(event, name, None)
    if value is None:
        return None
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _event_summary(event, event_name: str) -> str:
    fields = [
        "local_x",
        "local_y",
        "global_x",
        "global_y",
        "delta_x",
        "delta_y",
        "primary_delta",
        "velocity_x",
        "velocity_y",
        "buttons",
        "kind",
        "device",
        "scroll_delta_x",
        "scroll_delta_y",
    ]
    parts = [f"{event_name} @ {time.strftime('%H:%M:%S')}"]
    for name in fields:
        value = _event_value(event, name)
        if value is not None:
            parts.append(f"{name}={value}")
    return "  ".join(parts)


def create_view(page: ft.Page) -> ft.Control:
    latest = ft.Text("暂无输入", size=13, selectable=True)
    history = ft.Column(spacing=4)

    def record(event_name: str, event):
        line = _event_summary(event, event_name)
        print(f"[input-test] {line}", flush=True)
        latest.value = line
        history.controls.insert(0, ft.Text(line, size=12, selectable=True))
        del history.controls[20:]
        page.update()

    probe = ft.GestureDetector(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.TOUCH_APP, size=42, color=ft.Colors.PRIMARY),
                    ft.Text("在这里点击、拖动、滚轮", size=18, weight=ft.FontWeight.BOLD),
                    ft.Text("事件会同时显示在这里，并 print 到启动 Flet 的终端。", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=260,
            alignment=ft.Alignment(0, 0),
            border=ft.border.Border.all(1, ft.Colors.PRIMARY),
            border_radius=16,
            bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.PRIMARY),
        ),
        on_tap_down=lambda e: record("tap_down", e),
        on_tap_move=lambda e: record("tap_move", e),
        on_pan_down=lambda e: record("pan_down", e),
        on_pan_start=lambda e: record("pan_start", e),
        on_pan_update=lambda e: record("pan_update", e),
        on_pan_end=lambda e: record("pan_end", e),
        on_horizontal_drag_down=lambda e: record("horizontal_drag_down", e),
        on_horizontal_drag_start=lambda e: record("horizontal_drag_start", e),
        on_horizontal_drag_update=lambda e: record("horizontal_drag_update", e),
        on_horizontal_drag_end=lambda e: record("horizontal_drag_end", e),
        on_scroll=lambda e: record("scroll", e),
        allowed_devices=[ft.PointerDeviceType.TOUCH, ft.PointerDeviceType.STYLUS, ft.PointerDeviceType.MOUSE, ft.PointerDeviceType.TRACKPAD],
        drag_interval=16,
    )

    return ft.Column(
        [
            ft.Text("输入测试", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("这是独立页面，用于验证 Flet GestureDetector 能否读到用户输入。", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            probe,
            ft.Text("最近事件", size=16, weight=ft.FontWeight.BOLD),
            latest,
            ft.Divider(),
            history,
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
