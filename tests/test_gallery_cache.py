import tempfile
import unittest
from pathlib import Path

from core.api.dto import CommentDTO, MediaDetailDTO, RelatedMediaDTO
from core.cache.gallery_cache import EHGalleryCache
from core.provider.ehgrabber import ThumbnailItem, ThumbnailsResult


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

    def test_detail_dto_round_trips_without_provider_objects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "Cache" / "cache.db"
            cache = EHGalleryCache(db_path, ensure_dirs=lambda: None)
            url = "https://e-hentai.org/g/1/token"
            detail = MediaDetailDTO(
                provider="ehentai",
                id=url,
                title="Gallery",
                comments=[CommentDTO(id="c1", author="user", content="text")],
                related=[RelatedMediaDTO(id="2", page_url="next", relation="newer_version")],
                metadata={"file_size": "10 MiB"},
            )
            thumbnails = ThumbnailsResult(
                thumbnails=["thumb"],
                urls=["page"],
                items=[ThumbnailItem("thumb", "page")],
            )

            cache.put(url, detail, thumbnails)
            result = cache.get(url)

            self.assertIsNotNone(result)
            self.assertEqual(result.details.comments[0].author, "user")
            self.assertEqual(result.details.newer_versions[0].page_url, "next")
            self.assertEqual(result.details.file_size, "10 MiB")


if __name__ == "__main__":
    unittest.main()
