import unittest

from core.runtime import BackendRuntime


class _LifecycleService:
    def __init__(self, events, name, *, fail_once=False):
        self.events = events
        self.name = name
        self.fail_once = fail_once

    def initialize(self):
        self.events.append(f"initialize:{self.name}")
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("temporary failure")

    def shutdown(self, **kwargs):
        self.events.append((f"shutdown:{self.name}", kwargs))


class BackendRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.pixiv_config = {"cookie": "PHPSESSID=123_token", "user_id": ""}
        self.booru_config = {"gelbooru_user_id": "1", "gelbooru_api_key": "key"}
        self.runtime = BackendRuntime(
            load_app_config=lambda: {"proxy_mode": "disabled", "enable_login": False},
            load_eh_config=lambda: {},
            load_pixiv_config=lambda: dict(self.pixiv_config),
            load_booru_config=lambda: dict(self.booru_config),
        )

    def test_runtime_owns_facade_and_shared_browser_session(self):
        self.assertIs(self.runtime.backend._get_eh_client.__self__, self.runtime.browser_session)

    def test_pixiv_client_is_reused_when_user_id_is_derived(self):
        first = self.runtime.get_pixiv_client()
        second = self.runtime.get_pixiv_client()

        self.assertIs(first, second)
        self.assertEqual(first.user_id, "123")

    def test_pixiv_config_change_replaces_client(self):
        first = self.runtime.get_pixiv_client()
        self.pixiv_config["cookie"] = "PHPSESSID=456_new"

        second = self.runtime.get_pixiv_client()

        self.assertIsNot(first, second)
        self.assertEqual(second.user_id, "456")

    def test_booru_clients_are_reused_and_can_be_invalidated(self):
        first = self.runtime.get_booru_client("gelbooru")
        self.assertIs(first, self.runtime.get_booru_client("gelbooru"))

        self.runtime.invalidate_booru_clients()

        self.assertIsNot(first, self.runtime.get_booru_client("gelbooru"))

    def test_runtime_has_no_flet_or_app_dependency(self):
        module_names = {
            value.__module__
            for value in (BackendRuntime, type(self.runtime.backend), type(self.runtime.browser_session))
        }
        self.assertTrue(all(not name.startswith("app") and not name.startswith("flet") for name in module_names))

    def test_download_manager_can_be_injected_without_app(self):
        manager = object()

        self.runtime.configure_download_manager(manager)

        self.assertIs(self.runtime.get_download_manager(), manager)

    def test_image_fetcher_can_be_injected_without_app(self):
        fetcher = object()

        self.runtime.configure_image_fetcher(fetcher)

        self.assertIs(self.runtime.get_image_task_service()._fetcher, fetcher)

    def test_library_ports_can_be_injected_without_app(self):
        gallery_manager = object()
        history_repository = object()

        self.runtime.configure_local_gallery_manager(gallery_manager)
        self.runtime.configure_history_repository(history_repository)

        self.assertIs(self.runtime.get_local_gallery_service()._manager, gallery_manager)
        self.assertIs(self.runtime.get_history_service()._repository, history_repository)

    def test_lifecycle_is_idempotent_and_can_restart(self):
        events = []
        download = _LifecycleService(events, "download")
        gallery = _LifecycleService(events, "gallery")
        image = _LifecycleService(events, "image")
        self.runtime.configure_download_manager(download)
        self.runtime.configure_local_gallery_manager(gallery)
        self.runtime.configure_image_fetcher(image)

        self.runtime.initialize()
        self.runtime.initialize()
        self.runtime.shutdown(wait=False, cancel_futures=True)
        self.runtime.initialize()

        self.assertEqual(events[:2], ["initialize:download", "initialize:gallery"])
        self.assertEqual(events[2], ("shutdown:image", {"wait": False}))
        self.assertEqual(events[3], ("shutdown:download", {"wait": False, "cancel_futures": True}))
        self.assertEqual(events[4:], ["initialize:download", "initialize:gallery"])

    def test_initialize_failure_can_be_retried(self):
        events = []
        download = _LifecycleService(events, "download", fail_once=True)
        self.runtime.configure_download_manager(download)

        with self.assertRaisesRegex(RuntimeError, "temporary failure"):
            self.runtime.initialize()
        self.runtime.initialize()

        self.assertEqual(events, ["initialize:download", "initialize:download"])


if __name__ == "__main__":
    unittest.main()
