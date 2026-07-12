import base64
import time
from concurrent.futures import Future

import flet as ft

from app.debug_log import log_debug, log_exception, log_image_served
from app.image_fetcher import image_load_coordinator
from app.image_progress import image_progress_pump
from app.storage import should_load_images
from app.ui_update import request_update
from core.image.fetcher import ImageFetchCancelled, ImageFetchResult, ImageLoadSubscription


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
        self._subscription: ImageLoadSubscription | None = None
        self._progress_ring: ft.ProgressRing | None = None
        self._load_started_at = 0.0

    def _loading_content(self) -> ft.Control:
        self._progress_ring = ft.ProgressRing(width=42, height=42)
        return ft.Container(
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            alignment=ft.Alignment(0, 0),
            content=ft.Stack(
                [
                    self._progress_ring,
                    ft.IconButton(ft.Icons.CLOSE, tooltip="取消图像加载", icon_size=18, on_click=self._cancel_load),
                ],
                alignment=ft.Alignment(0, 0),
            ),
        )

    def _action_content(self, icon, tooltip: str, action) -> ft.Control:
        return ft.Container(
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            alignment=ft.Alignment(0, 0),
            content=ft.IconButton(icon, tooltip=tooltip, on_click=action),
        )

    def did_mount(self) -> None:
        self._mounted = True
        self._content_generation = getattr(self._page, "fletviewer_content_generation", None)
        if self._loaded or self._loading:
            return
        self._start_load()

    def _start_load(self, e=None) -> None:
        if not self._mounted:
            return
        image_progress_pump(self._page).unregister(self)
        old_subscription = self._subscription
        if old_subscription is not None:
            old_subscription.unsubscribe()
        self._load_token += 1
        self._loading = True
        self._load_started_at = time.perf_counter()
        self.content = self._loading_content()
        token = self._load_token
        subscription: ImageLoadSubscription | None = None
        try:
            subscription = image_load_coordinator.subscribe(self._url, kind="thumbnail")
            self._subscription = subscription
            image_progress_pump(self._page).register(self)
            subscription.future.add_done_callback(
                lambda completed, current=subscription: self._schedule_apply(token, current, completed)
            )
        except Exception as ex:
            if subscription is not None:
                subscription.unsubscribe()
            self._loading = False
            self._subscription = None
            self._progress_ring = None
            image_progress_pump(self._page).unregister(self)
            log_exception("异步图像", f"启动失败 URL={self._url}：{ex}")
            self.content = self._action_content(ft.Icons.REFRESH, "重试图像加载", self._start_load)
        request_update(self._page)

    def _cancel_load(self, e=None) -> None:
        if not self._loading:
            return
        self._load_token += 1
        subscription = self._subscription
        self._subscription = None
        self._loading = False
        if subscription is not None:
            subscription.cancel()
        image_progress_pump(self._page).unregister(self)
        self._progress_ring = None
        self.content = self._action_content(ft.Icons.DOWNLOAD_OUTLINED, "加载图像", self._start_load)
        request_update(self._page)

    def will_unmount(self) -> None:
        self._mounted = False
        self._loading = False
        self._load_token += 1
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.unsubscribe()
        image_progress_pump(self._page).unregister(self)

    def _is_active(self, token: int) -> bool:
        current_generation = getattr(self._page, "fletviewer_content_generation", None)
        generation_matches = self._content_generation is None or current_generation == self._content_generation
        return self._mounted and token == self._load_token and generation_matches

    def _can_schedule(self) -> bool:
        session = getattr(self._page, "session", None)
        return session is not None and getattr(session, "connection", None) is not None

    def _schedule_apply(
        self,
        token: int,
        subscription: ImageLoadSubscription | Future[ImageFetchResult],
        future: Future[ImageFetchResult] | None = None,
    ) -> None:
        if future is None:
            future = subscription
            subscription = getattr(self, "_subscription", None)
        if not self._is_active(token) or not self._can_schedule():
            self._clear_if_current(subscription)
            return
        if subscription is None:
            return
        try:
            self._page.run_thread(lambda: self._apply_result(token, subscription, future))
        except AttributeError as ex:
            # The Flet session can disconnect between the check and run_thread().
            if not self._can_schedule():
                self._clear_if_current(subscription)
                return
            self._clear_if_current(subscription)
            log_exception("异步图像", f"调度结果应用失败 URL={self._url}：{ex}")
        except Exception as ex:
            self._clear_if_current(subscription)
            log_exception("异步图像", f"调度结果应用失败 URL={self._url}：{ex}")

    def _apply_result(self, token: int, subscription: ImageLoadSubscription, future: Future[ImageFetchResult]) -> None:
        try:
            if not self._is_active(token) or self._subscription is not subscription:
                self._clear_if_current(subscription)
                return
            result = future.result()
        except ImageFetchCancelled:
            if self._is_active(token) and self._subscription is subscription:
                self.content = self._action_content(ft.Icons.DOWNLOAD_OUTLINED, "加载图像", self._start_load)
        except Exception:
            if self._is_active(token) and self._subscription is subscription:
                self.content = self._action_content(ft.Icons.REFRESH, "重试图像加载", self._start_load)
        else:
            if not self._is_active(token) or self._subscription is not subscription:
                self._clear_if_current(subscription)
                return
            try:
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
            except Exception as ex:
                self.content = self._action_content(ft.Icons.REFRESH, "重试图像加载", self._start_load)
                log_exception("异步图像", f"构建图像控件失败 URL={self._url}：{ex}")
            else:
                self._loaded = True
                source = "缓存命中💾" if result.from_cache else "网络抓取🌐"
                elapsed_ms = (time.perf_counter() - self._load_started_at) * 1000
                log_image_served(source, elapsed_ms, self._url, len(result.data))
        was_current = self._subscription is subscription
        self._clear_if_current(subscription)
        if was_current and self._is_active(token):
            request_update(self._page)

    def _clear_if_current(self, subscription) -> None:
        if getattr(self, "_subscription", None) is not subscription:
            return
        self._loading = False
        self._subscription = None
        self._progress_ring = None
        image_progress_pump(self._page).unregister(self)

    def _refresh_progress(self) -> bool:
        subscription = self._subscription
        ring = self._progress_ring
        if not self._mounted or not self._loading or subscription is None or ring is None:
            return False
        state = subscription.progress()
        value = min(1.0, state.bytes_done / state.bytes_total) if state is not None and state.bytes_total > 0 else None
        if ring.value == value:
            return False
        ring.value = value
        return True


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
        log_debug("异步图像", f"图像加载已禁用 URL={url}")
        return image_placeholder(width, height)
    if not url:
        log_debug("异步图像", "URL 为空")
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
