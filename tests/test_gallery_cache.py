import tempfile
import unittest
from pathlib import Path

from core.cache.gallery_cache import EHGalleryCache


class GalleryCacheInitializationTests(unittest.TestCase):
    def test_clear_creates_database_parent_even_when_callback_does_not(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "Cache" / "cache.db"
            cache = EHGalleryCache(db_path, ensure_dirs=lambda: None)

            cache.clear()

            self.assertTrue(db_path.is_file())

    def test_clear_quarantines_corrupt_database_and_rebuilds_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "Cache" / "cache.db"
            db_path.parent.mkdir(parents=True)
            db_path.write_bytes(b"not a sqlite database")
            cache = EHGalleryCache(db_path, ensure_dirs=lambda: None)

            cache.clear()

            self.assertTrue(db_path.is_file())
            quarantined = list(db_path.parent.glob("cache.db.corrupt-*"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].read_bytes(), b"not a sqlite database")


if __name__ == "__main__":
    unittest.main()
