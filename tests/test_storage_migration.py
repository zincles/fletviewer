import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.storage import AppStoragePaths, StorageLayout
from core.storage_migration import MARKER_NAME, migrate_legacy_storage


class StorageMigrationTests(unittest.TestCase):
    def test_migrates_legacy_root_into_four_domains(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "FletViewer"
            root.mkdir()
            (root / "config.json").write_text('{"eh":{},"app":{"theme_mode":"dark"}}', encoding="utf-8")
            data_db = root / "data.db"
            self._create_data_db(
                data_db,
                dir_path=str(root / "Downloads" / "EHArchieve" / "gallery"),
                payload_path=str(root / "Downloads" / "Downloading" / "task1" / "payload.zip"),
            )
            cache_db = root / "cache.db"
            self._create_simple_db(cache_db)
            cache_file = root / "Cache" / "ab" / "cd" / "abcd.webp"
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b"img")
            archive_dir = root / "Downloads" / "EHArchieve" / "gallery"
            archive_dir.mkdir(parents=True)
            (archive_dir / "gallery.json").write_text("{}", encoding="utf-8")
            part = root / "Downloads" / "Downloading" / "task1" / "payload.part"
            part.parent.mkdir(parents=True)
            part.write_bytes(b"part")

            layout = StorageLayout.from_paths(
                AppStoragePaths(
                    data=root / "Data",
                    cache=root / "Cache",
                    downloads=root / "Downloads",
                    temp=root / "Temp",
                )
            )
            result = migrate_legacy_storage(layout, legacy_home=root)

            self.assertTrue(result.performed)
            self.assertTrue((layout.paths.data / MARKER_NAME).exists())
            self.assertTrue(layout.config_file.exists())
            self.assertTrue(layout.data_db.exists())
            self.assertTrue(layout.cache_db.exists())
            self.assertTrue((layout.cache_files / "ab" / "cd" / "abcd.webp").exists())
            self.assertTrue((layout.eh_archive_dir / "gallery" / "gallery.json").exists())
            self.assertTrue((layout.downloading_dir / "task1" / "payload.part").exists())
            self.assertFalse((root / "config.json").exists())
            self.assertFalse((root / "data.db").exists())
            self.assertFalse((root / "cache.db").exists())

            conn = sqlite3.connect(layout.data_db)
            try:
                dir_path = conn.execute("SELECT dir_path FROM local_galleries").fetchone()[0]
                payload = conn.execute("SELECT payload_json FROM download_tasks").fetchone()[0]
            finally:
                conn.close()
            # Same-path downloads domain should keep existing absolute paths intact.
            self.assertTrue(
                dir_path.endswith(str(Path("EHArchieve") / "gallery"))
                or dir_path.replace("\\", "/").endswith("EHArchieve/gallery")
            )
            self.assertIn("payload.zip", payload)
            # Guard against corrupted drive-letter duplication from bad rewrites.
            self.assertLessEqual(dir_path.count(":\\"), 1)

            second = migrate_legacy_storage(layout, legacy_home=root)
            self.assertFalse(second.performed)

    def test_existing_target_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "FletViewer"
            root.mkdir()
            (root / "config.json").write_text('{"eh":{},"app":{"theme_mode":"light"}}', encoding="utf-8")
            layout = StorageLayout.from_paths(
                AppStoragePaths(root / "Data", root / "Cache", root / "Downloads", root / "Temp")
            )
            layout.paths.data.mkdir(parents=True)
            layout.config_file.write_text('{"eh":{},"app":{"theme_mode":"dark"}}', encoding="utf-8")

            migrate_legacy_storage(layout, legacy_home=root)

            self.assertEqual(json.loads(layout.config_file.read_text(encoding="utf-8"))["app"]["theme_mode"], "dark")
            self.assertTrue((root / "config.json").exists())

    def test_no_legacy_home_writes_marker_without_moving(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            layout = StorageLayout.from_paths(
                AppStoragePaths(root / "Data", root / "Cache", root / "Downloads", root / "Temp")
            )
            result = migrate_legacy_storage(layout, legacy_home=root / "missing")
            self.assertFalse(result.performed)
            self.assertTrue((layout.paths.data / MARKER_NAME).exists())

    def _create_simple_db(self, path: Path) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO t(id) VALUES (1)")
            conn.commit()
        finally:
            conn.close()

    def _create_data_db(self, path: Path, *, dir_path: str, payload_path: str) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """
                CREATE TABLE download_tasks (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE local_galleries (
                    provider TEXT,
                    gid TEXT,
                    token TEXT,
                    dir_path TEXT,
                    PRIMARY KEY (provider, gid, token)
                )
                """
            )
            conn.execute(
                "INSERT INTO download_tasks(id, payload_json) VALUES (?, ?)",
                ("task1", json.dumps({"final_path": payload_path})),
            )
            conn.execute(
                "INSERT INTO local_galleries(provider, gid, token, dir_path) VALUES (?, ?, ?, ?)",
                ("ehentai", "1", "abc", dir_path),
            )
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
