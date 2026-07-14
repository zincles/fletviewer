from __future__ import annotations

import flet as ft

from app.backend import backend
from app.controls.async_image import async_image
from app.controls.paged_masonry import PagedMasonryView
from app.debug_log import log_exception
from app.toast import show_toast
from app.views.image_viewer import ImageViewerItem
from core.paged_feed import PageBatch
from core.api.dto import MediaItemDTO
from core.provider.booru import BOORU_PROVIDERS


def create_provider_view(page: ft.Page, provider_id: str) -> ft.Control:
    display_name = BOORU_PROVIDERS[provider_id]
    query_state = {"value": ""}
    viewer_state: dict[str, list[ImageViewerItem]] = {"items": []}

    def load_page(cursor):
        result = backend.search_booru(provider_id, query_state["value"], cursor=cursor)
        return PageBatch(result.items, result.next_cursor)

    def update_viewer_items(posts: list[MediaItemDTO]) -> None:
        viewer_state["items"] = [
            ImageViewerItem(
                url=post.image_url,
                title=post.title,
                detail={
                    "provider": provider_id,
                    "post_id": str(post.id),
                    "page_url": post.page_url,
                    "rating": post.rating,
                    "score": post.score,
                    "tags": post.tags,
                },
            )
            for post in posts
            if post.image_url
        ]

    def build_image(post: MediaItemDTO, index: int) -> ft.Control:
        return ft.Container(
            content=async_image(
                page,
                post.thumbnail_url,
                width=float("inf"),
                height=float("inf"),
                fit=ft.BoxFit.COVER,
                cache_width=220,
            ),
            expand=True,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            border_radius=8,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        )

    def open_image(_post: MediaItemDTO, index: int) -> None:
        open_viewer = getattr(page, "fletviewer_open_image_viewer", None)
        if callable(open_viewer):
            open_viewer(viewer_state["items"], index)

    def aspect_ratio(post: MediaItemDTO) -> float:
        return post.aspect_ratio or 0.72

    def show_error(ex: Exception) -> None:
        log_exception("Booru", f"{display_name} 搜索失败：{ex}")
        show_toast(page, f"{display_name} 搜索失败")

    masonry = PagedMasonryView[MediaItemDTO, int | str](
        page,
        load_page=load_page,
        build_image=build_image,
        item_key=lambda post: f"{provider_id}:{post.id}",
        aspect_ratio=aspect_ratio,
        on_item_click=open_image,
        on_items_changed=update_viewer_items,
        on_error=show_error,
        loading_source=f"booru:{provider_id}",
    )

    def search(query: str | None = None, **_kwargs) -> None:
        query_state["value"] = (query or "").strip()
        masonry.reload()

    actions = getattr(page, "fletviewer_booru_search_actions", None)
    if isinstance(actions, dict):
        actions[display_name] = search
    return masonry


def create_safebooru_view(page: ft.Page) -> ft.Control:
    return create_provider_view(page, "safebooru")


def create_gelbooru_view(page: ft.Page) -> ft.Control:
    return create_provider_view(page, "gelbooru")


def create_danbooru_view(page: ft.Page) -> ft.Control:
    return create_provider_view(page, "danbooru")


def provider_view_factory(provider_id: str):
    return lambda page: create_provider_view(page, provider_id)
