import unittest
from concurrent.futures import Future

from app.controls.async_image import _AsyncImage


class _DisconnectedPage:
    class Session:
        connection = None

    session = Session()
    fletviewer_content_generation = 1

    def run_thread(self, handler):
        raise AssertionError("run_thread must not be called after the session disconnects")


class AsyncImageLifecycleTests(unittest.TestCase):
    def test_completed_fetch_is_discarded_after_session_disconnect(self) -> None:
        control = object.__new__(_AsyncImage)
        control._page = _DisconnectedPage()
        control._url = "https://example.test/image.jpg"
        control._mounted = True
        control._loading = True
        control._load_token = 0
        control._content_generation = 1
        future = Future()
        future.set_result(None)

        control._schedule_apply(0, future)

        self.assertFalse(control._loading)


if __name__ == "__main__":
    unittest.main()
