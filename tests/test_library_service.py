import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from core.api import MediaItemDTO
from core.api.errors import BackendError
from core.api.library import HistoryService, LocalGalleryService
from core.data.history import HistoryEntry


class FakeLocalGalleryManager:
    def __init__(self, galleries):
        self.galleries = galleries

    def scan_local_galleries(self, *, force=False):
        return list(self.galleries)


class FakeHistoryRepository:
    def __init__(self):
        self.entries = []
        self.next_id = 1

    def record(self, entry):
        self.entries = [item for item in self.entries if not (
            item.provider == entry.provider and item.kind == entry.kind and item.source_id == entry.source_id
        )]
        entry.id = self.next_id
        self.next_id += 1
        self.entries.insert(0, entry)
        return entry

    def list_entries(self, *, kind=None, limit=500):
        values = [entry for entry in self.entries if not kind or entry.kind == kind]
        return values[:limit]

    def clear(self, *, kind=None):
        self.entries = [entry for entry in self.entries if kind and entry.kind != kind]


class LibraryServiceTests(unittest.TestCase):
    def test_local_gallery_dto_and_resources_hide_internal_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "gallery"
            root.mkdir()
            archive_path = root / "archive.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("10.jpg", b"ten")
                archive.writestr("2.jpg", b"two")
            (root / "thumb.jpg").write_bytes(b"cover")
            gallery = SimpleNamespace(dir_path=root, metadata={
                "provider": "ehentai",
                "source": {"gid": "123", "token": "token", "gallery_url": "https://e-hentai.org/g/123/token"},
                "gallery": {"title": "Gallery", "max_page": 2, "tags": {"artist": ["name"]}},
                "archive": {"title": "Original", "bytes_total": archive_path.stat().st_size},
                "files": {"archive": "archive.zip", "cover": "thumb.jpg"},
                "created_at": "now",
            })
            service = LocalGalleryService(FakeLocalGalleryManager([gallery]))

            dto = service.list_galleries()[0]
            pages = service.list_pages(dto.id)
            cover = service.get_cover(dto.id)
            image = service.read_page(dto.id, pages[0].member_id)
            serialized = json.dumps({
                "gallery": dto.to_dict(),
                "pages": [page.to_dict() for page in pages],
                "cover": cover.to_dict(),
                "image": image.to_dict(),
            })

            self.assertEqual(dto.id, "ehentai:123:token")
            self.assertEqual([page.member_id for page in pages], ["2.jpg", "10.jpg"])
            self.assertEqual(image.byte_length, 3)
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("archive_path", serialized)

    def test_local_gallery_rejects_metadata_path_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "gallery"
            root.mkdir()
            gallery = SimpleNamespace(dir_path=root, metadata={
                "provider": "ehentai",
                "source": {"gid": "1", "token": "token"},
                "gallery": {"title": "Gallery"},
                "files": {"archive": "../outside.zip"},
            })
            service = LocalGalleryService(FakeLocalGalleryManager([gallery]))
            gallery_id = service.list_galleries()[0].id

            with self.assertRaises(BackendError) as raised:
                service.list_pages(gallery_id)

            self.assertEqual(raised.exception.to_dict()["code"], "local_file_missing")

    def test_history_round_trip_uses_media_dto_and_deduplicates_source(self):
        repository = FakeHistoryRepository()
        service = HistoryService(repository)
        first = MediaItemDTO("ehentai", "url-1", "First", thumbnail_url="cover-1")
        second = MediaItemDTO("ehentai", "url-2", "Second", thumbnail_url="cover-2")

        service.record_media(first, source_id="123", created_at="one")
        service.record_media(second, source_id="123", created_at="two")
        items = service.list_items()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].media.title, "Second")
        self.assertEqual(items[0].source_id, "123")
        json.dumps(items[0].to_dict())

    def test_legacy_comic_history_maps_to_media_dto(self):
        repository = FakeHistoryRepository()
        repository.entries = [HistoryEntry(
            id=1,
            provider="ehentai",
            kind="gallery",
            source_id="123",
            title="Legacy",
            url="https://e-hentai.org/g/123/token",
            metadata={"cover": "cover.jpg", "stars": 4.5, "max_page": 20, "tags": ["tag"]},
            created_at="now",
        )]

        item = HistoryService(repository).list_items()[0]

        self.assertEqual(item.media.thumbnail_url, "cover.jpg")
        self.assertEqual(item.media.stars, 4.5)
        self.assertEqual(item.media.page_count, 20)


if __name__ == "__main__":
    unittest.main()
