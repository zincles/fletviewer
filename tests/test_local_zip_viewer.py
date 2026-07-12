import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from app.views.local_zip_viewer import _list_images, _read_member
from core.image.fetcher import ImageFetchCancelled


class LocalZipViewerTests(unittest.TestCase):
    def test_images_are_naturally_sorted_and_hidden_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "gallery.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("10.jpg", b"10")
                archive.writestr("2.jpg", b"2")
                archive.writestr("1.jpg", b"1")
                archive.writestr(".hidden.jpg", b"hidden")
                archive.writestr("__MACOSX/cover.jpg", b"hidden")

            self.assertEqual(_list_images(archive_path), ["1.jpg", "2.jpg", "10.jpg"])
            self.assertEqual(_read_member(archive_path, "2.jpg"), b"2")

    def test_duplicate_image_members_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "gallery.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("1.jpg", b"first")
                archive.writestr("1.jpg", b"second")
                archive.writestr("gallery.json", b"{}")

            with self.assertRaisesRegex(ValueError, "重复"):
                _list_images(archive_path)
            self.assertEqual(_read_member(archive_path, "gallery.json"), b"{}")

    def test_cancelled_member_read_stops_before_decompression(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "gallery.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("1.jpg", b"image")
            cancel_event = threading.Event()
            cancel_event.set()

            with self.assertRaises(ImageFetchCancelled):
                _read_member(archive_path, "1.jpg", cancel_event)


if __name__ == "__main__":
    unittest.main()
