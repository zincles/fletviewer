import unittest

from unittest.mock import Mock

from core.provider.booru import (
    BOORU_PROVIDERS,
    BooruAccessDeniedError,
    BooruClient,
    BooruNotImplementedError,
    BooruPost,
    DanbooruClient,
    GelbooruClient,
    ImageVariant,
    SafebooruClient,
)


class BooruProviderSkeletonTests(unittest.TestCase):
    def test_expected_provider_tabs_are_registered(self):
        self.assertEqual(
            list(BOORU_PROVIDERS),
            ["safebooru", "gelbooru", "danbooru"],
        )

    def test_image_url_fallbacks(self):
        post = BooruPost(
            provider="test",
            id=1,
            sample=ImageVariant(url="sample"),
            preview=ImageVariant(url="preview"),
        )
        self.assertEqual(post.thumbnail_url, "preview")
        self.assertEqual(post.image_url, "sample")

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


if __name__ == "__main__":
    unittest.main()
