"""Compatibility exports backed by the standalone Core runtime."""

from app.backend import runtime
from core.provider.booru import BooruClient


def get_booru_client(provider_id: str) -> BooruClient:
    return runtime.get_booru_client(provider_id)


def invalidate_booru_clients() -> None:
    runtime.invalidate_booru_clients()
