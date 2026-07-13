from __future__ import annotations

import flet as ft

from app.booru_session import get_booru_client
from app.controls.async_image import async_image
from app.controls.paged_masonry import PagedMasonryView
from app.debug_log import log_exception
from app.toast import show_toast
from app.views.image_viewer import ImageViewerItem
from core.paged_feed import PageBatch
from core.provider.booru import BOORU_PROVIDERS, BooruPost


def create_provider_view(page: ft.Page, provider_id: str) -> ft.Control:
    display_name = BOORU_PROVIDERS[provider_id]
    query_state = {"value": ""}
    viewer_state: dict[str, list[ImageViewerItem]] = {"items": []}

    def load_page(cursor):
        result = get_booru_client(provider_id).search_posts(query_state["value"], page=cursor)
        return PageBatch(result.posts, result.next_page)

    def update_viewer_items(posts: list[BooruPost]) -> None:
        viewer_state["items"] = [
            ImageViewerItem(
                url=post.image_url,
                title=f"{display_name} #{post.id}",
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

    def build_image(post: BooruPost, index: int) -> ft.Control:
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

    def open_image(_post: BooruPost, index: int) -> None:
        open_viewer = getattr(page, "fletviewer_open_image_viewer", None)
        if callable(open_viewer):
            open_viewer(viewer_state["items"], index)

    def aspect_ratio(post: BooruPost) -> float:
        return post.original.width / post.original.height if post.original.width and post.original.height else 0.72

    def show_error(ex: Exception) -> None:
        log_exception("Booru", f"{display_name} 搜索失败：{ex}")
        show_toast(page, f"{display_name} 搜索失败")

    masonry = PagedMasonryView[BooruPost, int](
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
