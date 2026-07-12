import tempfile
import unittest
from pathlib import Path

from core.cache.image_cache_db import ImageCacheDB


class ImageCacheRecoveryTests(unittest.TestCase):
    def test_corrupt_database_is_quarantined_and_rebuilt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Cache"
            db_path = root / "cache.db"
            root.mkdir(parents=True)
            db_path.write_bytes(b"not a sqlite database")
            cache = ImageCacheDB(
                cache_dir=root,
                files_dir=root / "files",
                db_path=db_path,
                legacy_index_path=root / "legacy-index.json",
            )

            self.assertIsNone(cache.get_cached_filename("https://example.invalid/image.jpg"))

            quarantined = list(root.glob("cache.db.corrupt-*"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].read_bytes(), b"not a sqlite database")

    def test_zero_byte_cache_file_is_removed_from_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Cache"
            cache = ImageCacheDB(
                cache_dir=root,
                files_dir=root / "files",
                db_path=root / "cache.db",
                legacy_index_path=root / "legacy-index.json",
            )
            url = "https://example.invalid/image.jpg"
            filename = cache.filename_for_url(url, mime="image/jpeg")
            path = cache.path_for_filename(filename)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"")
            cache.put_cached_filename(url, filename)

            self.assertIsNone(cache.get_cached_path(url))
            self.assertIsNone(cache.get_cached_filename(url))


if __name__ == "__main__":
    unittest.main()
