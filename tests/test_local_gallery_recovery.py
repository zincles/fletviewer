import tempfile
import unittest
import zipfile
import json
from pathlib import Path
from unittest.mock import Mock

from core.data.data_db import AppDataDB
from core.download.local_gallery import LocalGalleryManager
from core.download.manager import DownloadTask


class LocalGalleryRecoveryTests(unittest.TestCase):
    def _manager(self, root: Path, download_manager: Mock) -> LocalGalleryManager:
        return LocalGalleryManager(
            archive_dir=root / "Downloads" / "EHArchieve",
            data_db=AppDataDB(root / "Data" / "data.db"),
            ensure_dirs=lambda: None,
            download_manager=download_manager,
        )

    def _task(self, root: Path, payload: bytes) -> DownloadTask:
        task_dir = root / "Downloads" / "Downloading" / "task-1"
        task_dir.mkdir(parents=True)
        archive_path = task_dir / "payload.zip"
        archive_path.write_bytes(payload)
        return DownloadTask(
            id="task-1",
            url="https://example.invalid/archive.zip",
            filename="archive.zip",
            tags=["eh_archive"],
            tag_data={"gid": "1", "token": "abc", "gallery_details": {"title": "Gallery"}},
            temp_dir=task_dir.as_posix(),
            part_path=(task_dir / "payload.part").as_posix(),
            final_path=archive_path.as_posix(),
        )

    def test_invalid_archive_preserves_source_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloads = Mock()
            task = self._task(root, b"not a zip")
            manager = self._manager(root, downloads)

            manager.handle_download_completed(task)

            self.assertTrue(task.final_file_path.is_file())
            self.assertEqual(list(manager.archive_dir.glob(".*.staging")), [])
            downloads.mark_consumed.assert_called_once()
            self.assertIsNotNone(downloads.mark_consumed.call_args.kwargs.get("consume_error"))

    def test_valid_archive_is_committed_before_source_is_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_dir = root / "source"
            task_dir.mkdir()
            archive = task_dir / "archive.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("001.jpg", b"image")
            task = self._task(root, archive.read_bytes())
            downloads = Mock()
            manager = self._manager(root, downloads)

            manager.handle_download_completed(task)

            self.assertFalse(task.final_file_path.exists())
            gallery_dirs = [path for path in manager.archive_dir.iterdir() if path.is_dir()]
            self.assertEqual(len(gallery_dirs), 1)
            self.assertTrue((gallery_dirs[0] / "gallery.json").is_file())
            self.assertTrue((gallery_dirs[0] / "archive.zip").is_file())
            downloads.mark_consumed.assert_called_once_with(task.id)

    def test_repeated_completion_reuses_committed_gallery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloads = Mock()
            with zipfile.ZipFile(root / "source.zip", "w") as archive:
                archive.writestr("001.jpg", b"image")
            task = self._task(root, (root / "source.zip").read_bytes())
            manager = self._manager(root, downloads)
            manager.handle_download_completed(task)
            committed = [path for path in manager.archive_dir.iterdir() if path.is_dir()]

            task.final_file_path.write_bytes((root / "source.zip").read_bytes())
            manager.handle_download_completed(task)

            self.assertEqual([path for path in manager.archive_dir.iterdir() if path.is_dir()], committed)
            self.assertFalse(task.final_file_path.exists())

    def test_repeated_completion_reuses_uniquely_named_gallery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloads = Mock()
            with zipfile.ZipFile(root / "source.zip", "w") as archive:
                archive.writestr("10.jpg", b"ten")
                archive.writestr("2.jpg", b"two")
            task = self._task(root, (root / "source.zip").read_bytes())
            manager = self._manager(root, downloads)
            base_dir = manager.archive_dir / manager._eh_archive_folder_name("1", "abc", "Gallery")
            base_dir.mkdir(parents=True)
            (base_dir / "occupied.txt").write_text("occupied", encoding="utf-8")

            manager.handle_download_completed(task)
            committed = manager._find_committed_gallery(task.id)
            self.assertIsNotNone(committed)
            self.assertNotEqual(committed, base_dir)
            self.assertEqual((committed / "thumb.jpg").read_bytes(), b"two")

            task.final_file_path.write_bytes((root / "source.zip").read_bytes())
            manager.handle_download_completed(task)

            committed_dirs = [
                path for path in manager.archive_dir.iterdir()
                if path.is_dir() and manager._is_committed_gallery(path, task.id)
            ]
            self.assertEqual(committed_dirs, [committed])

    def test_corrupt_gallery_json_is_quarantined_without_deleting_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gallery_dir = root / "Downloads" / "EHArchieve" / "gallery"
            gallery_dir.mkdir(parents=True)
            archive = gallery_dir / "archive.zip"
            archive.write_bytes(b"archive")
            (gallery_dir / "gallery.json").write_text("{broken", encoding="utf-8")
            manager = self._manager(root, Mock())

            self.assertEqual(manager.scan_local_galleries(force=True), [])

            self.assertTrue(archive.is_file())
            self.assertEqual(len(list(gallery_dir.glob("gallery.json.corrupt-*"))), 1)

    def test_gallery_json_path_traversal_is_quarantined(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gallery_dir = root / "Downloads" / "EHArchieve" / "gallery"
            gallery_dir.mkdir(parents=True)
            metadata = {
                "schema_version": 1,
                "source": {"gid": "1", "token": "abc"},
                "files": {"archive": "../archive.zip", "cover": ""},
            }
            (gallery_dir / "gallery.json").write_text(json.dumps(metadata), encoding="utf-8")
            manager = self._manager(root, Mock())

            self.assertEqual(manager.scan_local_galleries(force=True), [])
            self.assertEqual(len(list(gallery_dir.glob("gallery.json.corrupt-*"))), 1)


if __name__ == "__main__":
    unittest.main()
