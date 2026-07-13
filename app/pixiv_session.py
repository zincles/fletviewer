from __future__ import annotations

from app.debug_log import log_debug
from core.provider.pixiv import PixivClient


_client: PixivClient | None = None


def get_pixiv_client() -> PixivClient:
    """返回共享的缺省 Pixiv client。"""
    global _client
    if _client is None:
        _client = PixivClient(log_debug=log_debug)
        log_debug("pixiv", "已创建缺省 Pixiv Provider（未接入真实网络）")
    return _client
