import unittest
from concurrent.futures import Future
from unittest.mock import Mock, patch

from app.controls.async_image import _AsyncImage


class _DisconnectedPage:
    fletviewer_content_generation = 1

    def run_thread(self, handler):
        raise AssertionError("run_thread must not be called after the session disconnects")


class AsyncImageLifecycleTests(unittest.TestCase):
    def test_completed_fetch_uses_scheduler_even_without_private_session_connection(self) -> None:
        control = object.__new__(_AsyncImage)
        page = Mock(spec=["run_thread"])
        control._page = page
        control._url = "https://example.test/image.jpg"
        control._mounted = True
        control._loading = True
        control._load_token = 1
        control._content_generation = None
        subscription = Mock()
        control._subscription = subscription
        future = Future()
        future.set_result(None)

        control._schedule_apply(1, subscription, future)

        page.run_thread.assert_called_once()

    def test_completed_fetch_attempts_public_scheduler_without_private_connection_check(self) -> None:
        control = object.__new__(_AsyncImage)
        control._page = _DisconnectedPage()
        control._url = "https://example.test/image.jpg"
        control._mounted = True
        control._loading = True
        control._load_token = 0
        control._content_generation = 1
        future = Future()
        future.set_result(None)

        with patch("app.controls.async_image.image_progress_pump") as progress_pump:
            control._schedule_apply(0, future)

        self.assertFalse(control._loading)
        progress_pump.return_value.unregister.assert_called_once_with(control)

    def test_old_generation_cannot_clear_current_subscription(self) -> None:
        control = object.__new__(_AsyncImage)
        control._page = _DisconnectedPage()
        control._url = "https://example.test/image.jpg"
        control._mounted = True
        control._loading = True
        control._load_token = 2
        control._content_generation = 1
        old_subscription = Mock()
        current_subscription = Mock()
        control._subscription = current_subscription
        control._progress_ring = Mock()
        future = Future()
        future.set_result(None)

        with patch("app.controls.async_image.image_progress_pump") as progress_pump:
            control._schedule_apply(1, old_subscription, future)

        self.assertTrue(control._loading)
        self.assertIs(control._subscription, current_subscription)
        progress_pump.return_value.unregister.assert_not_called()


if __name__ == "__main__":
    unittest.main()
