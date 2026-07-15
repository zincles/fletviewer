import flet as ft


def create_view(page: ft.Page) -> ft.Control:
    return ft.Container(
        content=ft.Text(
            "用于测试Flet扩展的功能是否可用。",
            size=16,
            color=ft.Colors.ON_SURFACE_VARIANT,
        ),
        alignment=ft.Alignment(0, 0),
        expand=True,
    )
