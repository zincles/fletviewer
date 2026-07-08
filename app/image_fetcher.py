from app import image_cache
from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from lib.image.fetcher import ImageFetcherService, ImageFetchResult


def _get_image_response(url: str, headers: dict[str, str], timeout: int):
    return browser_session.get(url, headers=headers, timeout=timeout)


image_fetcher = ImageFetcherService(
    cache=image_cache,
    get_response=_get_image_response,
    log_debug=log_debug,
    log_exception=log_exception,
    timer_factory=Timer,
)


__all__ = ["ImageFetcherService", "ImageFetchResult", "image_fetcher"]
