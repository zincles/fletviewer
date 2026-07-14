import flet as ft

from fletviewer_native import FletviewerImageReader


def main(page: ft.Page):
    page.title = "Native Image Reader"
    page.padding = 0
    page.add(
        FletviewerImageReader(
            urls=[
                "https://picsum.photos/id/10/1200/1800",
                "https://picsum.photos/id/20/1800/1200",
                "https://picsum.photos/id/30/1200/1800",
            ],
            expand=True,
            on_change=lambda e: print(f"page: {e.data}"),
        )
    )


ft.run(main)
