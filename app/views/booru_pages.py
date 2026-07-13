from __future__ import annotations

import flet as ft

from app.booru_session import get_booru_client
from app.controls.async_image import async_image
from app.controls.masonry_gallery import MasonryGallery, MasonryItem
from app.debug_log import log_exception
from app.grid_layout import runs_count_for_width
from app.toast import show_toast
from app.ui_update import request_update
from app.views.image_viewer import ImageViewerItem
from core.provider.booru import BOORU_PROVIDERS, BooruProviderError


def create_provider_view(page: ft.Page, provider_id: str) -> ft.Control:
    display_name = BOORU_PROVIDERS[provider_id]
    status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    load_more_button = ft.FilledButton("加载下一页", icon=ft.Icons.EXPAND_MORE, disabled=True)
    column_state = {"value": runs_count_for_width(page.width, min_columns=2, max_columns=10)}
    masonry_gallery = MasonryGallery(column_count=column_state["value"], spacing=10)
    load_more_host = ft.Container(
        content=load_more_button,
        alignment=ft.Alignment(0, 0),
        padding=ft.Padding(0, 12, 0, 12),
    )
    results_list = ft.ListView(
        expand=True,
        padding=ft.Padding(0, 4, 0, 0),
        controls=[masonry_gallery, load_more_host],
    )
    empty_state = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED, size=42, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text("输入标签开始搜索", color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
        ),
        alignment=ft.Alignment(0, 0),
        expand=True,
    )
    results_host = ft.Stack([results_list, empty_state], expand=True)
    search_state = {"busy": False, "page": None, "next_page": None, "posts": [], "viewer_items": []}

    def render_posts(posts, *, append: bool):
        previous_count = len(search_state["posts"])
        all_posts = [*search_state["posts"], *posts] if append else list(posts)
        search_state["posts"] = all_posts
        search_state["viewer_items"] = [
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
            for post in all_posts
            if post.image_url
        ]

        def card(index, post):
            image = ft.Container(
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
            open_viewer = getattr(page, "fletviewer_open_image_viewer", None)
            if callable(open_viewer):
                return ft.GestureDetector(
                    content=image,
                    mouse_cursor=ft.MouseCursor.CLICK,
                    on_tap=lambda e, i=index: open_viewer(search_state["viewer_items"], i),
                )
            return image

        visible_posts = [post for post in all_posts if post.image_url]
        rendered_posts = [post for post in posts if post.image_url] if append else visible_posts
        start_index = sum(1 for post in all_posts[:previous_count] if post.image_url) if append else 0
        items = [
            MasonryItem(
                card(start_index + index, post),
                post.original.width / post.original.height if post.original.width and post.original.height else 0.72,
                key=f"{provider_id}:{post.id}",
            )
            for index, post in enumerate(rendered_posts)
        ]
        if append:
            masonry_gallery.append_batch(items)
        else:
            masonry_gallery.set_items(items)
        empty_state.visible = not visible_posts
        if not visible_posts:
            empty_state.content.controls[1].value = "没有找到可显示的图片"

    def search(search_query: str | None = None, *, target_page=None, append: bool = False):
        if search_state["busy"]:
            return
        if search_query is not None:
            search_state["query"] = search_query.strip()
        search_state["busy"] = True
        load_more_button.disabled = True
        status.value = "正在搜索..."
        page.update()

        def worker():
            try:
                result = get_booru_client(provider_id).search_posts(
                    str(search_state.get("query") or ""),
                    page=target_page,
                )
                search_state["page"] = result.page
                search_state["next_page"] = result.next_page
                render_posts(result.posts, append=append)
                load_more_button.disabled = result.next_page is None
                status.value = ""
                status.color = ft.Colors.PRIMARY
            except BooruProviderError as ex:
                status.value = str(ex)
                status.color = ft.Colors.ERROR
                log_exception("Booru", f"{display_name} 搜索失败：{ex}")
                show_toast(page, f"{display_name} 搜索失败")
            except Exception as ex:
                status.value = f"{display_name} 搜索失败: {ex}"
                status.color = ft.Colors.ERROR
                log_exception("Booru", f"{display_name} 未预期搜索错误：{ex}")
                show_toast(page, f"{display_name} 搜索失败")
            finally:
                search_state["busy"] = False
                load_more_button.disabled = search_state["next_page"] is None
                request_update(page)

        page.run_thread(worker)

    actions = getattr(page, "fletviewer_booru_search_actions", None)
    if isinstance(actions, dict):
        actions[display_name] = search
    def on_results_scroll(e):
        if search_state["busy"] or search_state["next_page"] is None:
            return
        pixels = float(getattr(e, "pixels", 0) or 0)
        max_extent = float(getattr(e, "max_scroll_extent", 0) or 0)
        if max_extent and pixels >= max_extent - 480:
            search(None, target_page=search_state["next_page"], append=True)

    results_list.on_scroll = on_results_scroll
    load_more_button.on_click = lambda e: search(
        None,
        target_page=search_state["next_page"],
        append=True,
    )

    def update_columns(e=None):
        new_count = runs_count_for_width(page.width, min_columns=2, max_columns=10)
        if masonry_gallery.set_column_count(new_count):
            column_state["value"] = new_count
            request_update(page)

    add_resize_handler = getattr(page, "fletviewer_add_resize_handler", None)
    if callable(add_resize_handler):
        add_resize_handler(update_columns)
    view = ft.Container(
        expand=True,
        padding=ft.Padding(10, 108, 10, 86),
        content=ft.Stack(
            [
                results_host,
                ft.Container(
                    content=status,
                    alignment=ft.Alignment(0, -1),
                    padding=8,
                    ignore_interactions=True,
                ),
            ]
        ),
    )
    search("")
    return view


def create_safebooru_view(page: ft.Page) -> ft.Control:
    return create_provider_view(page, "safebooru")


def create_gelbooru_view(page: ft.Page) -> ft.Control:
    return create_provider_view(page, "gelbooru")


def create_danbooru_view(page: ft.Page) -> ft.Control:
    return create_provider_view(page, "danbooru")
