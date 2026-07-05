from __future__ import annotations

import threading
import time
from io import BytesIO
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs

import requests
from PIL import Image

from app.browser_session import browser_session
from app.debug_log import Timer, log_debug
from app.image_cache import (
    cached_path_for_url,
    drop_cached_filename,
    ensure_image_cache_dirs,
    filename_for_url,
    get_cached_filename,
    get_cached_path,
    path_for_filename,
    put_cached_filename,
    repair_stale_entry,
)


@dataclass(slots=True)
class ImageFetchResult:
    """图片 fetch 的结果，包含本地缓存路径、图片 bytes 和 MIME。"""

    url: str
    path: Path
    data: bytes
    mime: str
    from_cache: bool


class ImageFetcherService:
    """Provider 无关的图片获取服务，负责磁盘缓存、去重和 EH sprite 裁剪。"""

    def __init__(self, max_workers: int = 6):
        """初始化图片 fetch 线程池和 in-flight 去重表。"""
        ensure_image_cache_dirs()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="image-fetch")
        self._lock = threading.Lock()
        self._in_flight: dict[str, Future] = {}

    def fetch(self, url: str) -> ImageFetchResult:
        """获取图片；优先读缓存，未命中时请求远端并写入缓存。"""
        normalized = url.strip()
        log_debug("image", f"request {normalized}")
        with self._lock:
            future = self._in_flight.get(normalized)
            if future is None:
                log_debug("image", f"submit fetch {normalized}")
                future = self._executor.submit(self._fetch_impl, normalized)
                self._in_flight[normalized] = future
            else:
                log_debug("image", f"join in-flight {normalized}")
        try:
            return future.result()
        finally:
            with self._lock:
                if self._in_flight.get(normalized) is future:
                    self._in_flight.pop(normalized, None)

    def _fetch_impl(self, url: str) -> ImageFetchResult:
        """执行单个 URL 的实际 fetch 流程。"""
        cached_path = get_cached_path(url)
        if cached_path is not None:
            with Timer("image", f"cache read {cached_path}"):
                data = cached_path.read_bytes()
            mime = self._guess_mime(cached_path)
            log_debug("image", f"cache hit url={url} bytes={len(data)} mime={mime}")
            return ImageFetchResult(url=url, path=cached_path, data=data, mime=mime, from_cache=True)

        cached_filename = get_cached_filename(url)
        if cached_filename:
            stale_path = path_for_filename(cached_filename)
            if stale_path.exists():
                with Timer("image", f"cache read {stale_path}"):
                    data = stale_path.read_bytes()
                mime = self._guess_mime(stale_path)
                log_debug("image", f"cache hit stale-index url={url} bytes={len(data)} mime={mime}")
                return ImageFetchResult(url=url, path=stale_path, data=data, mime=mime, from_cache=True)
            log_debug("image", f"stale index repaired url={url} filename={cached_filename}")
            repair_stale_entry(url)

        sprite_crop = self._parse_sprite_crop(url)
        if sprite_crop is not None:
            return self._fetch_sprite_crop(url, *sprite_crop)

        log_debug("image", f"cache miss url={url}")
        response = self._get_image_response(url)
        response.raise_for_status()
        mime = response.headers.get("Content-Type", "image/jpeg").split(";", 1)[0].strip()
        filename = filename_for_url(url, mime=mime)
        path = cached_path_for_url(url, mime=mime)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with Timer("image", f"cache write {path}"):
            tmp_path.write_bytes(response.content)
            tmp_path.replace(path)

        # 若同一 URL 之前指向了别的旧文件名，先清掉脏映射再写新值。
        old_filename = get_cached_filename(url)
        if old_filename and old_filename != filename:
            drop_cached_filename(url)
        put_cached_filename(url, filename)
        log_debug("image", f"network fetched url={url} bytes={len(response.content)} mime={mime} path={path}")
        return ImageFetchResult(url=url, path=path, data=response.content, mime=mime, from_cache=False)

    def _get_image_response(self, url: str) -> requests.Response:
        """拉取图片响应；对 H@H 瞬时断连做轻量重试。"""
        headers = {
            "Referer": "https://e-hentai.org/",
            "Connection": "close",
        }
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                if attempt > 1:
                    log_debug("image", f"retry image fetch attempt={attempt} url={url}")
                return browser_session.get(url, headers=headers, timeout=20)
            except requests.RequestException as ex:
                last_error = ex
                log_debug("image", f"transient image fetch failed attempt={attempt} url={url}: {ex}")
                if attempt < 3:
                    time.sleep(0.5 * attempt)
        assert last_error is not None
        raise last_error

    def _fetch_sprite_crop(
        self,
        url: str,
        base_url: str,
        left: int,
        top: int,
        right: int,
        bottom: int,
    ) -> ImageFetchResult:
        """处理 EH sprite crop URL：先取原始 sprite，再本地裁剪并缓存。"""
        log_debug("image", f"sprite crop url={url} base={base_url} box={left},{top},{right},{bottom}")
        base_result = self._fetch_impl(base_url)
        with Timer("image", f"sprite crop {base_url}"):
            with Image.open(BytesIO(base_result.data)) as image:
                cropped = image.crop((left, top, right, bottom))
                output = BytesIO()
                fmt = image.format or "WEBP"
                cropped.save(output, format=fmt)
                data = output.getvalue()

        mime = base_result.mime if base_result.mime.startswith("image/") else "image/webp"
        filename = filename_for_url(url, mime=mime)
        path = cached_path_for_url(url, mime=mime)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with Timer("image", f"cache write {path}"):
            tmp_path.write_bytes(data)
            tmp_path.replace(path)

        old_filename = get_cached_filename(url)
        if old_filename and old_filename != filename:
            drop_cached_filename(url)
        put_cached_filename(url, filename)
        log_debug("image", f"sprite cropped url={url} bytes={len(data)} mime={mime} path={path}")
        return ImageFetchResult(url=url, path=path, data=data, mime=mime, from_cache=False)

    @staticmethod
    def _parse_sprite_crop(url: str) -> tuple[str, int, int, int, int] | None:
        """解析本地 crop URL 后缀，返回原始 sprite URL 和裁剪框。"""
        if "@" not in url:
            return None
        base_url, crop_spec = url.rsplit("@", 1)
        if not base_url or not crop_spec:
            return None
        params = parse_qs(crop_spec, keep_blank_values=False)
        x_values = params.get("x")
        y_values = params.get("y")
        if not x_values or not y_values:
            return None

        def parse_range(value: str) -> tuple[int, int] | None:
            parts = value.split("-", 1)
            if len(parts) != 2:
                return None
            try:
                start = int(parts[0])
                end = int(parts[1])
            except ValueError:
                return None
            if start < 0 or end <= start:
                return None
            return start, end

        x_range = parse_range(x_values[0])
        y_range = parse_range(y_values[0])
        if x_range is None or y_range is None:
            return None
        return base_url, x_range[0], y_range[0], x_range[1], y_range[1]

    @staticmethod
    def _guess_mime(path: Path) -> str:
        """根据文件扩展名推断图片 MIME。"""
        suffix = path.suffix.lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")


image_fetcher = ImageFetcherService()
