import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock, patch

from core.data.data_db import AppDataDB
from core.download.manager import DownloadManager


class DownloadManagerLifecycleTests(unittest.TestCase):
    def _manager(self, root: Path) -> DownloadManager:
        return DownloadManager(
            downloading_dir=root / "Downloading",
            data_db=AppDataDB(root / "data.db"),
            ensure_dirs=lambda: root.mkdir(parents=True, exist_ok=True),
            stream_get=Mock(),
        )

    def test_constructor_does_not_create_executor_or_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "storage"
            with patch("core.download.manager.ThreadPoolExecutor") as executor_class:
                manager = self._manager(root)
                executor_class.assert_not_called()
                self.assertFalse(root.exists())
                self.assertIsNone(manager._executor)

    def test_initialize_shutdown_and_reinitialize_executor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "storage"
            first_executor = Mock()
            second_executor = Mock()
            with patch(
                "core.download.manager.ThreadPoolExecutor",
                side_effect=[first_executor, second_executor],
            ) as executor_class:
                manager = self._manager(root)
                manager.initialize()
                self.assertIs(manager._executor, first_executor)
                self.assertTrue((root / "data.db").is_file())

                manager.initialize()
                executor_class.assert_called_once()

                manager.shutdown(wait=False, cancel_futures=True)
                first_executor.shutdown.assert_called_once_with(
                    wait=False,
                    cancel_futures=True,
                )
                self.assertIsNone(manager._executor)

                manager.initialize()
                self.assertIs(manager._executor, second_executor)
                self.assertEqual(executor_class.call_count, 2)
                manager.shutdown()

    def test_initialize_creates_database_parent_even_when_callback_does_not(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "Data" / "data.db"
            manager = DownloadManager(
                downloading_dir=root / "Downloads" / "Downloading",
                data_db=AppDataDB(db_path, ensure_dirs=lambda: None),
                ensure_dirs=lambda: None,
                stream_get=Mock(),
            )
            try:
                manager.initialize()
                self.assertTrue(db_path.is_file())
            finally:
                manager.shutdown()

    def test_initialize_quarantines_corrupt_database_and_rebuilds_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "Data" / "data.db"
            db_path.parent.mkdir(parents=True)
            db_path.write_bytes(b"not a sqlite database")
            manager = DownloadManager(
                downloading_dir=root / "Downloads" / "Downloading",
                data_db=AppDataDB(db_path, ensure_dirs=lambda: None),
                ensure_dirs=lambda: None,
                stream_get=Mock(),
            )
            try:
                manager.initialize()
                self.assertEqual(manager.list_tasks(), [])
                quarantined = list(db_path.parent.glob("data.db.corrupt-*"))
                self.assertEqual(len(quarantined), 1)
                self.assertEqual(quarantined[0].read_bytes(), b"not a sqlite database")
            finally:
                manager.shutdown()

    def test_task_snapshot_recovers_task_missing_from_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = self._manager(root)
            try:
                task = manager.create_task("https://example.invalid/archive.zip", "archive.zip")
                self.assertTrue(task.task_file_path.is_file())
            finally:
                manager.shutdown()

            db_path = root / "data.db"
            db_path.unlink()
            for suffix in ("-wal", "-shm"):
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)

            recovered = self._manager(root)
            try:
                recovered.initialize()
                restored = recovered.get_task(task.id)
                self.assertIsNotNone(restored)
                self.assertEqual(restored.url, task.url)
            finally:
                recovered.shutdown()

    def test_corrupt_task_snapshot_does_not_block_initialization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_dir = root / "Downloading" / "broken"
            task_dir.mkdir(parents=True)
            (task_dir / "task.json").write_text("{broken", encoding="utf-8")
            manager = self._manager(root)
            try:
                manager.initialize()
                self.assertEqual(manager.list_tasks(), [])
                self.assertEqual(len(list(task_dir.glob("task.json.corrupt-*"))), 1)
            finally:
                manager.shutdown()

    def test_snapshot_paths_are_rebuilt_inside_task_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = self._manager(root)
            try:
                task = manager.create_task("https://example.invalid/archive.zip", "archive.zip")
            finally:
                manager.shutdown()
            payload = task.to_dict()
            payload["temp_dir"] = "/tmp/outside"
            payload["part_path"] = "/tmp/outside.part"
            payload["final_path"] = "/tmp/outside.zip"
            task.task_file_path.write_text(__import__("json").dumps(payload), encoding="utf-8")
            db_path = root / "data.db"
            db_path.unlink()
            for suffix in ("-wal", "-shm"):
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)

            recovered = self._manager(root)
            try:
                recovered.initialize()
                restored = recovered.get_task(task.id)
                self.assertEqual(restored.temp_dir_path.resolve(), task.task_file_path.parent.resolve())
                self.assertEqual(restored.final_file_path.parent.resolve(), task.task_file_path.parent.resolve())
            finally:
                recovered.shutdown()

    def test_start_task_does_not_submit_duplicate_worker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(Path(temp_dir))
            manager.initialize()
            executor = Mock()
            future = Future()
            executor.submit.return_value = future
            manager._executor = executor
            task = manager.create_task("https://example.invalid/archive.zip", "archive.zip")

            manager.start_task(task.id)
            manager.start_task(task.id)

            executor.submit.assert_called_once()
            future.cancel()
            manager.shutdown(wait=False, cancel_futures=True)

    def test_running_delete_waits_for_worker_before_removing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = self._manager(Path(temp_dir))
            manager.initialize()
            executor = Mock()
            future = Future()
            executor.submit.return_value = future
            manager._executor = executor
            task = manager.create_task("https://example.invalid/archive.zip", "archive.zip")
            manager.start_task(task.id)

            manager.delete_task(task.id)

            self.assertTrue(task.temp_dir_path.exists())
            self.assertIsNotNone(manager.get_task(task.id))
            future.set_result(None)
            self.assertFalse(task.temp_dir_path.exists())
            self.assertIsNone(manager.get_task(task.id))
            manager.shutdown(wait=False, cancel_futures=True)

    def test_download_response_is_closed(self):
        class Response:
            status_code = 200
            url = "https://example.invalid/archive.zip"
            headers = {"Content-Length": "4"}

            def __init__(self):
                self.closed = False

            def iter_content(self, chunk_size):
                yield b"data"

            def close(self):
                self.closed = True

        with tempfile.TemporaryDirectory() as temp_dir:
            response = Response()
            manager = DownloadManager(
                downloading_dir=Path(temp_dir) / "Downloading",
                data_db=AppDataDB(Path(temp_dir) / "data.db"),
                ensure_dirs=lambda: None,
                stream_get=lambda *_args, **_kwargs: response,
            )
            task = manager.create_task("https://example.invalid/archive.zip", "archive.zip")

            manager._download_impl(task.id)

            self.assertTrue(response.closed)
            self.assertEqual(manager.get_task(task.id).status, "completed")
            manager.shutdown()


if __name__ == "__main__":
    unittest.main()
