import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any

import flet as ft

from app.controls.async_image import image_placeholder, image_src_for_page
from app.debug_log import Timer, log_debug, log_exception
from app.image_fetcher import image_fetcher
from app.storage import get_image_viewer_mode, get_storage_layout, should_load_images
from app.toast import show_error_toast
from app.ui_update import request_update


@dataclass(slots=True)
class ImageViewerItem:
    """通用阅读器条目；url 可以是直接图片 URL，也可以是待解析的页面 URL。"""

    url: str
    title: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


ResolveImageUrl = Callable[[ImageViewerItem, int], str]


@dataclass(slots=True)
class ViewerImageResult:
    data: bytes
    mime: str
    url: str = ""
    path: Path | None = None
    from_cache: bool = False


LoadImage = Callable[[ImageViewerItem, int], ViewerImageResult]
VERTICAL_ESTIMATED_WIDTH = 900
VERTICAL_DEFAULT_RATIO = 0.7
VERTICAL_SPACING = 12
VERTICAL_WINDOW_PAGES = 2
VERTICAL_SCROLL_BUFFER = 1200


def _suffix_for_mime(mime: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime.split(";", 1)[0].lower(), ".img")


def _download_path(source_path: Path, title: str) -> Path:
    """根据图片标题生成 Downloads 下不冲突的保存路径。"""
    downloads_dir = get_storage_layout().paths.downloads
    downloads_dir.mkdir(parents=True, exist_ok=True)
    safe_title = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in title).strip("_")
    stem = safe_title[:80] or source_path.stem
    target = downloads_dir / f"{stem}{source_path.suffix}"
    counter = 1
    while target.exists():
        target = downloads_dir / f"{stem}_{counter}{source_path.suffix}"
        counter += 1
    return target


def _estimated_height(item: ImageViewerItem) -> int:
    """根据缩略图比例估算垂直模式占位高度。"""
    ratio = item.detail.get("thumbnail_aspect_ratio") or 0
    if not ratio:
        width = item.detail.get("thumbnail_width") or 0
        height = item.detail.get("thumbnail_height") or 0
        ratio = width / height if width and height else 0
    ratio = float(ratio or VERTICAL_DEFAULT_RATIO)
    return max(320, min(1800, int(VERTICAL_ESTIMATED_WIDTH / ratio)))


def create_view(
    page: ft.Page,
    items: list[ImageViewerItem],
    initial_index: int,
    on_back,
    *,
    resolve_image_url: ResolveImageUrl | None = None,
    load_image: LoadImage | None = None,
) -> ft.Control:
    """创建通用图片阅读器，支持单页和有限窗口垂直浏览。"""
    index = max(0, min(initial_index, len(items) - 1)) if items else 0
    state = {
        "index": index,
        "mode": get_image_viewer_mode(),
        "current_url": "",
        "current_path": None,
        "current_data": None,
        "current_mime": "",
        "paged_generation": 0,
        "vertical_generation": 0,
        "overlay_generation": 0,
        "last_overlay_activity": 0.0,
    }
    if state["mode"] not in ("paged", "vertical"):
        state["mode"] = "paged"

    title = ft.Text("", size=18, weight=ft.FontWeight.W_500, selectable=True)
    status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    body = ft.Container(expand=True)
    image_box = ft.Container(content=image_placeholder(), expand=True, alignment=ft.Alignment(0, 0))
    prev_btn = ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, tooltip="上一张")
    next_btn = ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, tooltip="下一张")
    download_btn = ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="下载当前图片")
    detail_btn = ft.IconButton(icon=ft.Icons.INFO_OUTLINE, tooltip="详情")
    mode_btn = ft.IconButton(icon=ft.Icons.VIEW_STREAM, tooltip="切换为垂直连续浏览")
    back_overlay_btn = ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="返回")
    page_counter = ft.Text("", size=14, weight=ft.FontWeight.W_600, color=ft.Colors.WHITE)
    for button in (prev_btn, next_btn, download_btn, detail_btn, mode_btn, back_overlay_btn):
        button.icon_color = ft.Colors.WHITE
    status.color = ft.Colors.WHITE
    top_overlay_container = ft.Container(
        content=ft.Stack(
            controls=[
                ft.Container(content=page_counter, left=0, right=0, top=0, bottom=0, alignment=ft.Alignment(0, 0), ignore_interactions=True),
                ft.Container(content=back_overlay_btn, left=0, top=0, bottom=0, alignment=ft.Alignment(-1, 0)),
                ft.Container(content=ft.Row([mode_btn, detail_btn, download_btn], spacing=4), right=0, top=0, bottom=0, alignment=ft.Alignment(1, 0)),
            ],
            expand=True,
        ),
        top=12,
        left=12,
        right=12,
        height=48,
        padding=ft.Padding(4, 2, 4, 2),
        border_radius=999,
        bgcolor=ft.Colors.with_opacity(0.48, ft.Colors.BLACK),
        animate_opacity=180,
        animate_offset=180,
    )

    estimated_heights = [_estimated_height(item) for item in items]
    vertical_cards: list[ft.Container] = []
    vertical_loaded: set[int] = set()
    vertical_loading: set[int] = set()
    vertical_urls: dict[int, str] = {}
    vertical_paths: dict[int, Path | None] = {}
    vertical_data: dict[int, tuple[bytes, str]] = {}

    offsets: list[int] = []
    total = 0
    for height in estimated_heights:
        offsets.append(total)
        total += height + VERTICAL_SPACING

    def current_item() -> ImageViewerItem:
        return items[state["index"]]

    def resolve_item_url(item: ImageViewerItem, idx: int) -> str:
        with Timer("图像查看器", f"解析图像 索引={idx}"):
            return resolve_image_url(item, idx) if resolve_image_url else item.url

    def fetch_item_image(item: ImageViewerItem, idx: int):
        if load_image is not None:
            return load_image(item, idx)
        provider = item.detail.get("provider")
        gid = item.detail.get("gid")
        token = item.detail.get("token")
        page_idx = item.detail.get("page_idx")
        if provider and gid and token and page_idx is not None and resolve_image_url:
            return image_fetcher.fetch_gallery_page(
                provider=str(provider),
                gid=str(gid),
                token=str(token),
                page_idx=int(page_idx),
                kind=str(item.detail.get("kind") or "original"),
                resolve_url=lambda: resolve_item_url(item, idx),
            )
        url = resolve_item_url(item, idx)
        return image_fetcher.fetch(url)

    def update_nav():
        prev_btn.disabled = state["index"] <= 0
        next_btn.disabled = state["index"] >= len(items) - 1

    def update_mode_button():
        if state["mode"] == "paged":
            mode_btn.icon = ft.Icons.VIEW_STREAM
            mode_btn.tooltip = "切换为垂直连续浏览"
        else:
            mode_btn.icon = ft.Icons.VIEW_CAROUSEL
            mode_btn.tooltip = "切换为单页左右切换"

    def schedule_overlay_hide():
        state["overlay_generation"] += 1
        generation = state["overlay_generation"]

        def worker():
            time.sleep(3)
            if generation != state["overlay_generation"]:
                return
            top_overlay_container.opacity = 0
            top_overlay_container.offset = (0, -1.4)
            top_overlay_container.ignore_interactions = True
            request_update(page)

        page.run_thread(worker)

    def show_overlay(force: bool = False):
        now = time.monotonic()
        if not force and now - float(state.get("last_overlay_activity") or 0) < 0.2:
            return
        state["last_overlay_activity"] = now
        top_overlay_container.opacity = 1
        top_overlay_container.offset = (0, 0)
        top_overlay_container.ignore_interactions = False
        schedule_overlay_hide()

    def load_current():
        state["paged_generation"] += 1
        generation = state["paged_generation"]
        if not items:
            title.value = "没有图片"
            page_counter.value = "0/0"
            status.value = "空列表"
            update_nav()
            page.update()
            return

        item = current_item()
        pos = f"{state['index'] + 1}/{len(items)}"
        page_counter.value = pos
        title.value = item.title or pos
        if not should_load_images():
            status.value = "图像加载已关闭"
            image_box.content = image_placeholder()
            state["current_url"] = ""
            state["current_path"] = None
            state["current_data"] = None
            state["current_mime"] = ""
            update_nav()
            page.update()
            return

        status.value = f"加载中... {pos}"
        image_box.content = image_placeholder(loading=True)
        state["current_url"] = ""
        state["current_path"] = None
        state["current_data"] = None
        state["current_mime"] = ""
        update_nav()
        page.update()

        def worker():
            try:
                log_debug("图像查看器", f"加载图像 索引={state['index']}")
                with Timer("图像查看器", f"获取图像 索引={state['index']}"):
                    result = fetch_item_image(item, state["index"])
                if generation != state["paged_generation"] or state["mode"] != "paged":
                    return
                state["current_url"] = result.url or item.url
                state["current_path"] = result.path
                state["current_data"] = result.data
                state["current_mime"] = result.mime
                with Timer("图像查看器", f"构建图像控件 索引={state['index']}"):
                    image_box.content = ft.Image(
                        src=image_src_for_page(page, result.data, result.mime),
                        fit=ft.BoxFit.CONTAIN,
                        expand=True,
                    )
                status.value = f"{pos}  {len(result.data)} bytes  {'cache' if result.from_cache else 'network'}"
                log_debug("图像查看器", f"图像加载完成 索引={state['index']} 字节数={len(result.data)}")
            except Exception as ex:
                status.value = f"错误: {ex}"
                show_error_toast(page, "图片加载失败", ex)
                log_exception("图像查看器", f"图像加载失败 索引={state['index']}：{ex}")
            finally:
                request_update(page)

        page.run_thread(worker)

    def move(delta: int):
        show_overlay()
        next_index = state["index"] + delta
        if 0 <= next_index < len(items):
            state["index"] = next_index
            if state["mode"] == "paged":
                load_current()
            else:
                render_vertical(scroll_to_index=next_index)

    def download_current(e):
        show_overlay()
        path = state.get("current_path")
        data = state.get("current_data")
        if not path and not data:
            status.value = "当前图片尚未加载完成"
            page.update()
            return
        try:
            item = current_item()
            suffix = Path(path).suffix if path else _suffix_for_mime(str(state.get("current_mime") or ""))
            source = Path(path) if path else Path(f"image{suffix}")
            target = _download_path(source, item.title or f"image_{state['index'] + 1}")
            if path:
                shutil.copy2(path, target)
            else:
                target.write_bytes(data)
            status.value = f"已下载到 {target}"
            log_debug("图像查看器", f"下载完成 {path} -> {target}")
        except Exception as ex:
            status.value = f"下载失败: {ex}"
            show_error_toast(page, "图片下载失败", ex)
            log_exception("图像查看器", f"下载失败：{ex}")
        page.update()

    def show_detail(e):
        show_overlay()
        item = current_item() if items else ImageViewerItem(url="")
        detail_text = ft.Text(
            f"url: {state.get('current_url') or item.url}\ncache_path: {state.get('current_path')}\nmetadata: {item.detail}",
            selectable=True,
        )
        dialog = ft.AlertDialog(
            title=ft.Text("图片详情"),
            content=ft.Container(content=detail_text, width=700, height=360),
        )
        dialog.actions = [ft.Button("关闭", on_click=lambda ev: page.pop_dialog())]
        dialog.open = True
        page.show_dialog(dialog)

    def vertical_frame(idx: int, content: ft.Control) -> ft.Control:
        return ft.Container(
            content=content,
            width=float("inf"),
            height=estimated_heights[idx],
            alignment=ft.Alignment(0, 0),
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

    def vertical_placeholder(idx: int) -> ft.Control:
        return ft.Column(
            controls=[
                vertical_frame(idx, image_placeholder(width=float("inf"), height=estimated_heights[idx], loading=True)),
                ft.Text(f"#{idx + 1}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def reset_vertical_card(idx: int):
        if 0 <= idx < len(vertical_cards):
            vertical_cards[idx].content = vertical_placeholder(idx)

    def set_current_from_scroll(pixels: float):
        if not offsets:
            return
        best = 0
        for idx, top in enumerate(offsets):
            if top <= pixels:
                best = idx
            else:
                break
        state["index"] = max(0, min(best, len(items) - 1))
        page_counter.value = f"{state['index'] + 1}/{len(items)}"
        item = current_item()
        title.value = item.title or f"{state['index'] + 1}/{len(items)}"
        state["current_url"] = vertical_urls.get(state["index"], item.url)
        state["current_path"] = vertical_paths.get(state["index"])
        current_data = vertical_data.get(state["index"])
        state["current_data"] = current_data[0] if current_data else None
        state["current_mime"] = current_data[1] if current_data else ""
        update_nav()

    def vertical_visible_indexes(pixels: float, viewport: float) -> set[int]:
        if not items:
            return set()
        start = max(0, pixels - VERTICAL_SCROLL_BUFFER)
        end = pixels + max(viewport, 600) + VERTICAL_SCROLL_BUFFER
        visible = set()
        for idx, top in enumerate(offsets):
            bottom = top + estimated_heights[idx]
            if bottom < start:
                continue
            if top > end:
                break
            visible.add(idx)
        current = state["index"]
        visible.update(range(max(0, current - VERTICAL_WINDOW_PAGES), min(len(items), current + VERTICAL_WINDOW_PAGES + 1)))
        return visible

    def load_vertical_index(idx: int):
        if idx in vertical_loaded or idx in vertical_loading or not should_load_images():
            return
        vertical_loading.add(idx)
        vertical_cards[idx].content = ft.Column(
            controls=[
                vertical_frame(idx, image_placeholder(width=float("inf"), height=estimated_heights[idx])),
                ft.Text(f"加载中 #{idx + 1}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        generation = state["vertical_generation"]
        item = items[idx]

        def worker():
            try:
                log_debug("图像查看器", f"垂直模式加载图像 索引={idx}")
                result = fetch_item_image(item, idx)
                if generation != state["vertical_generation"] or state["mode"] != "vertical":
                    return
                vertical_urls[idx] = result.url or item.url
                vertical_paths[idx] = result.path
                vertical_data[idx] = (result.data, result.mime)
                vertical_loaded.add(idx)
                vertical_cards[idx].content = ft.Column(
                    controls=[
                        vertical_frame(
                            idx,
                            ft.Image(
                                src=image_src_for_page(page, result.data, result.mime),
                                width=float("inf"),
                                height=estimated_heights[idx],
                                fit=ft.BoxFit.FIT_WIDTH,
                            ),
                        ),
                        ft.Text(f"#{idx + 1}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                )
                if idx == state["index"]:
                    state["current_url"] = result.url or item.url
                    state["current_path"] = result.path
                    state["current_data"] = result.data
                    state["current_mime"] = result.mime
                status.value = f"垂直浏览 {state['index'] + 1}/{len(items)}，窗口内加载 {len(vertical_loaded)} 张"
                log_debug("图像查看器", f"垂直模式图像加载完成 索引={idx} 字节数={len(result.data)}")
            except Exception as ex:
                vertical_cards[idx].content = ft.Text(f"#{idx + 1} 加载失败: {ex}", color=ft.Colors.ERROR)
                log_exception("图像查看器", f"垂直模式图像加载失败 索引={idx}：{ex}")
            finally:
                vertical_loading.discard(idx)
                request_update(page)

        page.run_thread(worker)

    def update_vertical_window(pixels: float, viewport: float):
        set_current_from_scroll(pixels)
        keep = vertical_visible_indexes(pixels, viewport)
        for idx in list(vertical_loaded):
            if idx not in keep:
                vertical_loaded.discard(idx)
                vertical_data.pop(idx, None)
                vertical_paths.pop(idx, None)
                vertical_urls.pop(idx, None)
                reset_vertical_card(idx)
        for idx in sorted(keep):
            load_vertical_index(idx)
        status.value = f"垂直浏览 {state['index'] + 1}/{len(items)}，窗口 {min(keep) + 1 if keep else 0}-{max(keep) + 1 if keep else 0}"
        page.update()

    def on_vertical_scroll(e):
        show_overlay()
        update_vertical_window(float(e.pixels or 0), float(e.viewport_dimension or 700))

    def interactive_overlay_stack(controls: list[ft.Control]) -> ft.Control:
        """包装阅读器 Stack，捕获 PC 鼠标移动来保持顶部栏显示。"""
        return ft.Container(
            content=ft.Stack(controls=controls, expand=True),
            on_hover=lambda e: show_overlay(),
            expand=True,
        )

    def render_paged():
        state["mode"] = "paged"
        state["vertical_generation"] += 1
        vertical_loaded.clear()
        vertical_loading.clear()
        vertical_data.clear()
        vertical_paths.clear()
        vertical_urls.clear()
        update_mode_button()
        show_overlay(force=True)
        body.content = interactive_overlay_stack([
                image_box,
                ft.Container(
                    content=prev_btn,
                    width=72,
                    left=12,
                    top=0,
                    bottom=0,
                    alignment=ft.Alignment(0, 0),
                ),
                ft.Container(
                    content=next_btn,
                    width=72,
                    right=12,
                    top=0,
                    bottom=0,
                    alignment=ft.Alignment(0, 0),
                ),
                top_overlay_container,
        ])
        load_current()

    def render_vertical(scroll_to_index: int | None = None):
        state["mode"] = "vertical"
        state["paged_generation"] += 1
        state["vertical_generation"] += 1
        update_mode_button()
        show_overlay(force=True)
        if not items:
            title.value = "没有图片"
            page_counter.value = "0/0"
            status.value = "空列表"
            body.content = interactive_overlay_stack([
                    ft.Container(content=image_placeholder(), expand=True, alignment=ft.Alignment(0, 0)),
                    top_overlay_container,
            ])
            page.update()
            return
        if not should_load_images():
            title.value = current_item().title or f"{state['index'] + 1}/{len(items)}"
            page_counter.value = f"{state['index'] + 1}/{len(items)}"
            status.value = "图像加载已关闭"
            body.content = interactive_overlay_stack([
                    ft.Container(content=image_placeholder(), expand=True, alignment=ft.Alignment(0, 0)),
                    top_overlay_container,
            ])
            page.update()
            return

        vertical_loaded.clear()
        vertical_loading.clear()
        vertical_data.clear()
        vertical_paths.clear()
        vertical_urls.clear()
        vertical_cards.clear()
        for idx in range(len(items)):
            vertical_cards.append(
                ft.Container(
                    content=vertical_placeholder(idx),
                    padding=ft.Padding(0, 0, 0, VERTICAL_SPACING),
                )
            )
        list_view = ft.ListView(
            controls=vertical_cards,
            spacing=0,
            expand=True,
            scroll=ft.ScrollMode.ALWAYS,
            cache_extent=VERTICAL_SCROLL_BUFFER,
            on_scroll=on_vertical_scroll,
        )
        body.content = interactive_overlay_stack([
                list_view,
                top_overlay_container,
        ])
        update_nav()
        page.update()

        target = state["index"] if scroll_to_index is None else max(0, min(scroll_to_index, len(items) - 1))
        state["index"] = target
        page_counter.value = f"{target + 1}/{len(items)}"
        title.value = current_item().title or f"{target + 1}/{len(items)}"
        update_vertical_window(float(offsets[target] if offsets else 0), 900)

        def scroll_worker():
            time.sleep(0.1)
            try:
                list_view.scroll_to(offset=offsets[target] if offsets else 0, duration=0)
            except Exception as ex:
                log_exception("图像查看器", f"垂直模式滚动定位失败 索引={target}：{ex}")

        page.run_thread(scroll_worker)

    def toggle_mode(e):
        show_overlay()
        if state["mode"] == "paged":
            render_vertical(scroll_to_index=state["index"])
        else:
            render_paged()

    prev_btn.on_click = lambda e: move(-1)
    next_btn.on_click = lambda e: move(1)
    back_overlay_btn.on_click = lambda e: (show_overlay(), on_back())
    download_btn.on_click = download_current
    detail_btn.on_click = show_detail
    mode_btn.on_click = toggle_mode

    if state["mode"] == "vertical":
        render_vertical(scroll_to_index=index)
    else:
        render_paged()

    return body
