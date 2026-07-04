import dataclasses
import json
import threading

import flet as ft

from app.browser_session import browser_session
from app.controls.async_image import async_image
from app.debug_log import Timer, log_debug, log_exception
from lib.provider.ehgrabber import Comic, ThumbnailItem
from app.views.image_viewer import ImageViewerItem


def _to_jsonable(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return value


def _tag_pill(text: str) -> ft.Control:
    return ft.Container(
        content=ft.Text(text, size=12, color=ft.Colors.ON_SURFACE),
        padding=ft.Padding(8, 4, 8, 4),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_radius=999,
    )


def _make_tag_controls(tags: dict[str, list[str]]) -> list[ft.Control]:
    controls: list[ft.Control] = []
    for namespace, values in tags.items():
        if not values:
            continue
        controls.append(ft.Text(f"{namespace}:", size=13, weight=ft.FontWeight.BOLD))
        controls.extend(_tag_pill(tag) for tag in values)
    return controls


def create_view(page: ft.Page, comic: Comic, on_back) -> ft.Control:
    title = ft.Text(comic.title or "加载中...", size=28, weight=ft.FontWeight.BOLD, selectable=True)
    subtitle = ft.Text(comic.id, size=13, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True)
    status = ft.Text("加载中...", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
    cover_box = ft.Container(
        content=async_image(page, comic.cover, width=260, height=360, fit=ft.BoxFit.COVER, cache_width=520),
        width=260,
        height=360,
        border_radius=8,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )
    meta = ft.Column(
        controls=[
            title,
            subtitle,
            ft.Row(
                [
                    ft.Text(comic.type, size=13),
                    ft.Text(f"{comic.max_page}P", size=13),
                    ft.Text(f"★{comic.stars}", size=13),
                ],
                spacing=12,
            ),
            status,
        ],
        spacing=8,
        expand=True,
    )
    tags_wrap = ft.Row(wrap=True, spacing=8, run_spacing=8)
    thumbs_grid = ft.GridView(
        height=360,
        runs_count=8,
        spacing=8,
        run_spacing=8,
        child_aspect_ratio=0.72,
    )
    raw_json = ft.Text("{}", size=12, selectable=True)

    def worker():
        try:
            log_debug("detail", f"load start {comic.id}")
            client = browser_session.get_eh_client(require_login=False)
            with Timer("detail", f"load_comic_info {comic.id}"):
                details = client.load_comic_info(comic.id)
            with Timer("detail", f"load_thumbnails {comic.id}"):
                thumbs = client.load_thumbnails(comic.id)

            title.value = details.title or comic.title
            subtitle.value = details.sub_title or details.url or comic.id
            if details.cover:
                cover_box.content = async_image(page, details.cover, width=260, height=360, fit=ft.BoxFit.COVER, cache_width=520)

            tags_wrap.controls = _make_tag_controls(details.tags)
            thumb_items = thumbs.items or [
                ThumbnailItem(url=thumb, page_url=page_url)
                for page_url, thumb in zip(thumbs.urls, thumbs.thumbnails)
            ]
            viewer_items = [
                ImageViewerItem(
                    url=item.page_url,
                    title=f"{details.title or comic.title} #{idx + 1}",
                    detail={
                        "gallery_url": comic.id,
                        "page_url": item.page_url,
                        "thumbnail_url": item.url,
                        "thumbnail_width": item.width,
                        "thumbnail_height": item.height,
                        "thumbnail_aspect_ratio": item.aspect_ratio,
                    },
                )
                for idx, item in enumerate(thumb_items)
            ]

            def resolve_full_image(item: ImageViewerItem, idx: int) -> str:
                client = browser_session.get_eh_client(require_login=False)
                with Timer("detail", f"resolve full image {comic.id} index={idx}"):
                    result = client.get_image_url(comic.id, idx)
                return result.url

            def make_thumb(idx: int, thumb: str) -> ft.Control:
                item = viewer_items[idx]
                box = ft.Container(
                    content=async_image(page, thumb, width=float("inf"), height=150, fit=ft.BoxFit.COVER, cache_width=220),
                    border_radius=6,
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                )
                open_viewer = getattr(page, "fletviewer_open_image_viewer", None)
                if callable(open_viewer):
                    return ft.GestureDetector(
                        content=box,
                        mouse_cursor=ft.MouseCursor.CLICK,
                        on_tap=lambda e, i=idx: open_viewer(viewer_items, i, resolve_full_image),
                    )
                return box

            thumbs_grid.controls = [make_thumb(idx, item.detail["thumbnail_url"]) for idx, item in enumerate(viewer_items)]
            raw_json.value = json.dumps(
                {
                    "details": _to_jsonable(details),
                    "thumbnails": _to_jsonable(thumbs),
                },
                ensure_ascii=False,
                indent=2,
            )
            status.value = f"{details.max_page} 页，{len(thumbs.thumbnails)} 个缩略图"
            log_debug("detail", f"load done {comic.id} thumbs={len(thumbs.thumbnails)}")
        except Exception as ex:
            status.value = f"错误: {ex}"
            log_exception("detail", f"load failed {comic.id}: {ex}")
        finally:
            page.update()

    threading.Thread(target=worker, daemon=True).start()

    return ft.Column(
        controls=[
            ft.Row(
                [
                    ft.Button("返回", icon=ft.Icons.ARROW_BACK, on_click=lambda e: on_back()),
                    ft.Text("画廊详情", size=18, weight=ft.FontWeight.W_500),
                ],
                spacing=12,
            ),
            ft.Divider(),
            ft.Row([cover_box, meta], spacing=24, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Text("标签", size=18, weight=ft.FontWeight.BOLD),
            tags_wrap,
            ft.Text("缩略图", size=18, weight=ft.FontWeight.BOLD),
            thumbs_grid,
            ft.Text("原始详情 JSON", size=18, weight=ft.FontWeight.BOLD),
            ft.Container(
                content=ft.Column([raw_json], scroll=ft.ScrollMode.AUTO),
                height=420,
                border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=8,
                padding=16,
            ),
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
