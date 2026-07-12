import tempfile
import unittest
import zipfile
from pathlib import Path

from app.views.local_zip_viewer import _list_images, _read_member


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


if __name__ == "__main__":
    unittest.main()
