import json
import threading
import unittest
from concurrent.futures import Future
from types import SimpleNamespace

from core.api.errors import BackendError
from core.api.images import ImageTaskService
from core.image.fetcher import ImageFetchCancelled, ImageFetchResult


class FakeImageFetcher:
    def __init__(self):
        self.submissions = []
        self.states = {}

    def submit_fetch(self, url, *, kind="unknown", cancel_event=None):
        key = f"fetch-{len(self.submissions) + 1}"
        future = Future()
        event = cancel_event or threading.Event()
        self.submissions.append((key, url, kind, event, future))
        self.states[key] = SimpleNamespace(
            status="running",
            bytes_done=2,
            bytes_total=4,
            from_cache=False,
            error="",
            started_at=10.0,
            finished_at=0.0,
        )
        return key, future

    def task_state(self, key):
        return self.states.get(key)

    def mark_cancelling(self, key):
        self.states[key].status = "cancelling"


class ImageTaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.fetcher = FakeImageFetcher()
        self.service = ImageTaskService(self.fetcher)

    def test_start_and_status_are_json_safe_without_future(self):
        started = self.service.start("https://example.test/image.jpg", kind="thumbnail")
        status = self.service.status(started.id)
        payload = status.to_dict()

        self.assertEqual(status.status, "running")
        self.assertEqual(status.progress, 0.5)
        self.assertEqual(status.kind, "thumbnail")
        serialized = json.dumps(payload)
        self.assertNotIn("Future", serialized)
        self.assertNotIn("subscription", serialized)

    def test_completed_result_is_base64_and_contains_no_path(self):
        started = self.service.start("https://example.test/image.jpg")
        future = self.fetcher.submissions[0][4]
        future.set_result(ImageFetchResult(
            url="https://example.test/image.jpg",
            path=__import__("pathlib").Path("C:/private/cache.jpg"),
            data=b"image-bytes",
            mime="image/jpeg",
            from_cache=True,
        ))

        status = self.service.status(started.id)
        result = self.service.result(started.id)
        serialized = json.dumps(result.to_dict())

        self.assertEqual(status.status, "completed")
        self.assertEqual(result.byte_length, 11)
        self.assertNotIn("C:/private", serialized)
        self.assertNotIn("example.test", serialized)

    def test_shared_url_cancels_underlying_fetch_only_after_last_task(self):
        first = self.service.start("https://example.test/shared.jpg")
        second = self.service.start("https://example.test/shared.jpg")
        event = self.fetcher.submissions[0][3]

        self.service.cancel(first.id)
        self.assertFalse(event.is_set())
        self.assertEqual(self.service.status(first.id).status, "cancelled")
        self.assertEqual(self.service.status(second.id).status, "running")

        self.service.cancel(second.id)
        self.assertTrue(event.is_set())

    def test_disabled_and_unknown_tasks_have_stable_errors(self):
        disabled = ImageTaskService(self.fetcher, images_enabled=lambda: False)

        with self.assertRaises(BackendError) as disabled_error:
            disabled.start("https://example.test/image.jpg")
        with self.assertRaises(BackendError) as missing_error:
            self.service.status("missing")

        self.assertEqual(disabled_error.exception.to_dict()["code"], "images_disabled")
        self.assertEqual(missing_error.exception.to_dict()["code"], "image_task_not_found")

    def test_cancelled_result_has_stable_error(self):
        started = self.service.start("https://example.test/image.jpg")
        self.fetcher.submissions[0][4].set_exception(ImageFetchCancelled())

        with self.assertRaises(BackendError) as raised:
            self.service.result(started.id)

        self.assertEqual(raised.exception.to_dict()["code"], "image_cancelled")


if __name__ == "__main__":
    unittest.main()
