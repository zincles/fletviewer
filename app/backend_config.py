"""Adapter between the legacy Flet config file and the core config contract."""

from core.config import BackendConfig, BooruConfig, EHConfig, PixivConfig, ProxyConfig

from app.storage import (
    load_app_config,
    load_booru_config,
    load_eh_config,
    load_pixiv_config,
    save_app_config,
    save_booru_config,
    save_eh_config,
    save_pixiv_config,
)


class AppBackendConfigRepository:
    def load(self) -> BackendConfig:
        app = load_app_config()
        eh = load_eh_config()
        return BackendConfig(
            eh=EHConfig(
                ipb_member_id=str(eh.get("ipb_member_id") or ""),
                ipb_pass_hash=str(eh.get("ipb_pass_hash") or ""),
                igneous=str(eh.get("igneous") or ""),
                star=str(eh.get("star") or ""),
                login_enabled=bool(app.get("enable_login", True)),
            ),
            pixiv=PixivConfig.from_dict(load_pixiv_config()),
            booru=BooruConfig.from_dict(load_booru_config()),
            proxy=ProxyConfig.from_dict({"mode": app.get("proxy_mode"), "url": app.get("proxy_url")}),
        )

    def save(self, config: BackendConfig) -> None:
        if not isinstance(config, BackendConfig):
            raise TypeError("config must be BackendConfig")
        save_eh_config({
            "ipb_member_id": config.eh.ipb_member_id,
            "ipb_pass_hash": config.eh.ipb_pass_hash,
            "igneous": config.eh.igneous,
            "star": config.eh.star,
        })
        save_pixiv_config({
            "user_id": config.pixiv.user_id,
            "cookie": config.pixiv.cookie,
        })
        save_booru_config({
            "gelbooru_user_id": config.booru.gelbooru_user_id,
            "gelbooru_api_key": config.booru.gelbooru_api_key,
        })
        app = load_app_config()
        app.update({
            "enable_login": config.eh.login_enabled,
            "proxy_mode": config.proxy.mode,
            "proxy_url": config.proxy.url,
        })
        save_app_config(app)
