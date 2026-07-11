import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from core.image.fetcher import ImageFetcherService


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

            self.assertEqual(data, b"new!")
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


if __name__ == "__main__":
    unittest.main()
