import unittest
import threading
from unittest.mock import Mock

from core.net.browser_session import BrowserSessionService, redact_url


class BrowserSessionProxyTests(unittest.TestCase):
    def _service(self, app_config: dict) -> BrowserSessionService:
        return BrowserSessionService(
            load_app_config=lambda: app_config,
            load_eh_config=lambda: {},
        )

    def test_redact_url_hides_api_key(self):
        value = redact_url("https://example.test/posts?user_id=12&api_key=secret&tags=cat")
        self.assertIn("user_id=12", value)
        self.assertIn("tags=cat", value)
        self.assertNotIn("secret", value)

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

    def test_eh_client_requests_use_service_entrypoint(self):
        service = self._service({"proxy_mode": "disabled"})
        response = Mock(status_code=200)
        service.get = Mock(return_value=response)
        client = service.get_eh_client(require_login=False)

        result = client._session.get("https://e-hentai.org/")

        self.assertIs(result, response)
        service.get.assert_called_once_with("https://e-hentai.org/")

    def test_guest_requests_remain_concurrent_after_initial_configuration(self):
        service = self._service({"proxy_mode": "disabled", "enable_login": False})
        entered = 0
        both_entered = threading.Event()
        release = threading.Event()
        lock = threading.Lock()

        def get(*_args, **_kwargs):
            nonlocal entered
            with lock:
                entered += 1
                if entered == 2:
                    both_entered.set()
            release.wait(timeout=2)
            return Mock(status_code=200, content=b"", url="https://example.test/image.jpg")

        service.session.get = get
        threads = [threading.Thread(target=service.get, args=("https://example.test/image.jpg",)) for _ in range(2)]
        for thread in threads:
            thread.start()
        self.assertTrue(both_entered.wait(timeout=1))
        release.set()
        for thread in threads:
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
