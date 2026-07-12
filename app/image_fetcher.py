from app import image_cache
from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.lazy import LazyProxy
from core.image.fetcher import ImageFetcherService, ImageFetchResult, ImageFetchSnapshot, ImageFetchTaskState


def _get_image_response(url: str, headers: dict[str, str], timeout: int):
    return browser_session.get(url, headers=headers, timeout=timeout, stream=True)


def _create_image_fetcher() -> ImageFetcherService:
    return ImageFetcherService(
        cache=image_cache,
        get_response=_get_image_response,
        log_debug=log_debug,
        log_exception=log_exception,
        timer_factory=Timer,
        max_workers=30,
    )


image_fetcher = LazyProxy(_create_image_fetcher)


__all__ = ["ImageFetcherService", "ImageFetchResult", "ImageFetchSnapshot", "ImageFetchTaskState", "image_fetcher"]
