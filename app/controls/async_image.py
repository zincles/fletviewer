import base64
import threading

import flet as ft

from app.debug_log import log_debug, log_exception
from app.image_fetcher import image_fetcher
from app.storage import should_load_images


def image_src_for_page(page: ft.Page, data: bytes, mime: str) -> bytes | str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"
    # Desktop can render raw bytes with lower overhead, but using one data URI
    # path keeps image behavior identical across desktop and web for now.
    # return data


def image_placeholder(width=None, height=None) -> ft.Container:
    return ft.Container(
        width=width,
        height=height,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        alignment=ft.Alignment(0, 0),
        content=ft.Icon(ft.Icons.IMAGE_OUTLINED, color=ft.Colors.ON_SURFACE_VARIANT),
    )


def async_image(
    page: ft.Page,
    url: str | None,
    *,
    width: float | int | None = None,
    height: float | int | None = None,
    fit: ft.BoxFit = ft.BoxFit.COVER,
    cache_width: int | None = None,
    cache_height: int | None = None,
) -> ft.Control:
    if not should_load_images():
        log_debug("async_image", f"disabled url={url}")
        return image_placeholder(width, height)

    box = ft.Container(content=image_placeholder(width, height), width=width, height=height)

    if not url:
        log_debug("async_image", "empty url")
        return box

    def worker():
        try:
            log_debug("async_image", f"load start url={url}")
            result = image_fetcher.fetch(url)
            box.content = ft.Image(
                src=image_src_for_page(page, result.data, result.mime),
                width=width,
                height=height,
                fit=fit,
                cache_width=cache_width,
                cache_height=cache_height,
                error_content=ft.Container(
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=ft.Colors.ON_SURFACE_VARIANT),
                ),
            )
            log_debug("async_image", f"load done url={url} bytes={len(result.data)} from_cache={result.from_cache}")
        except Exception as ex:
            log_exception("async_image", f"load failed url={url}: {ex}")
        finally:
            try:
                    box.update()
            except Exception:
                try:
                    page.update()
                except Exception:
                    pass

    threading.Thread(target=worker, daemon=True).start()
    return box
