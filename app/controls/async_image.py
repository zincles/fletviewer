import base64
import threading
import time

import flet as ft

from app.debug_log import log_debug, log_exception, log_image_served
from app.image_fetcher import image_fetcher
from app.storage import should_load_images
from app.ui_update import request_update


def _start_background_task(page: ft.Page, target, name: str) -> None:
    """优先走 page.run_thread；不可用时退回普通守护线程。"""
    connection = getattr(getattr(page, "session", None), "connection", None)
    loop = getattr(connection, "loop", None)
    if loop is not None:
        page.run_thread(target)
        return
    log_debug("async_image", f"fallback thread {name}")
    threading.Thread(target=target, name=f"async_image_{name}", daemon=True).start()


def image_src_for_page(page: ft.Page, data: bytes, mime: str) -> bytes | str:
    """把图片 bytes 转成 data URI，统一桌面/Web 的显示路径。"""
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"
    # Desktop can render raw bytes with lower overhead, but using one data URI
    # path keeps image behavior identical across desktop and web for now.
    # return data


def image_placeholder(width=None, height=None, *, loading: bool = False) -> ft.Container:
    """创建图片占位控件；loading=True 时显示转动圆环。"""
    return ft.Container(
        width=width,
        height=height,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        alignment=ft.Alignment(0, 0),
        content=ft.ProgressRing(width=28, height=28) if loading else ft.Icon(ft.Icons.IMAGE_OUTLINED, color=ft.Colors.ON_SURFACE_VARIANT),
    )


def _format_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def async_image(
    page: ft.Page,
    url: str | None,
    *,
    width: float | int | None = None,
    height: float | int | None = None,
    expand: bool | int | None = None,
    fit: ft.BoxFit = ft.BoxFit.COVER,
    cache_width: int | None = None,
    cache_height: int | None = None,
) -> ft.Control:
    """创建异步图片控件：先显示占位，再通过 ImageFetcherService 获取图片。"""
    if not should_load_images():
        log_debug("async_image", f"disabled url={url}")
        return image_placeholder(width, height)

    progress_bar = ft.ProgressBar(width=140, value=None)
    progress_text = ft.Text("等待中...", size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    loading_content = ft.Container(
        width=width,
        height=height,
        expand=expand,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        alignment=ft.Alignment(0, 0),
        content=ft.Column(
            [
                ft.ProgressRing(width=24, height=24),
                progress_bar,
                progress_text,
            ],
            spacing=8,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )
    box = ft.Container(content=loading_content, width=width, height=height, expand=expand)

    if not url:
        log_debug("async_image", "empty url")
        return box
    created_generation = getattr(page, "fletviewer_content_generation", None)
    progress_state = {"done": False, "started_at": time.perf_counter()}

    def is_stale() -> bool:
        current_generation = getattr(page, "fletviewer_content_generation", None)
        return created_generation is not None and current_generation != created_generation

    def worker():
        started_at = time.perf_counter()
        try:
            if is_stale():
                return
            result = image_fetcher.fetch(url)
            if is_stale():
                return
            box.content = ft.Image(
                src=image_src_for_page(page, result.data, result.mime),
                width=width,
                height=height,
                expand=expand,
                fit=fit,
                cache_width=cache_width,
                cache_height=cache_height,
                error_content=ft.Container(
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=ft.Colors.ON_SURFACE_VARIANT),
                ),
            )
            source = "缓存命中💾" if result.from_cache else "网络抓取🌐"
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            log_image_served(source, elapsed_ms, url, len(result.data))
        except Exception as ex:
            if is_stale():
                return
            log_exception("async_image", f"load failed url={url}: {ex}")
        finally:
            progress_state["done"] = True
            if not is_stale():
                request_update(page)

    def progress_worker():
        while not progress_state["done"] and not is_stale():
            try:
                snapshot = image_fetcher.snapshot()
                task = next((item for item in [*snapshot.active, *snapshot.queued] if item.url == url), None)
                if task is not None:
                    if task.status == "queued":
                        progress_text.value = "排队中..."
                        progress_bar.value = 0
                    elif task.bytes_total:
                        progress_bar.value = max(0, min(1, task.bytes_done / task.bytes_total))
                        progress_text.value = f"{_format_bytes(task.bytes_done)} / {_format_bytes(task.bytes_total)}"
                    elif task.bytes_done:
                        elapsed = max(0.0, time.perf_counter() - progress_state["started_at"])
                        progress_bar.value = min(0.92, 0.18 + elapsed * 0.08)
                        progress_text.value = _format_bytes(task.bytes_done)
                    else:
                        progress_text.value = "连接中..."
                        elapsed = max(0.0, time.perf_counter() - progress_state["started_at"])
                        progress_bar.value = min(0.82, 0.08 + elapsed * 0.06)
                else:
                    elapsed = max(0.0, time.perf_counter() - progress_state["started_at"])
                    progress_text.value = "等待线程..."
                    progress_bar.value = min(0.35, elapsed * 0.08)
                request_update(page)
            except Exception as ex:
                log_exception("async_image", f"progress update failed url={url}: {ex}")
            time.sleep(0.2)

    _start_background_task(page, progress_worker, "progress")
    _start_background_task(page, worker, "fetch")
    return box
