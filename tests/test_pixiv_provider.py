import unittest

from core.provider.pixiv import PixivClient, PixivNotImplementedError, PixivIllust, PixivUser


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


if __name__ == "__main__":
    unittest.main()
