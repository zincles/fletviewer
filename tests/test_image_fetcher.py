import tempfile
import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import requests

from core.image.fetcher import ImageFetchCancelled, ImageFetcherService, ImageLoadCoordinator


class _MemoryCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.entries: dict[str, str] = {}

    def ensure_image_cache_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def get_cached_filename(self, url: str) -> str | None:
        return self.entries.get(url)

    def get_cached_path(self, url: str) -> Path | None:
        filename = self.entries.get(url)
        if not filename:
            return None
        path = self.path_for_filename(filename)
        return path if path.exists() else None

    def path_for_filename(self, filename: str) -> Path:
        return self.root / filename

    def repair_stale_entry(self, url: str) -> bool:
        return self.entries.pop(url, None) is not None

    def filename_for_url(self, url: str, mime: str | None = None) -> str:
        return "image.jpg"

    def cached_path_for_url(self, url: str, mime: str | None = None) -> Path:
        return self.root / self.filename_for_url(url, mime)

    def drop_cached_filename(self, url: str) -> str | None:
        return self.entries.pop(url, None)

    def put_cached_filename(self, url: str, filename: str, *, kind: str = "unknown") -> None:
        self.entries[url] = filename

    def get_gallery_page_cached_filename(self, provider: str, gid: str, token: str, page_idx: int) -> str | None:
        return None

    def get_gallery_page_cached_path(self, provider: str, gid: str, token: str, page_idx: int) -> Path | None:
        return None

    def repair_gallery_page_entry(self, provider: str, gid: str, token: str, page_idx: int) -> bool:
        return False

    def put_gallery_page_cached_filename(
        self,
        provider: str,
        gid: str,
        token: str,
        page_idx: int,
        filename: str,
        *,
        kind: str = "original",
    ) -> None:
        pass


class ImageFetcherAsyncTests(unittest.TestCase):
    def test_coordinator_accepts_already_completed_future_without_deadlock(self) -> None:
        service = Mock()
        future = Future()
        future.set_result("cached")
        service.submit_fetch.return_value = ("task-1", future)
        service.task_state.return_value = None
        coordinator = ImageLoadCoordinator(service)

        subscription = coordinator.subscribe("https://example.test/cached.jpg")

        self.assertEqual(subscription.future.result(), "cached")

    def test_subscription_progress_uses_its_task_generation(self) -> None:
        service = Mock()
        future = Future()
        service.submit_fetch.return_value = ("generation-2", future)
        expected = Mock(key="generation-2")
        service.task_state.return_value = expected
        coordinator = ImageLoadCoordinator(service)

        subscription = coordinator.subscribe("https://example.test/image.jpg")
        progress = subscription.progress()

        self.assertIs(progress, expected)
        service.task_state.assert_called_once_with("generation-2")
        future.set_result("done")

    def test_cancel_then_retry_keeps_new_generation_registered(self) -> None:
        service = Mock()
        first_future = Future()
        second_future = Future()
        service.submit_fetch.side_effect = [
            ("generation-1", first_future),
            ("generation-2", second_future),
        ]
        coordinator = ImageLoadCoordinator(service)
        first = coordinator.subscribe("https://example.test/image.jpg")
        first.cancel()
        second = coordinator.retry("https://example.test/image.jpg")

        first_future.set_exception(ImageFetchCancelled())

        entries = coordinator.debug_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["task_key"], "generation-2")
        self.assertIs(second.future, second_future)
        second_future.set_result("done")

    def test_coordinator_shares_future_and_cancels_only_last_subscriber(self) -> None:
        started = threading.Event()
        release = threading.Event()

        def blocked_fetch(url: str, kind: str, task_key: str | None = None, cancel_event=None):
            started.set()
            while not release.wait(0.01):
                if cancel_event is not None and cancel_event.is_set():
                    raise ImageFetchCancelled()
            return "result"

        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(cache=_MemoryCache(Path(tmp)), get_response=lambda *_args: None, max_workers=1)
            service._fetch_impl = blocked_fetch
            coordinator = ImageLoadCoordinator(service)

            first = coordinator.subscribe("https://example.test/shared.jpg")
            second = coordinator.subscribe("https://example.test/shared.jpg")
            self.assertTrue(started.wait(timeout=1))
            self.assertIs(first.future, second.future)
            self.assertEqual(coordinator.subscriber_count(first.url), 2)

            first.cancel()
            self.assertFalse(second.future.done())
            self.assertEqual(coordinator.subscriber_count(second.url), 1)

            release.set()
            self.assertEqual(second.future.result(timeout=1), "result")

    def test_last_subscriber_cancel_stops_running_task(self) -> None:
        started = threading.Event()

        def blocked_fetch(url: str, kind: str, task_key: str | None = None, cancel_event=None):
            started.set()
            while True:
                if cancel_event is not None and cancel_event.wait(0.01):
                    raise ImageFetchCancelled()

        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(cache=_MemoryCache(Path(tmp)), get_response=lambda *_args: None, max_workers=1)
            service._fetch_impl = blocked_fetch
            coordinator = ImageLoadCoordinator(service)
            subscription = coordinator.subscribe("https://example.test/cancel.jpg")
            self.assertTrue(started.wait(timeout=1))

            subscription.cancel()

            with self.assertRaises(ImageFetchCancelled):
                subscription.future.result(timeout=1)

    def test_cancelled_cache_write_removes_temporary_file(self) -> None:
        cancel_event = threading.Event()

        class Response:
            headers = {"Content-Length": "8"}

            def iter_content(self, chunk_size: int):
                yield b"data"
                cancel_event.set()
                yield b"more"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ImageFetcherService(cache=_MemoryCache(root), get_response=lambda *_args: None, max_workers=1)
            target = root / "image.jpg"

            with self.assertRaises(ImageFetchCancelled):
                service._write_response_to_cache(Response(), target, None, cancel_event)

            self.assertFalse(target.exists())
            self.assertEqual(list(root.glob("*.tmp")), [])

    def test_cancel_interrupts_retry_backoff(self) -> None:
        cancel_event = threading.Event()
        attempts = 0

        def fail_response(*_args):
            nonlocal attempts
            attempts += 1
            cancel_event.set()
            raise requests.ConnectionError("offline")

        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(cache=_MemoryCache(Path(tmp)), get_response=fail_response, max_workers=1)
            started = time.perf_counter()

            with self.assertRaises(ImageFetchCancelled):
                service._get_image_response("https://example.test/image.jpg", cancel_event)

            self.assertLess(time.perf_counter() - started, 0.2)
            self.assertEqual(attempts, 1)

    def test_invalid_content_length_is_treated_as_unknown(self) -> None:
        class Response:
            headers = {"Content-Length": "invalid"}

            def iter_content(self, chunk_size: int):
                yield b"data"

        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(cache=_MemoryCache(Path(tmp)), get_response=lambda *_args: None, max_workers=1)

            data = service._write_response_to_cache(Response(), Path(tmp) / "image.jpg", None)

            self.assertEqual(data, b"data")

    def test_cache_read_failure_finishes_task_as_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = _MemoryCache(Path(tmp))
            cache.get_cached_path = Mock(side_effect=PermissionError("denied"))
            service = ImageFetcherService(cache=cache, get_response=lambda *_args: None, max_workers=1)

            with self.assertRaises(PermissionError):
                service.fetch_async("https://example.test/image.jpg").result(timeout=1)

            snapshot = service.snapshot()
            self.assertEqual(snapshot.active, [])
            self.assertEqual(snapshot.queued, [])
            self.assertEqual(snapshot.recent[0].status, "failed")

    def test_last_subscriber_marks_running_task_cancelling(self) -> None:
        started = threading.Event()

        def blocked_fetch(url: str, kind: str, task_key: str | None = None, cancel_event=None):
            service._update_task(task_key, status="running", started_at=time.time())
            started.set()
            while not cancel_event.wait(0.01):
                pass
            raise ImageFetchCancelled()

        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(cache=_MemoryCache(Path(tmp)), get_response=lambda *_args: None, max_workers=1)
            service._fetch_impl = blocked_fetch
            coordinator = ImageLoadCoordinator(service)
            subscription = coordinator.subscribe("https://example.test/image.jpg")
            self.assertTrue(started.wait(timeout=1))

            subscription.cancel()
            state = service.task_state(subscription.task_key)

            self.assertIsNotNone(state)
            self.assertEqual(state.status, "cancelling")
            with self.assertRaises(ImageFetchCancelled):
                subscription.future.result(timeout=1)

    def test_concurrent_fetch_impl_for_same_url_downloads_once(self) -> None:
        class Response:
            headers = {"Content-Length": "4", "Content-Type": "image/webp"}

            def raise_for_status(self) -> None:
                pass

            def iter_content(self, chunk_size: int):
                yield b"data"

        calls = 0
        calls_lock = threading.Lock()

        def get_response(*_args):
            nonlocal calls
            with calls_lock:
                calls += 1
            return Response()

        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(
                cache=_MemoryCache(Path(tmp)),
                get_response=get_response,
                max_workers=2,
            )
            url = "https://example.test/shared.webp"

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = [
                    future.result(timeout=2)
                    for future in [executor.submit(service._fetch_impl, url, "sprite") for _ in range(2)]
                ]

            self.assertEqual(calls, 1)
            self.assertEqual([result.data for result in results], [b"data", b"data"])
            self.assertFalse(results[0].from_cache)
            self.assertTrue(results[1].from_cache)

    def test_temporary_paths_are_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(
                cache=_MemoryCache(Path(tmp)),
                get_response=lambda *_args: None,
                max_workers=1,
            )
            target = Path(tmp) / "shared.webp"
            first = service._temporary_path(target)
            second = service._temporary_path(target)

            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, target.parent)
            self.assertTrue(first.name.startswith(f".{target.name}."))
            self.assertTrue(first.name.endswith(".tmp"))

    def test_existing_target_wins_when_windows_rejects_replace(self) -> None:
        class Response:
            headers = {"Content-Length": "4"}

            def iter_content(self, chunk_size: int):
                yield b"new!"

        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(
                cache=_MemoryCache(Path(tmp)),
                get_response=lambda *_args: None,
                max_workers=1,
            )
            target = Path(tmp) / "shared.webp"
            target.write_bytes(b"old!")
            original_temporary_path = service._temporary_path

            class RejectedReplacePath(type(target)):
                def replace(self, target):
                    raise PermissionError("simulated Windows sharing violation")

            temporary = original_temporary_path(target)
            service._temporary_path = lambda _path: RejectedReplacePath(temporary)

            data = service._write_response_to_cache(Response(), target, None)

            self.assertEqual(data, b"old!")
            self.assertEqual(target.read_bytes(), b"old!")
            self.assertFalse(temporary.exists())

    def test_fetch_async_returns_immediately_and_deduplicates(self) -> None:
        started = threading.Event()
        release = threading.Event()
        calls = 0

        def blocked_fetch(url: str, kind: str, task_key: str | None = None):
            nonlocal calls
            calls += 1
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return "result"

        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(
                cache=_MemoryCache(Path(tmp)),
                get_response=lambda *_args: None,
                max_workers=1,
            )
            service._fetch_impl = blocked_fetch

            first = service.fetch_async("https://example.test/image.jpg")
            self.assertTrue(started.wait(timeout=1))
            second = service.fetch_async("https://example.test/image.jpg")

            self.assertIs(first, second)
            self.assertFalse(first.done())
            self.assertEqual(calls, 1)

            release.set()
            self.assertEqual(first.result(timeout=1), "result")

    def test_completed_request_is_removed_from_in_flight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(
                cache=_MemoryCache(Path(tmp)),
                get_response=lambda *_args: None,
                max_workers=1,
            )
            calls = 0

            def completed_fetch(url: str, kind: str, task_key: str | None = None):
                nonlocal calls
                calls += 1
                return calls

            service._fetch_impl = completed_fetch

            self.assertEqual(service.fetch_async("https://example.test/image.jpg").result(timeout=1), 1)
            self.assertEqual(service.fetch_async("https://example.test/image.jpg").result(timeout=1), 2)

    def test_failed_request_is_removed_from_in_flight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(
                cache=_MemoryCache(Path(tmp)),
                get_response=lambda *_args: None,
                max_workers=1,
            )
            calls = 0

            def failed_fetch(url: str, kind: str, task_key: str | None = None):
                nonlocal calls
                calls += 1
                raise RuntimeError("failed")

            service._fetch_impl = failed_fetch

            with self.assertRaisesRegex(RuntimeError, "failed"):
                service.fetch_async("https://example.test/image.jpg").result(timeout=1)
            with self.assertRaisesRegex(RuntimeError, "failed"):
                service.fetch_async("https://example.test/image.jpg").result(timeout=1)
            self.assertEqual(calls, 2)

    def test_failed_background_request_is_reported(self) -> None:
        logged = threading.Event()
        log_exception = Mock(side_effect=lambda *_args: logged.set())
        with tempfile.TemporaryDirectory() as tmp:
            service = ImageFetcherService(
                cache=_MemoryCache(Path(tmp)),
                get_response=lambda *_args: None,
                log_exception=log_exception,
                max_workers=1,
            )
            service._fetch_impl = lambda *_args: (_ for _ in ()).throw(RuntimeError("failed"))

            service.fetch_async("https://example.test/image.jpg")

            self.assertTrue(logged.wait(timeout=1))
            area, message = log_exception.call_args.args
            self.assertEqual(area, "图像")
            self.assertIn("failed", message)


if __name__ == "__main__":
    unittest.main()
