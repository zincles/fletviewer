import json
import tempfile
import unittest
from pathlib import Path

from app import storage
from app.backend_config import AppBackendConfigRepository
from core.config import (
    BackendConfig,
    BooruConfig,
    EHConfig,
    MemoryBackendConfigRepository,
    PixivConfig,
    ProxyConfig,
)
from core.runtime import BackendRuntime
from core.storage import AppStoragePaths, StorageLayout


class BackendConfigTests(unittest.TestCase):
    def test_config_is_json_safe_and_invalid_proxy_falls_back(self):
        config = BackendConfig.from_dict({
            "eh": {"ipb_member_id": 123, "login_enabled": False},
            "proxy": {"mode": "invalid", "url": None},
        })

        self.assertEqual(config.eh.ipb_member_id, "123")
        self.assertFalse(config.eh.login_enabled)
        self.assertEqual(config.proxy.mode, "disabled")
        json.dumps(config.to_dict())

    def test_memory_repository_round_trip(self):
        repository = MemoryBackendConfigRepository()
        config = BackendConfig(pixiv=PixivConfig(user_id="42", cookie="session"))

        repository.save(config)

        self.assertEqual(repository.load(), config)

    def test_runtime_saves_each_backend_section_and_invalidates_clients(self):
        repository = MemoryBackendConfigRepository(BackendConfig(
            eh=EHConfig(login_enabled=False),
            pixiv=PixivConfig(cookie="PHPSESSID=123_old"),
            booru=BooruConfig(gelbooru_user_id="1", gelbooru_api_key="old"),
        ))
        runtime = BackendRuntime(config_repository=repository)
        pixiv_client = runtime.get_pixiv_client()
        booru_client = runtime.get_booru_client("gelbooru")

        runtime.save_pixiv_config(PixivConfig(cookie="PHPSESSID=456_new"))
        runtime.save_booru_config(BooruConfig(gelbooru_user_id="2", gelbooru_api_key="new"))
        runtime.save_eh_config(EHConfig(ipb_member_id="member", login_enabled=False))
        runtime.save_proxy_config(ProxyConfig(mode="disabled"))

        saved = repository.load()
        self.assertEqual(saved.pixiv.cookie, "PHPSESSID=456_new")
        self.assertEqual(saved.booru.gelbooru_api_key, "new")
        self.assertEqual(saved.eh.ipb_member_id, "member")
        self.assertIsNot(runtime.get_pixiv_client(), pixiv_client)
        self.assertIsNot(runtime.get_booru_client("gelbooru"), booru_client)

    def test_app_adapter_preserves_legacy_ui_preferences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            layout = StorageLayout.from_paths(
                AppStoragePaths(root / "Data", root / "Cache", root / "Downloads", root / "Temp")
            )
            previous = storage.get_storage_layout()
            try:
                storage.configure_storage(layout)
                storage.save_app_config({"theme_mode": "dark", "gallery_grid_columns": 7})
                repository = AppBackendConfigRepository()
                repository.save(BackendConfig(
                    eh=EHConfig(ipb_member_id="member", login_enabled=False),
                    pixiv=PixivConfig(user_id="42", cookie="cookie"),
                    booru=BooruConfig(gelbooru_api_key="key"),
                    proxy=ProxyConfig(mode="manual", url="http://127.0.0.1:8080"),
                ))

                app = storage.load_app_config()
                self.assertEqual(app["theme_mode"], "dark")
                self.assertEqual(app["gallery_grid_columns"], 7)
                self.assertFalse(app["enable_login"])
                self.assertEqual(repository.load().pixiv.user_id, "42")
            finally:
                storage.configure_storage(previous)


if __name__ == "__main__":
    unittest.main()
