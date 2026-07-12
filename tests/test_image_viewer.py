import threading
import time
import unittest
from unittest.mock import patch

from core.image.fetcher import ImageFetchCancelled
from app.views.image_viewer import ImageViewerItem, ViewerImageResult, create_view


class _Page:
    def __init__(self) -> None:
        self.updated = 0
        self.threads: list[threading.Thread] = []

    def update(self) -> None:
        self.updated += 1

    def run_thread(self, worker) -> None:
        thread = threading.Thread(target=worker, daemon=True)
        self.threads.append(thread)
        thread.start()


class ImageViewerLifecycleTests(unittest.TestCase):
    @patch("app.views.image_viewer.get_image_viewer_mode", return_value="paged")
    @patch("app.views.image_viewer.should_load_images", return_value=True)
    def test_image_io_starts_only_after_mount(self, _load_images, _mode) -> None:
        page = _Page()
        called = threading.Event()

        def load_image(_item, _index, _cancel_event):
            called.set()
            return ViewerImageResult(data=b"image", mime="image/jpeg")

        viewer = create_view(page, [ImageViewerItem("image")], 0, lambda: None, load_image=load_image)
        self.assertFalse(called.is_set())

        viewer.did_mount()

        self.assertTrue(called.wait(timeout=1))

    @patch("app.views.image_viewer.show_error_toast")
    @patch("app.views.image_viewer.get_image_viewer_mode", return_value="paged")
    @patch("app.views.image_viewer.should_load_images", return_value=True)
    def test_unmount_cancels_load_without_late_ui_update(self, _load_images, _mode, show_error) -> None:
        page = _Page()
        started = threading.Event()
        stopped = threading.Event()

        def load_image(_item, _index, cancel_event):
            started.set()
            self.assertTrue(cancel_event.wait(timeout=1))
            stopped.set()
            raise ImageFetchCancelled("cancelled")

        viewer = create_view(page, [ImageViewerItem("image")], 0, lambda: None, load_image=load_image)
        viewer.did_mount()
        self.assertTrue(started.wait(timeout=1))
        viewer.will_unmount()
        updates_after_unmount = page.updated

        self.assertTrue(stopped.wait(timeout=1))
        time.sleep(0.01)
        self.assertEqual(page.updated, updates_after_unmount)
        show_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
