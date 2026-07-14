import unittest

from unittest.mock import Mock

from core.provider.pixiv import PixivClient, PixivNotImplementedError, PixivIllust, PixivUser, PixivWebClient


class PixivProviderSkeletonTests(unittest.TestCase):
    def test_default_client_is_not_logged_in(self):
        client = PixivClient()
        self.assertFalse(client.is_logged_in())
        self.assertEqual(client.provider_id, "pixiv")

    def test_feed_methods_are_reserved(self):
        client = PixivClient()
        with self.assertRaises(PixivNotImplementedError):
            client.get_recommended()
        with self.assertRaises(PixivNotImplementedError):
            client.get_following()
        with self.assertRaises(PixivNotImplementedError):
            client.get_ranking()
        with self.assertRaises(PixivNotImplementedError):
            client.search_illusts("cat")

    def test_history_placeholder_returns_empty_result(self):
        result = PixivClient().get_history_placeholder()
        self.assertEqual(result.illusts, [])
        self.assertEqual(result.query, "history")

    def test_illust_cover_url_priority(self):
        illust = PixivIllust(
            id="1",
            title="demo",
            image_urls={"medium": "m.jpg", "square_medium": "s.jpg", "large": "l.jpg"},
            user=PixivUser(id="u", name="n"),
        )
        self.assertEqual(illust.cover_url, "s.jpg")
        self.assertFalse(illust.is_r18)

    def test_web_search_maps_ajax_illusts_and_next_page(self):
        response = Mock(status_code=200)
        response.json.return_value = {"error": False, "body": {"next": "https://www.pixiv.net/ajax/search/artworks/cat?p=2", "illustManga": {"data": [{"id": "1", "title": "Cat", "userId": "2", "userName": "Artist", "pageCount": 2, "url": "https://i.pximg.net/cover.jpg", "tags": ["cat"]}]}}}
        transport = Mock()
        transport.get.return_value = response
        result = PixivWebClient(transport=transport, cookie="PHPSESSID=abc").search_illusts("cat")
        self.assertEqual(result.illusts[0].title, "Cat")
        self.assertEqual(result.illusts[0].user.name, "Artist")
        self.assertEqual(result.illusts[0].cover_url, "https://i.pximg.net/cover.jpg")
        self.assertEqual(result.next_url, "https://www.pixiv.net/ajax/search/artworks/cat?p=2")
        self.assertEqual(transport.get.call_args.kwargs["headers"]["Cookie"], "PHPSESSID=abc")

    def test_web_illust_pages_maps_original_urls(self):
        response = Mock(status_code=200)
        response.json.return_value = {"error": False, "body": [{"urls": {"original": "https://i.pximg.net/original.jpg", "thumb_mini": "https://i.pximg.net/thumb.jpg"}}]}
        transport = Mock()
        transport.get.return_value = response
        pages = PixivWebClient(transport=transport).get_illust_pages("42")
        self.assertEqual(pages, [{"original": "https://i.pximg.net/original.jpg", "thumb_mini": "https://i.pximg.net/thumb.jpg"}])

    def test_web_detail_maps_tags_and_dimensions(self):
        response = Mock(status_code=200)
        response.json.return_value = {"error": False, "body": {"id": "42", "title": "Detail", "width": 1000, "height": 800, "tags": {"tags": [{"tag": "cat"}]}, "userId": "9", "userName": "Artist"}}
        transport = Mock()
        transport.get.return_value = response
        illust = PixivWebClient(transport=transport).get_illust_detail("42")
        self.assertEqual(illust.tags, ["cat"])
        self.assertEqual((illust.width, illust.height), (1000, 800))

    def test_web_ranking_converts_app_mode_to_web_mode(self):
        response = Mock(status_code=200)
        response.json.return_value = {"contents": [{"illust_id": "1", "title": "Ranked"}]}
        transport = Mock()
        transport.get.return_value = response
        result = PixivWebClient(transport=transport).get_ranking(mode="day")
        self.assertEqual(result.illusts[0].title, "Ranked")
        self.assertEqual(transport.get.call_args.kwargs["params"]["mode"], "daily")

    def test_web_recommendations_map_discovery_illusts(self):
        response = Mock(status_code=200)
        response.json.return_value = {"error": False, "body": {"illusts": [{"id": "1", "title": "Discovery", "url": "https://i.pximg.net/cover.jpg"}]}}
        transport = Mock()
        transport.get.return_value = response
        result = PixivWebClient(transport=transport).get_recommended()
        self.assertEqual(result.query, "discovery")
        self.assertEqual(result.illusts[0].cover_url, "https://i.pximg.net/cover.jpg")
        self.assertEqual(transport.get.call_args.kwargs["params"], {"mode": "all", "limit": 100})


if __name__ == "__main__":
    unittest.main()
