import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app import storage
from app.download_manager import _create_download_manager
from app.gallery_cache import _create_gallery_cache
from app.history import _create_history_repository
from app.image_cache import _create_image_cache_db
from app.lazy import LazyProxy
from app.local_gallery_manager import _create_local_gallery_manager
from core.storage import AppStoragePaths, StorageLayout


class StorageAdapterTests(unittest.TestCase):
    def test_lazy_proxy_creates_instance_on_first_access(self):
        instance = Mock()
        factory = Mock(return_value=instance)
        proxy = LazyProxy(factory)

        factory.assert_not_called()
        self.assertIs(proxy.resolve(), instance)
        self.assertIs(proxy.resolve(), instance)
        factory.assert_called_once_with()

    def test_proxy_forwards_get_method_to_instance(self):
        instance = Mock()
        proxy = LazyProxy(lambda: instance)

        proxy.get("key")

        instance.get.assert_called_once_with("key")

    def test_adapter_factories_use_current_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            layout = StorageLayout.from_paths(
                AppStoragePaths(
                    data=root / "Data",
                    cache=root / "Cache",
                    downloads=root / "Downloads",
                    temp=root / "Temp",
                )
            )
            previous = storage.get_storage_layout()
            try:
                storage.configure_storage(layout)
                history = _create_history_repository()
                gallery_cache = _create_gallery_cache()
                image_cache = _create_image_cache_db()
                downloads = _create_download_manager()
                local_galleries = _create_local_gallery_manager()

                self.assertEqual(history.data_db.db_path, layout.data_db)
                self.assertEqual(gallery_cache.db_path, layout.cache_db)
                self.assertEqual(image_cache.db_path, layout.cache_db)
                self.assertEqual(image_cache.files_dir, layout.cache_files)
                self.assertEqual(downloads.downloading_dir, layout.downloading_dir)
                self.assertEqual(downloads.data_db.db_path, layout.data_db)
                self.assertEqual(local_galleries.archive_dir, layout.eh_archive_dir)
                self.assertEqual(local_galleries.data_db.db_path, layout.data_db)
                for path in (layout.paths.data, layout.paths.cache, layout.paths.downloads, layout.paths.temp):
                    self.assertFalse(path.exists())
            finally:
                storage.configure_storage(previous)


if __name__ == "__main__":
    unittest.main()
