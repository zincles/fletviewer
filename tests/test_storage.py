import tempfile
import unittest
from pathlib import Path

from app import storage
from core.storage import AppStoragePaths, StorageLayout


class StorageDirectoryTests(unittest.TestCase):
    def test_gallery_detail_preview_rows_validation(self):
        original = storage.load_app_config
        try:
            storage.load_app_config = lambda: {"gallery_detail_preview_rows": "all"}
            self.assertIsNone(storage.get_gallery_detail_preview_rows())
            storage.load_app_config = lambda: {"gallery_detail_preview_rows": "4"}
            self.assertEqual(storage.get_gallery_detail_preview_rows(), 4)
            storage.load_app_config = lambda: {"gallery_detail_preview_rows": "invalid"}
            self.assertEqual(storage.get_gallery_detail_preview_rows(), 3)
        finally:
            storage.load_app_config = original

    def test_directory_initialization_never_removes_legacy_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "FletViewer"
            legacy_data = root / "Data"
            config_dir = root / "Config"
            gallery_cache = legacy_data / "GalleryCache"
            image_cache = legacy_data / "ImageCache"
            cache_files = root / "Cache"
            downloads = root / "Downloads"
            downloading = downloads / "Downloading"
            archive = downloads / "EHArchieve"

            sentinels = [
                legacy_data / "data.txt",
                config_dir / "config.txt",
                gallery_cache / "gallery.txt",
                image_cache / "image.txt",
            ]
            for sentinel in sentinels:
                sentinel.parent.mkdir(parents=True, exist_ok=True)
                sentinel.write_text("keep", encoding="utf-8")

            layout = StorageLayout(
                paths=AppStoragePaths(
                    data=root,
                    cache=root,
                    downloads=downloads,
                    temp=root / "Temp",
                ),
                config_file=root / "config.json",
                data_db=root / "data.db",
                cache_db=root / "cache.db",
                cache_files=cache_files,
                downloading_dir=downloading,
                eh_archive_dir=archive,
                debug_log_file=root / "Temp" / "debug_log.md",
                import_staging_dir=root / "Temp" / "import",
                export_staging_dir=root / "Temp" / "export",
            )
            previous = storage.get_storage_layout()
            try:
                storage.configure_storage(layout)
                storage.ensure_dirs()
                storage.ensure_gallery_cache_dirs()
                storage.ensure_image_cache_dirs()
                storage.ensure_download_dirs()
            finally:
                storage.configure_storage(previous)

            for sentinel in sentinels:
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertTrue(cache_files.is_dir())
            self.assertTrue(downloading.is_dir())
            self.assertTrue(archive.is_dir())

    def test_configured_layout_controls_config_and_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = AppStoragePaths(
                data=root / "Data",
                cache=root / "Cache",
                downloads=root / "Downloads",
                temp=root / "Temp",
            )
            layout = StorageLayout.from_paths(paths)
            previous = storage.get_storage_layout()
            try:
                storage.configure_storage(layout)
                storage.save_app_config({"theme_mode": "dark"})
                storage.ensure_image_cache_dirs()
                storage.ensure_download_dirs()

                self.assertTrue(layout.config_file.is_file())
                self.assertEqual(storage.load_app_config()["theme_mode"], "dark")
                self.assertTrue(layout.cache_files.is_dir())
                self.assertTrue(layout.downloading_dir.is_dir())
                self.assertTrue(layout.eh_archive_dir.is_dir())
            finally:
                storage.configure_storage(previous)

    def test_corrupt_config_is_quarantined_and_defaults_are_returned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            layout = StorageLayout.from_paths(
                AppStoragePaths(root / "Data", root / "Cache", root / "Downloads", root / "Temp")
            )
            layout.config_file.parent.mkdir(parents=True)
            layout.config_file.write_text("{broken", encoding="utf-8")
            previous = storage.get_storage_layout()
            try:
                storage.configure_storage(layout)
                config = storage.load_app_config()
                self.assertEqual(config, storage.APP_CONFIG_DEFAULTS)
                self.assertFalse(layout.config_file.exists())
                quarantined = list(layout.config_file.parent.glob("config.json.corrupt-*"))
                self.assertEqual(len(quarantined), 1)
                self.assertEqual(quarantined[0].read_text(encoding="utf-8"), "{broken")
            finally:
                storage.configure_storage(previous)

    def test_non_object_config_is_quarantined(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            layout = StorageLayout.from_paths(
                AppStoragePaths(root / "Data", root / "Cache", root / "Downloads", root / "Temp")
            )
            layout.config_file.parent.mkdir(parents=True)
            layout.config_file.write_text("[]", encoding="utf-8")
            previous = storage.get_storage_layout()
            try:
                storage.configure_storage(layout)
                self.assertEqual(storage.load_app_config(), storage.APP_CONFIG_DEFAULTS)
                self.assertEqual(len(list(layout.config_file.parent.glob("config.json.corrupt-*"))), 1)
            finally:
                storage.configure_storage(previous)

    def test_save_config_replaces_file_without_leaving_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            layout = StorageLayout.from_paths(
                AppStoragePaths(root / "Data", root / "Cache", root / "Downloads", root / "Temp")
            )
            previous = storage.get_storage_layout()
            try:
                storage.configure_storage(layout)
                storage.save_app_config({"theme_mode": "dark"})
                self.assertEqual(storage.load_app_config()["theme_mode"], "dark")
                self.assertEqual(list(layout.config_file.parent.glob(".config.json.*.tmp")), [])
            finally:
                storage.configure_storage(previous)


if __name__ == "__main__":
    unittest.main()
