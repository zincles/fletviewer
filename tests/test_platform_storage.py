import tempfile
import unittest
from pathlib import Path

from app.platform_storage import resolve_storage
from core.storage import AppStoragePaths, StorageLayout


class StoragePathModelTests(unittest.TestCase):
    def test_layout_derives_all_paths_from_domains(self):
        paths = AppStoragePaths(
            data=Path("/app/data"),
            cache=Path("/app/cache"),
            downloads=Path("/app/downloads"),
            temp=Path("/app/temp"),
        )
        layout = StorageLayout.from_paths(paths)

        self.assertEqual(layout.config_file, paths.data / "config.json")
        self.assertEqual(layout.data_db, paths.data / "data.db")
        self.assertEqual(layout.cache_db, paths.cache / "cache.db")
        self.assertEqual(layout.cache_files, paths.cache / "files")
        self.assertEqual(layout.downloading_dir, paths.downloads / "Downloading")
        self.assertEqual(layout.eh_archive_dir, paths.downloads / "EHArchieve")
        self.assertEqual(layout.debug_log_file, paths.temp / "debug_log.md")

    def test_resolver_has_no_directory_creation_side_effect(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            resolved = resolve_storage({}, cwd=cwd)

            self.assertEqual(resolved.paths.data, cwd / "FletViewer" / "Data")
            self.assertEqual(resolved.paths.cache, cwd / "FletViewer" / "Cache")
            self.assertEqual(resolved.paths.downloads, cwd / "FletViewer" / "Downloads")
            self.assertEqual(resolved.paths.temp, cwd / "FletViewer" / "Temp")
            self.assertFalse((cwd / "FletViewer").exists())
            self.assertEqual(set(resolved.sources.values()), {"desktop fallback"})

    def test_flet_roots_separate_persistent_and_clearable_domains(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_root = root / "flet-data"
            temp_root = root / "flet-temp"
            resolved = resolve_storage(
                {
                    "FLET_APP_STORAGE_DATA": str(data_root),
                    "FLET_APP_STORAGE_TEMP": str(temp_root),
                    "FLETVIEWER_HOME": str(root / "ignored"),
                }
            )

            self.assertEqual(resolved.paths.data, data_root / "Data")
            self.assertEqual(resolved.paths.downloads, data_root / "Downloads")
            self.assertEqual(resolved.paths.cache, temp_root / "Cache")
            self.assertEqual(resolved.paths.temp, temp_root / "Temp")
            self.assertEqual(resolved.sources["data"], "FLET_APP_STORAGE_DATA")
            self.assertEqual(resolved.sources["cache"], "FLET_APP_STORAGE_TEMP")

    def test_explicit_home_is_resolved_against_supplied_cwd(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path(temp_dir)
            resolved = resolve_storage({"FLETVIEWER_HOME": "custom"}, cwd=cwd)

            self.assertEqual(resolved.paths.data, cwd / "custom" / "Data")
            self.assertEqual(resolved.paths.cache, cwd / "custom" / "Cache")
            self.assertEqual(set(resolved.sources.values()), {"FLETVIEWER_HOME"})


if __name__ == "__main__":
    unittest.main()
