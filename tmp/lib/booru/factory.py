from __future__ import annotations

from enum import Enum
from typing import Any

from .providers._base import _BaseBooruClient
from .providers import DanbooruClient, GelbooruAlikeClient, GelbooruClient, MoebooruClient, Rule34Client, SafebooruClient


class BooruKind(str, Enum):
    DANBOORU = "danbooru"
    GELBOORU = "gelbooru"
    GELBOORU_ALIKE = "gelbooru_alike"
    SAFEBOORU = "safebooru"
    RULE34 = "rule34"
    MOEBOORU = "moebooru"


def create_booru_client(kind: str | BooruKind, **kwargs: Any) -> _BaseBooruClient:
    '''
    根据协议类型创建对应 Booru client。

    这个 factory 只负责选择 provider，不负责自动探测站点协议。自动探测需要单独实现，
    因为 Gelbooru、Gelbooru-alike、Moebooru 等协议不能混用。
    '''
    value = kind.value if isinstance(kind, BooruKind) else str(kind).lower()
    if value == BooruKind.DANBOORU.value:
        return DanbooruClient(**kwargs)
    if value == BooruKind.GELBOORU.value:
        return GelbooruClient(**kwargs)
    if value == BooruKind.GELBOORU_ALIKE.value:
        return GelbooruAlikeClient(**kwargs)
    if value == BooruKind.SAFEBOORU.value:
        return SafebooruClient(**kwargs)
    if value == BooruKind.RULE34.value:
        return Rule34Client(**kwargs)
    if value == BooruKind.MOEBOORU.value:
        return MoebooruClient(**kwargs)
    raise ValueError(f"unsupported booru kind: {kind}")
