from __future__ import annotations

import flet as ft

from app.controls.async_image import async_image
from app.controls.paged_masonry import PagedMasonryView
from app.debug_log import log_exception
from app.backend import backend
from app.toast import show_toast
from app.views.image_viewer import ImageViewerItem
from core.paged_feed import PageBatch
from core.api.dto import MediaItemDTO


def _create_illust_feed(page: ft.Page, *, label: str, load_page) -> ft.Control:
    viewer_state: dict[str, list[ImageViewerItem]] = {"items": []}

    def update_viewer_items(illusts: list[MediaItemDTO]) -> None:
        viewer_state["items"] = [
            ImageViewerItem(
                url=illust.thumbnail_url,
                title=illust.title or f"Pixiv #{illust.id}",
                detail={
                    "provider": "pixiv",
                    "illust_id": illust.id,
                    "page_url": f"https://www.pixiv.net/artworks/{illust.id}",
                    "thumbnail_width": illust.width,
                    "thumbnail_height": illust.height,
                    "tags": illust.tags.get("general", []),
                },
            )
            for illust in illusts
            if illust.thumbnail_url
        ]

    def build_image(illust: MediaItemDTO, _index: int) -> ft.Control:
        return ft.Container(
            content=async_image(page, illust.thumbnail_url, width=float("inf"), height=float("inf"), fit=ft.BoxFit.COVER, cache_width=220),
            expand=True,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            border_radius=8,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        )

    def open_image(_illust: MediaItemDTO, index: int) -> None:
        open_viewer = getattr(page, "fletviewer_open_image_viewer", None)
        if callable(open_viewer):
            open_viewer(viewer_state["items"], index)

    def aspect_ratio(illust: MediaItemDTO) -> float:
        return illust.aspect_ratio or 0.72

    def show_error(ex: Exception) -> None:
        log_exception("Pixiv", f"{label} 加载失败：{ex}")
        show_toast(page, f"Pixiv {label} 加载失败")

    return PagedMasonryView[MediaItemDTO, str](
        page,
        load_page=load_page,
        build_image=build_image,
        item_key=lambda illust: f"pixiv:{illust.id}",
        aspect_ratio=aspect_ratio,
        on_item_click=open_image,
        on_items_changed=update_viewer_items,
        on_error=show_error,
        loading_source=f"pixiv:{label}",
    )


def create_ranking_view(page: ft.Page) -> ft.Control:
    def load_page(cursor):
        result = backend.get_pixiv_feed("ranking", cursor=cursor)
        return PageBatch(result.items, result.next_cursor)

    return _create_illust_feed(page, label="排行", load_page=load_page)


def create_search_view(page: ft.Page) -> ft.Control:
    query_state = {"value": ""}

    def load_page(cursor):
        result = backend.search_pixiv(query_state["value"], cursor=cursor)
        return PageBatch(result.items, result.next_cursor)

    masonry = _create_illust_feed(page, label="搜索", load_page=load_page)

    def search(query: str | None = None, **_kwargs) -> None:
        query_state["value"] = (query or "").strip()
        masonry.reload()

    actions = getattr(page, "fletviewer_pixiv_search_actions", None)
    if isinstance(actions, dict):
        actions["搜索"] = search
    return masonry


def _placeholder_page(title: str, subtitle: str, icon) -> ft.Control:
    return ft.Container(
        expand=True,
        padding=24,
        alignment=ft.Alignment(0, 0),
        content=ft.Column(
            [
                ft.Icon(icon, size=42, color=ft.Colors.PRIMARY),
                ft.Text(title, size=24, weight=ft.FontWeight.BOLD),
                ft.Text(subtitle, size=14, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
            ],
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def create_home_view(page: ft.Page) -> ft.Control:
    def load_page(cursor):
        result = backend.get_pixiv_feed("recommended", cursor=cursor)
        return PageBatch(result.items, result.next_cursor)

    return _create_illust_feed(page, label="推荐", load_page=load_page)


def create_following_view(page: ft.Page) -> ft.Control:
    def load_page(cursor):
        result = backend.get_pixiv_feed("following", cursor=cursor)
        return PageBatch(result.items, result.next_cursor)

    return _create_illust_feed(page, label="关注", load_page=load_page)


def create_bookmarks_view(page: ft.Page) -> ft.Control:
    def load_page(cursor):
        result = backend.get_pixiv_feed("bookmarks", cursor=cursor)
        return PageBatch(result.items, result.next_cursor)

    return _create_illust_feed(page, label="收藏", load_page=load_page)


def create_history_view(page: ft.Page) -> ft.Control:
    return _placeholder_page("Pixiv 历史", "本地历史接入尚未实现。", ft.Icons.HISTORY)
