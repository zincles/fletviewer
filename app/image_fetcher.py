from app import image_cache
from app.backend import runtime
from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.lazy import LazyProxy
from app.storage import should_load_images
from core.image.fetcher import ImageFetchCancelled, ImageFetcherService, ImageFetchResult, ImageFetchSnapshot, ImageFetchTaskState, ImageLoadCoordinator


def _get_image_response(url: str, headers: dict[str, str], timeout: int):
    return browser_session.get(url, headers=headers, timeout=timeout, stream=True)


def _create_image_fetcher() -> ImageFetcherService:
    service = ImageFetcherService(
        cache=image_cache,
        get_response=_get_image_response,
        log_debug=log_debug,
        log_exception=log_exception,
        timer_factory=Timer,
        max_workers=8,
    )
    return service


image_fetcher = LazyProxy(_create_image_fetcher)


def _create_image_load_coordinator() -> ImageLoadCoordinator:
    return ImageLoadCoordinator(image_fetcher.resolve())


image_load_coordinator = LazyProxy(_create_image_load_coordinator)


class _RuntimeImageFetcher:
    def submit_fetch(self, *args, **kwargs):
        return image_fetcher.submit_fetch(*args, **kwargs)

    def task_state(self, *args, **kwargs):
        return image_fetcher.task_state(*args, **kwargs)

    def mark_cancelling(self, *args, **kwargs):
        return image_fetcher.mark_cancelling(*args, **kwargs)

    def shutdown(self, *, wait: bool = True):
        image_load_coordinator.reset()
        service = image_fetcher.reset()
        if service is not None:
            service.shutdown(wait=wait)


runtime.configure_image_fetcher(_RuntimeImageFetcher(), images_enabled=should_load_images)


__all__ = ["ImageFetchCancelled", "ImageFetcherService", "ImageFetchResult", "ImageFetchSnapshot", "ImageFetchTaskState", "image_fetcher", "image_load_coordinator"]
