"""Compatibility exports backed by the standalone Core runtime."""

from app.backend import runtime
from core.provider.pixiv import PixivWebClient


def get_pixiv_client() -> PixivWebClient:
    return runtime.get_pixiv_client()


def invalidate_pixiv_client() -> None:
    runtime.invalidate_pixiv_client()
