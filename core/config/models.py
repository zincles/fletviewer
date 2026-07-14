from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


@dataclass(frozen=True, slots=True)
class EHConfig:
    ipb_member_id: str = ""
    ipb_pass_hash: str = ""
    igneous: str = ""
    star: str = ""
    login_enabled: bool = True

    @classmethod
    def from_dict(cls, value: object) -> EHConfig:
        data = _mapping(value)
        return cls(
            ipb_member_id=str(data.get("ipb_member_id") or ""),
            ipb_pass_hash=str(data.get("ipb_pass_hash") or ""),
            igneous=str(data.get("igneous") or ""),
            star=str(data.get("star") or ""),
            login_enabled=bool(data.get("login_enabled", True)),
        )


@dataclass(frozen=True, slots=True)
class PixivConfig:
    user_id: str = ""
    cookie: str = ""

    @classmethod
    def from_dict(cls, value: object) -> PixivConfig:
        data = _mapping(value)
        return cls(
            user_id=str(data.get("user_id") or ""),
            cookie=str(data.get("cookie") or ""),
        )


@dataclass(frozen=True, slots=True)
class BooruConfig:
    gelbooru_user_id: str = ""
    gelbooru_api_key: str = ""

    @classmethod
    def from_dict(cls, value: object) -> BooruConfig:
        data = _mapping(value)
        return cls(
            gelbooru_user_id=str(data.get("gelbooru_user_id") or ""),
            gelbooru_api_key=str(data.get("gelbooru_api_key") or ""),
        )


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    mode: str = "disabled"
    url: str = ""

    @classmethod
    def from_dict(cls, value: object) -> ProxyConfig:
        data = _mapping(value)
        mode = str(data.get("mode") or "disabled")
        if mode not in {"disabled", "system", "manual"}:
            mode = "disabled"
        return cls(mode=mode, url=str(data.get("url") or "").strip())


@dataclass(frozen=True, slots=True)
class BackendConfig:
    eh: EHConfig = field(default_factory=EHConfig)
    pixiv: PixivConfig = field(default_factory=PixivConfig)
    booru: BooruConfig = field(default_factory=BooruConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)

    @classmethod
    def from_dict(cls, value: object) -> BackendConfig:
        data = _mapping(value)
        return cls(
            eh=EHConfig.from_dict(data.get("eh")),
            pixiv=PixivConfig.from_dict(data.get("pixiv")),
            booru=BooruConfig.from_dict(data.get("booru")),
            proxy=ProxyConfig.from_dict(data.get("proxy")),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
