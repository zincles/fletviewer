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
from app.storage import ROOT_DIR, get_image_viewer_mode, should_load_images
from app.ui_update import request_update


@dataclass(slots=True)
class ImageViewerItem:
    url: str
    title: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


ResolveImageUrl = Callable[[ImageViewerItem, int], str]
VERTICAL_ESTIMATED_WIDTH = 900
VERTICAL_DEFAULT_RATIO = 0.7
VERTICAL_SPACING = 12
VERTICAL_WINDOW_PAGES = 2
VERTICAL_SCROLL_BUFFER = 1200


def _download_path(source_path: Path, title: str) -> Path:
    downloads_dir = ROOT_DIR / "Downloads"
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
) -> ft.Control:
    index = max(0, min(initial_index, len(items) - 1)) if items else 0
    state = {
        "index": index,
        "mode": get_image_viewer_mode(),
        "current_url": "",
        "current_path": None,
        "paged_generation": 0,
        "vertical_generation": 0,
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

    estimated_heights = [_estimated_height(item) for item in items]
    vertical_cards: list[ft.Container] = []
    vertical_loaded: set[int] = set()
    vertical_loading: set[int] = set()
    vertical_urls: dict[int, str] = {}
    vertical_paths: dict[int, Path] = {}

    offsets: list[int] = []
    total = 0
    for height in estimated_heights:
        offsets.append(total)
        total += height + VERTICAL_SPACING

    def current_item() -> ImageViewerItem:
        return items[state["index"]]

    def resolve_item_url(item: ImageViewerItem, idx: int) -> str:
        with Timer("viewer", f"resolve image index={idx}"):
            return resolve_image_url(item, idx) if resolve_image_url else item.url

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

    def load_current():
        state["paged_generation"] += 1
        generation = state["paged_generation"]
        if not items:
            title.value = "没有图片"
            status.value = "空列表"
            update_nav()
            page.update()
            return

        item = current_item()
        pos = f"{state['index'] + 1}/{len(items)}"
        title.value = item.title or pos
        if not should_load_images():
            status.value = "图像加载已关闭"
            image_box.content = image_placeholder()
            state["current_url"] = ""
            state["current_path"] = None
            update_nav()
            page.update()
            return

        status.value = f"加载中... {pos}"
        image_box.content = image_placeholder(loading=True)
        state["current_url"] = ""
        state["current_path"] = None
        update_nav()
        page.update()

        def worker():
            try:
                url = resolve_item_url(item, state["index"])
                log_debug("viewer", f"load image index={state['index']} url={url}")
                result = image_fetcher.fetch(url)
                if generation != state["paged_generation"] or state["mode"] != "paged":
                    return
                state["current_url"] = url
                state["current_path"] = result.path
                image_box.content = ft.Image(
                    src=image_src_for_page(page, result.data, result.mime),
                    fit=ft.BoxFit.CONTAIN,
                    expand=True,
                )
                status.value = f"{pos}  {len(result.data)} bytes  {'cache' if result.from_cache else 'network'}"
                log_debug("viewer", f"image loaded index={state['index']} bytes={len(result.data)}")
            except Exception as ex:
                status.value = f"错误: {ex}"
                log_exception("viewer", f"image load failed index={state['index']}: {ex}")
            finally:
                request_update(page)

        page.run_thread(worker)

    def move(delta: int):
        next_index = state["index"] + delta
        if 0 <= next_index < len(items):
            state["index"] = next_index
            if state["mode"] == "paged":
                load_current()
            else:
                render_vertical(scroll_to_index=next_index)

    def download_current(e):
        path = state.get("current_path")
        if not path:
            status.value = "当前图片尚未加载完成"
            page.update()
            return
        try:
            item = current_item()
            target = _download_path(Path(path), item.title or f"image_{state['index'] + 1}")
            shutil.copy2(path, target)
            status.value = f"已下载到 {target}"
            log_debug("viewer", f"downloaded {path} -> {target}")
        except Exception as ex:
            status.value = f"下载失败: {ex}"
            log_exception("viewer", f"download failed: {ex}")
        page.update()

    def show_detail(e):
        item = current_item() if items else ImageViewerItem(url="")
        detail_text = ft.Text(
            f"url: {state.get('current_url') or item.url}\ncache_path: {state.get('current_path')}\nmetadata: {item.detail}",
            selectable=True,
        )
        dialog = ft.AlertDialog(
            title=ft.Text("图片详情"),
            content=ft.Container(content=detail_text, width=700, height=360),
        )
        dialog.actions = [ft.Button("关闭", on_click=lambda ev: page.close(dialog))]
        page.open(dialog)

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
        item = current_item()
        title.value = item.title or f"{state['index'] + 1}/{len(items)}"
        state["current_url"] = vertical_urls.get(state["index"], item.url)
        state["current_path"] = vertical_paths.get(state["index"])
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
                url = resolve_item_url(item, idx)
                log_debug("viewer", f"vertical load image index={idx} url={url}")
                result = image_fetcher.fetch(url)
                if generation != state["vertical_generation"] or state["mode"] != "vertical":
                    return
                vertical_urls[idx] = url
                vertical_paths[idx] = result.path
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
                    state["current_url"] = url
                    state["current_path"] = result.path
                status.value = f"垂直浏览 {state['index'] + 1}/{len(items)}，窗口内加载 {len(vertical_loaded)} 张"
                log_debug("viewer", f"vertical image loaded index={idx} bytes={len(result.data)}")
            except Exception as ex:
                vertical_cards[idx].content = ft.Text(f"#{idx + 1} 加载失败: {ex}", color=ft.Colors.ERROR)
                log_exception("viewer", f"vertical image load failed index={idx}: {ex}")
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
                reset_vertical_card(idx)
        for idx in sorted(keep):
            load_vertical_index(idx)
        status.value = f"垂直浏览 {state['index'] + 1}/{len(items)}，窗口 {min(keep) + 1 if keep else 0}-{max(keep) + 1 if keep else 0}"
        page.update()

    def on_vertical_scroll(e):
        update_vertical_window(float(e.pixels or 0), float(e.viewport_dimension or 700))

    def render_paged():
        state["mode"] = "paged"
        state["vertical_generation"] += 1
        update_mode_button()
        body.content = ft.Row(
            [prev_btn, image_box, next_btn],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        load_current()

    def render_vertical(scroll_to_index: int | None = None):
        state["mode"] = "vertical"
        state["paged_generation"] += 1
        state["vertical_generation"] += 1
        update_mode_button()
        if not items:
            title.value = "没有图片"
            status.value = "空列表"
            body.content = ft.Container(content=image_placeholder(), expand=True, alignment=ft.Alignment(0, 0))
            page.update()
            return
        if not should_load_images():
            title.value = current_item().title or f"{state['index'] + 1}/{len(items)}"
            status.value = "图像加载已关闭"
            body.content = ft.Container(content=image_placeholder(), expand=True, alignment=ft.Alignment(0, 0))
            page.update()
            return

        vertical_loaded.clear()
        vertical_loading.clear()
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
        body.content = list_view
        update_nav()
        page.update()

        target = state["index"] if scroll_to_index is None else max(0, min(scroll_to_index, len(items) - 1))
        state["index"] = target
        title.value = current_item().title or f"{target + 1}/{len(items)}"
        update_vertical_window(float(offsets[target] if offsets else 0), 900)

        def scroll_worker():
            time.sleep(0.1)
            try:
                list_view.scroll_to(offset=offsets[target] if offsets else 0, duration=0)
            except Exception as ex:
                log_exception("viewer", f"vertical scroll_to failed index={target}: {ex}")

        page.run_thread(scroll_worker)

    def toggle_mode(e):
        if state["mode"] == "paged":
            render_vertical(scroll_to_index=state["index"])
        else:
            render_paged()

    prev_btn.on_click = lambda e: move(-1)
    next_btn.on_click = lambda e: move(1)
    download_btn.on_click = download_current
    detail_btn.on_click = show_detail
    mode_btn.on_click = toggle_mode

    if state["mode"] == "vertical":
        render_vertical(scroll_to_index=index)
    else:
        render_paged()

    return ft.Column(
        controls=[
            ft.Row(
                [
                    ft.Button("返回", icon=ft.Icons.ARROW_BACK, on_click=lambda e: on_back()),
                    title,
                    ft.Row([mode_btn, detail_btn, download_btn], spacing=4),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            status,
            body,
        ],
        spacing=8,
        expand=True,
    )
