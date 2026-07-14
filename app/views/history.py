import flet as ft

from app.controls.masonry_gallery import MasonryGallery, MasonryItem
from app.backend import backend
from app.grid_layout import runs_count_for_width
from app.storage import get_gallery_view_mode
from app.views.gallery_cards import make_gallery_card


def create_view(page: ft.Page) -> ft.Control:
    """用历史中的 Comic 快照重建统一画廊浏览界面。"""
    status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    content = ft.Container(expand=True)
    view_mode = get_gallery_view_mode()
    column_count = runs_count_for_width(page.width, min_columns=2, max_columns=10)

    def build_content(comics) -> ft.Control:
        cards = [make_gallery_card(page, comic, mode=view_mode) for comic in comics]
        if view_mode == "list":
            return ft.ListView(cards, expand=True, spacing=8, padding=10)
        if view_mode == "masonry":
            gallery = MasonryGallery(column_count=column_count, spacing=0)
            gallery.set_items(
                [
                    MasonryItem(card, comic.cover_aspect_ratio, key=comic.id)
                    for comic, card in zip(comics, cards)
                ]
            )
            return ft.ListView([gallery], expand=True, padding=10)
        return ft.GridView(
            cards,
            expand=True,
            runs_count=column_count,
            spacing=0,
            run_spacing=0,
            child_aspect_ratio=0.72,
            padding=10,
        )

    def refresh(e=None):
        comics = [entry.media for entry in backend.list_history(kind="gallery")]
        status.value = f"共 {len(comics)} 条画廊浏览记录"
        content.content = build_content(comics) if comics else ft.Container(
            content=ft.Text("暂无画廊浏览历史", color=ft.Colors.ON_SURFACE_VARIANT),
            alignment=ft.Alignment(0, 0),
            expand=True,
        )
        if e is not None:
            page.update()

    def clear(e=None):
        backend.clear_history(kind="gallery")
        refresh(e)

    refresh_btn = ft.Button("刷新", icon=ft.Icons.REFRESH, on_click=refresh)
    clear_btn = ft.OutlinedButton("清空历史", icon=ft.Icons.DELETE_SWEEP, on_click=clear)
    refresh()
    return ft.Container(
        content=ft.Column(
            [
                ft.Row([status, clear_btn, refresh_btn], alignment=ft.MainAxisAlignment.END, wrap=True),
                content,
            ],
            spacing=8,
            expand=True,
        ),
        padding=ft.Padding(10, 108, 10, 86),
        expand=True,
    )
