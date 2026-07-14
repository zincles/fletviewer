import unittest

from unittest.mock import Mock

from core.provider.booru import (
    BOORU_PROVIDER_SPECS,
    BOORU_PROVIDERS,
    BooruAccessDeniedError,
    BooruClient,
    BooruNotImplementedError,
    BooruPost,
    DanbooruClient,
    GelbooruClient,
    MoebooruClient,
    E621Client,
    PhilomenaClient,
    PahealClient,
    ImageVariant,
    SafebooruClient,
    create_booru_client,
)


class BooruProviderSkeletonTests(unittest.TestCase):
    def test_expected_provider_tabs_are_registered(self):
        self.assertEqual(
            list(BOORU_PROVIDERS),
            [
                "safebooru", "gelbooru", "danbooru", "rule34", "tbib", "xbooru",
                "hypnohub", "yandere", "lolibooru", "konachan", "konachan_net", "e621", "e926",
                "derpibooru", "furbooru", "behoimi",
            ],
        )

    def test_all_registered_providers_create_a_client(self):
        transport = Mock()
        for provider_id in BOORU_PROVIDER_SPECS:
            with self.subTest(provider=provider_id):
                client = create_booru_client(provider_id, transport=transport)
                self.assertEqual(client.provider_id, provider_id)

    def test_image_url_fallbacks(self):
        post = BooruPost(
            provider="test",
            id=1,
            sample=ImageVariant(url="sample"),
            preview=ImageVariant(url="preview"),
        )
        self.assertEqual(post.thumbnail_url, "preview")
        self.assertEqual(post.image_url, "sample")

    def test_all_tags_preserve_category_order_and_deduplicate(self):
        post = BooruPost("test", 1, tags={"artist": ["a"], "general": ["x", "a"]})
        self.assertEqual(post.all_tags, ["a", "x"])
        self.assertEqual(post.tags_for("artist"), ["a"])

    def test_default_client_reserves_search_detail_and_suggestions(self):
        client = BooruClient("test", "Test")
        with self.assertRaises(BooruNotImplementedError):
            client.search_posts("tag")
        with self.assertRaises(BooruNotImplementedError):
            client.get_post(1)
        with self.assertRaises(BooruNotImplementedError):
            client.tag_suggestions("ta")

    def test_http_403_is_reported_without_bypass(self):
        response = Mock(status_code=403)
        transport = Mock()
        transport.get.return_value = response
        with self.assertRaises(BooruAccessDeniedError):
            GelbooruClient(transport=transport).search_posts("cat")

    def test_http_401_requests_credentials(self):
        response = Mock(status_code=401)
        transport = Mock()
        transport.get.return_value = response
        with self.assertRaisesRegex(BooruAccessDeniedError, "HTTP 401"):
            GelbooruClient(transport=transport).search_posts("cat")

    def test_xml_api_error_is_not_treated_as_an_empty_result(self):
        response = Mock(status_code=200, text="<error>Missing authentication</error>")
        transport = Mock()
        transport.get.return_value = response
        with self.assertRaisesRegex(BooruAccessDeniedError, "Missing authentication"):
            create_booru_client("rule34", transport=transport).search_posts("cat")

    def test_html_response_from_json_api_is_diagnostic(self):
        response = Mock(status_code=200)
        response.headers = {"Content-Type": "text/html"}
        response.json.side_effect = ValueError("not JSON")
        transport = Mock()
        transport.get.return_value = response
        with self.assertRaisesRegex(Exception, "非 JSON"):
            DanbooruClient(transport=transport).search_posts("cat")

    def test_gelbooru_credentials_are_sent(self):
        response = Mock(status_code=200)
        response.json.return_value = {"@attributes": {"count": 0}, "post": []}
        transport = Mock()
        transport.get.return_value = response
        GelbooruClient(transport=transport, user_id="12", api_key="secret").search_posts("cat")
        params = transport.get.call_args.kwargs["params"]
        self.assertEqual(params["user_id"], "12")
        self.assertEqual(params["api_key"], "secret")

    def test_gelbooru_get_post_maps_metadata(self):
        response = Mock(status_code=200)
        response.json.return_value = {"post": [{
            "id": 9,
            "file_url": "https://img.test/9.jpg",
            "sample_url": "https://img.test/sample/9.jpg",
            "sample_width": 800,
            "sample_height": 600,
            "md5": "abc",
            "owner": "42",
        }]}
        transport = Mock()
        transport.get.return_value = response
        post = GelbooruClient(transport=transport).get_post(9)
        self.assertEqual(post.id, 9)
        self.assertEqual(post.sample.width, 800)
        self.assertEqual(post.metadata["md5"], "abc")
        self.assertEqual(transport.get.call_args.kwargs["params"]["id"], 9)

    def test_gelbooru_tag_suggestions_are_mapped(self):
        response = Mock(status_code=200)
        response.json.return_value = {"tag": [{"name": "cat_girl", "type": 4, "count": 123}]}
        transport = Mock()
        transport.get.return_value = response
        suggestions = GelbooruClient(transport=transport).tag_suggestions("cat")
        self.assertEqual(suggestions[0].tag, "cat_girl")
        self.assertEqual(suggestions[0].type, "character")
        self.assertEqual(suggestions[0].count, 123)

    def test_danbooru_json_is_mapped(self):
        response = Mock(status_code=200)
        response.json.return_value = [{"id": 7, "file_url": "https://img.test/7.jpg", "tag_string_general": "cat solo"}]
        transport = Mock()
        transport.get.return_value = response
        result = DanbooruClient(transport=transport).search_posts("cat")
        self.assertEqual(result.posts[0].id, 7)
        self.assertEqual(result.posts[0].tags["general"], ["cat", "solo"])

    def test_safebooru_xml_is_mapped(self):
        response = Mock(status_code=200, text='<posts count="1"><post id="8" file_url="https://img.test/8.jpg" tags="cat solo" /></posts>')
        transport = Mock()
        transport.get.return_value = response
        result = SafebooruClient(transport=transport).search_posts("cat")
        self.assertEqual(result.total_count, 1)
        self.assertEqual(result.posts[0].image_url, "https://img.test/8.jpg")

    def test_moebooru_json_is_mapped(self):
        response = Mock(status_code=200)
        response.json.return_value = [{"id": 10, "file_url": "https://img.test/10.jpg", "tags": "cat solo"}]
        transport = Mock()
        transport.get.return_value = response
        result = MoebooruClient("yandere", "Yande.re", "https://yande.re", transport=transport).search_posts("cat")
        self.assertEqual(result.posts[0].provider, "yandere")
        self.assertEqual(result.posts[0].all_tags, ["cat", "solo"])

    def test_gelbooru_alike_result_keeps_preset_provider(self):
        response = Mock(status_code=200, text='<posts count="1"><post id="10" file_url="https://img.test/10.jpg" /></posts>')
        transport = Mock()
        transport.get.return_value = response
        client = create_booru_client("rule34", transport=transport)
        result = client.search_posts("cat")
        self.assertEqual(result.provider, "rule34")
        self.assertEqual(result.posts[0].provider, "rule34")

    def test_e621_json_preserves_tag_categories(self):
        response = Mock(status_code=200)
        response.json.return_value = {"posts": [{
            "id": 11,
            "file": {"url": "https://img.test/11.jpg", "width": 1000, "height": 800},
            "preview": {"url": "https://img.test/11-preview.jpg"},
            "tags": {"artist": ["artist_a"], "general": ["cat"]},
            "score": {"total": 12},
        }]}
        transport = Mock()
        transport.get.return_value = response
        post = E621Client("e621", "E621", "https://e621.net", transport=transport).search_posts("cat").posts[0]
        self.assertEqual(post.tags["artist"], ["artist_a"])
        self.assertEqual(post.score, 12)

    def test_philomena_json_is_mapped(self):
        response = Mock(status_code=200)
        response.json.return_value = {"total": 1, "images": [{
            "id": 12,
            "representations": {"full": "https://img.test/12.jpg", "thumb": "https://img.test/12-thumb.jpg"},
            "tags": ["safe", "pony"],
            "width": 900,
            "height": 1200,
        }]}
        transport = Mock()
        transport.get.return_value = response
        result = PhilomenaClient("derpibooru", "Derpibooru", "https://derpibooru.org", transport=transport).search_posts("pony")
        self.assertEqual(result.total_count, 1)
        self.assertEqual(result.posts[0].thumbnail_url, "https://img.test/12-thumb.jpg")

    def test_paheal_xml_is_mapped(self):
        response = Mock(status_code=200, text='<posts><tag id="13" file_url="https://img.test/13.jpg" tags="cat solo" /></posts>')
        transport = Mock()
        transport.get.return_value = response
        result = PahealClient(transport=transport).search_posts("cat")
        self.assertEqual(result.posts[0].id, "13")
        self.assertEqual(result.posts[0].all_tags, ["cat", "solo"])


if __name__ == "__main__":
    unittest.main()
