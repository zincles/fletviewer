from app.browser_session import browser_session
from app.debug_log import log_debug
from app.storage import load_booru_config
from core.provider.booru import BOORU_PROVIDERS, BooruClient, create_booru_client


_clients: dict[str, BooruClient] = {}


def get_booru_client(provider_id: str) -> BooruClient:
    """返回指定站点的共享缺省 client。"""
    if provider_id not in BOORU_PROVIDERS:
        raise KeyError(f"未知 Booru Provider: {provider_id}")
    if provider_id not in _clients:
        cfg = load_booru_config()
        credentials = {}
        if provider_id == "gelbooru":
            credentials = {
                "user_id": str(cfg.get("gelbooru_user_id") or ""),
                "api_key": str(cfg.get("gelbooru_api_key") or ""),
            }
        _clients[provider_id] = create_booru_client(
            provider_id,
            transport=browser_session,
            log_debug=log_debug,
            credentials=credentials,
        )
    return _clients[provider_id]


def invalidate_booru_clients() -> None:
    _clients.clear()
