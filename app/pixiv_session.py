from __future__ import annotations

from app.debug_log import log_debug
from app.browser_session import browser_session
from app.storage import load_pixiv_config
from core.provider.pixiv import PixivWebClient


_client: PixivWebClient | None = None


def get_pixiv_client() -> PixivWebClient:
    """返回使用用户导入 Cookie 的 Pixiv 网页 AJAX client。"""
    global _client
    cfg = load_pixiv_config()
    signature = (str(cfg.get("cookie") or ""), str(cfg.get("user_id") or ""))
    if _client is not None and (_client.cookie, _client.user_id) != signature:
        _client = None
    if _client is None:
        _client = PixivWebClient(transport=browser_session, cookie=signature[0], user_id=signature[1], log_debug=log_debug)
        log_debug("pixiv", f"已创建 Pixiv 网页 Provider has_cookie={bool(signature[0])}")
    return _client


def invalidate_pixiv_client() -> None:
    global _client
    _client = None
