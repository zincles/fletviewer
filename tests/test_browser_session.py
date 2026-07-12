import unittest

from core.net.browser_session import BrowserSessionService


class BrowserSessionProxyTests(unittest.TestCase):
    def _service(self, app_config: dict) -> BrowserSessionService:
        return BrowserSessionService(
            load_app_config=lambda: app_config,
            load_eh_config=lambda: {},
        )

    def test_manual_proxy_applies_to_shared_session(self):
        service = self._service({"proxy_mode": "manual", "proxy_url": "http://127.0.0.1:7890"})

        service.configure_proxy_from_storage()

        self.assertFalse(service.session.trust_env)
        self.assertEqual(service.session.proxies["http"], "http://127.0.0.1:7890")
        self.assertEqual(service.session.proxies["https"], "http://127.0.0.1:7890")

    def test_disabled_proxy_ignores_environment(self):
        service = self._service({"proxy_mode": "disabled"})
        service.session.proxies["http"] = "http://old:1"

        service.configure_proxy_from_storage()

        self.assertFalse(service.session.trust_env)
        self.assertEqual(service.session.proxies, {})

    def test_system_proxy_uses_requests_environment_support(self):
        service = self._service({"proxy_mode": "system"})

        service.configure_proxy_from_storage()

        self.assertTrue(service.session.trust_env)
        self.assertEqual(service.session.proxies, {})

    def test_invalid_manual_proxy_is_rejected(self):
        service = self._service({"proxy_mode": "manual", "proxy_url": "socks5://127.0.0.1:7890"})

        with self.assertRaises(ValueError):
            service.configure_proxy_from_storage()


if __name__ == "__main__":
    unittest.main()
