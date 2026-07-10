import base64
import time

import flet as ft

from app.debug_log import log_debug, log_exception, log_image_served
from app.image_fetcher import image_fetcher
from app.storage import should_load_images
from app.ui_update import request_update


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


class _AsyncImage(ft.Container):
    """挂载后才启动加载，卸载后丢弃后台结果。"""

    def __init__(
        self,
        page: ft.Page,
        url: str,
        *,
        width: float | int | None,
        height: float | int | None,
        expand: bool | int | None,
        fit: ft.BoxFit,
        cache_width: int | None,
        cache_height: int | None,
        border_radius: int | float | ft.BorderRadius | None,
        anti_alias: bool,
        fade_in_duration_ms: int,
    ) -> None:
        super().__init__(
            content=image_placeholder(width, height, loading=True),
            width=width,
            height=height,
            expand=expand,
        )
        self._page = page
        self._url = url
        self._fit = fit
        self._cache_width = cache_width
        self._cache_height = cache_height
        self._border_radius = border_radius
        self._anti_alias = anti_alias
        self._fade_in_duration_ms = max(0, int(fade_in_duration_ms))
        self._mounted = False
        self._loading = False
        self._loaded = False
        self._load_token = 0
        self._content_generation = getattr(page, "fletviewer_content_generation", None)

    def did_mount(self) -> None:
        self._mounted = True
        self._content_generation = getattr(self._page, "fletviewer_content_generation", None)
        if self._loaded or self._loading:
            return
        self._loading = True
        token = self._load_token
        try:
            self._page.run_thread(lambda: self._load(token))
        except Exception as ex:
            self._loading = False
            log_exception("async_image", f"start failed url={self._url}: {ex}")

    def will_unmount(self) -> None:
        self._mounted = False
        self._loading = False
        self._load_token += 1

    def _is_active(self, token: int) -> bool:
        current_generation = getattr(self._page, "fletviewer_content_generation", None)
        generation_matches = self._content_generation is None or current_generation == self._content_generation
        return self._mounted and token == self._load_token and generation_matches

    def _load(self, token: int) -> None:
        started_at = time.perf_counter()
        try:
            if not self._is_active(token):
                return
            result = image_fetcher.fetch(self._url)
            if not self._is_active(token):
                return
            self.content = ft.Image(
                src=image_src_for_page(self._page, result.data, result.mime),
                width=self.width,
                height=self.height,
                expand=self.expand,
                fit=self._fit,
                cache_width=self._cache_width,
                cache_height=self._cache_height,
                border_radius=self._border_radius,
                anti_alias=self._anti_alias,
                fade_in_animation=(
                    ft.Animation(
                        duration=ft.Duration(milliseconds=self._fade_in_duration_ms),
                        curve=ft.AnimationCurve.EASE_OUT,
                    )
                    if self._fade_in_duration_ms
                    else None
                ),
                error_content=image_placeholder(),
            )
            self._loaded = True
            source = "缓存命中💾" if result.from_cache else "网络抓取🌐"
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            log_image_served(source, elapsed_ms, self._url, len(result.data))
        except Exception as ex:
            if not self._is_active(token):
                return
            self.content = ft.Container(
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                alignment=ft.Alignment(0, 0),
                content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=ft.Colors.ON_SURFACE_VARIANT),
            )
            log_exception("async_image", f"load failed url={self._url}: {ex}")
        self._loading = False
        if self._is_active(token):
            request_update(self._page)


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
    border_radius: int | float | ft.BorderRadius | None = None,
    anti_alias: bool = False,
    fade_in_duration_ms: int = 180,
) -> ft.Control:
    """创建异步图片控件：先显示占位，再通过 ImageFetcherService 获取图片。"""
    if not should_load_images():
        log_debug("async_image", f"disabled url={url}")
        return image_placeholder(width, height)
    if not url:
        log_debug("async_image", "empty url")
        return image_placeholder(width, height)
    return _AsyncImage(
        page,
        url,
        width=width,
        height=height,
        expand=expand,
        fit=fit,
        cache_width=cache_width,
        cache_height=cache_height,
        border_radius=border_radius,
        anti_alias=anti_alias,
        fade_in_duration_ms=fade_in_duration_ms,
    )
