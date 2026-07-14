import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.api.backend import BackendFacade
from core.api.errors import BackendError
from core.provider.booru import BooruPost, BooruSearchResult, ImageVariant
from core.provider.ehgrabber import Comment, Comic, ComicDetails, GalleryVersion, SearchResult
from core.provider.pixiv import PixivIllust, PixivSearchResult, PixivUser


class BackendFacadeTests(unittest.TestCase):
    def setUp(self):
        self.eh_client = Mock()
        self.pixiv_client = Mock()
        self.booru_client = Mock()
        self.backend = BackendFacade(
            get_eh_client=Mock(return_value=self.eh_client),
            get_pixiv_client=Mock(return_value=self.pixiv_client),
            get_booru_client=Mock(return_value=self.booru_client),
        )

    def test_eh_search_maps_to_json_safe_page(self):
        self.eh_client.search.return_value = SearchResult(
            comics=[Comic("https://e-hentai.org/g/1/t", "Gallery", "cover.jpg", tags=["artist:test"], stars=4.5)],
            next_url="next",
        )

        result = self.backend.search_eh("test")

        self.assertEqual(result.items[0].provider, "ehentai")
        self.assertEqual(result.items[0].metadata["stars"], 4.5)
        self.assertEqual(result.next_cursor, "next")
        json.dumps(result.to_dict())

    def test_pixiv_search_does_not_expose_raw_response(self):
        self.pixiv_client.search_illusts.return_value = PixivSearchResult(
            illusts=[PixivIllust("2", "Illust", user=PixivUser("3", "Artist"), raw={"secret_shape": object()})],
            next_url="next",
            query="cat",
        )

        result = self.backend.search_pixiv("cat")
        payload = result.to_dict()

        self.assertEqual(payload["items"][0]["creator_name"], "Artist")
        self.assertNotIn("raw", payload["items"][0])
        json.dumps(payload)

    def test_booru_search_preserves_provider_metadata(self):
        self.booru_client.search_posts.return_value = BooruSearchResult(
            provider="demo",
            posts=[
                BooruPost(
                    "demo",
                    4,
                    original=ImageVariant("image.jpg", 1200, 800),
                    tags={"artist": ["name"]},
                    rating="q",
                    score=12,
                    metadata={"md5": "abc"},
                    raw=object(),
                )
            ],
            next_page=2,
        )

        result = self.backend.search_booru("demo", "tag")

        self.assertEqual(result.items[0].tags, {"artist": ["name"]})
        self.assertEqual(result.items[0].metadata, {"md5": "abc"})
        self.assertEqual(result.next_cursor, 2)
        json.dumps(result.to_dict())

    def test_provider_exception_becomes_stable_error(self):
        self.pixiv_client.search_illusts.side_effect = RuntimeError("Cookie 已失效")

        with self.assertRaises(BackendError) as raised:
            self.backend.search_pixiv("cat")

        self.assertEqual(raised.exception.to_dict()["code"], "authentication_required")
        self.assertEqual(raised.exception.to_dict()["provider"], "pixiv")

    def test_pixiv_feed_maps_ranking(self):
        self.pixiv_client.get_ranking.return_value = SimpleNamespace(
            illusts=[PixivIllust("5", "Ranked")],
            next_url="rank-2",
        )

        result = self.backend.get_pixiv_feed("ranking")

        self.assertEqual(result.items[0].id, "5")
        self.assertEqual(result.next_cursor, "rank-2")

    def test_eh_detail_maps_comments_versions_and_metadata(self):
        self.eh_client.load_comic_info.return_value = ComicDetails(
            id="https://e-hentai.org/g/1/token",
            title="Gallery",
            cover="cover.jpg",
            tags={"artist": ["name"]},
            stars=4.5,
            max_page=20,
            comments=[Comment("c1", "hello", "today", "user", score=2)],
            newer_versions=[GalleryVersion("https://e-hentai.org/g/2/new", gid="2", token="new", title="New")],
            parent="https://e-hentai.org/g/0/old",
            file_size="10 MiB",
        )

        result = self.backend.get_media_detail("ehentai", "https://e-hentai.org/g/1/token")
        payload = result.to_dict()

        self.assertEqual(result.comments[0].author, "user")
        self.assertEqual(result.newer_versions[0].title, "New")
        self.assertEqual(result.file_size, "10 MiB")
        self.assertEqual(payload["metadata"]["parent_url"], "https://e-hentai.org/g/0/old")
        json.dumps(payload)

    def test_pixiv_detail_does_not_expose_raw(self):
        self.pixiv_client.get_illust_detail.return_value = PixivIllust(
            "7",
            "Detail",
            user=PixivUser("8", "Artist"),
            image_urls={"large": "large.jpg"},
            meta_pages=[{"original": "page.jpg"}],
            raw={"response": object()},
        )

        payload = self.backend.get_pixiv_detail("7").to_dict()

        self.assertEqual(payload["creator_name"], "Artist")
        self.assertNotIn("raw", payload)
        json.dumps(payload)

    def test_booru_detail_preserves_variants_without_raw(self):
        self.booru_client.get_post.return_value = BooruPost(
            "demo",
            9,
            original=ImageVariant("original.jpg", 1000, 800),
            sample=ImageVariant("sample.jpg", 500, 400),
            tags={"general": ["tag"]},
            rating="s",
            score=5,
            source=["source"],
            metadata={"md5": "abc"},
            raw=object(),
        )

        payload = self.backend.get_booru_detail("demo", "9").to_dict()

        self.assertEqual(payload["metadata"]["sample"]["url"], "sample.jpg")
        self.assertEqual(payload["metadata"]["rating"], "s")
        self.assertNotIn("raw", payload)
        json.dumps(payload)

    def test_detail_error_uses_stable_provider_error(self):
        self.booru_client.get_post.side_effect = TimeoutError("timed out")

        with self.assertRaises(BackendError) as raised:
            self.backend.get_booru_detail("demo", "9")

        self.assertEqual(raised.exception.to_dict()["code"], "timeout")


if __name__ == "__main__":
    unittest.main()
