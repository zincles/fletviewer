import unittest
from unittest.mock import Mock

from app.views.search import SearchContext
from core.provider.ehgrabber import EHentaiClient


class SearchContextTests(unittest.TestCase):
    def test_context_freezes_loader_and_scope(self):
        loader = Mock(return_value="result")
        context = SearchContext("favorites", "搜索收藏", "关键词", loader, needs_login=True)

        result = context.load("client", "tag", None)

        self.assertEqual(result, "result")
        self.assertEqual(context.key, "favorites")
        self.assertTrue(context.needs_login)
        loader.assert_called_once_with("client", "tag", None)

    def test_favorite_pagination_preserves_missing_keyword(self):
        client = object.__new__(EHentaiClient)
        client._get_galleries = Mock(return_value="result")

        result = client.get_favorites(
            page_url="https://e-hentai.org/favorites.php?next=123",
            keyword="blue archive",
        )

        self.assertEqual(result, "result")
        requested_url = client._get_galleries.call_args.args[0]
        self.assertIn("next=123", requested_url)
        self.assertIn("f_search=blue+archive", requested_url)


if __name__ == "__main__":
    unittest.main()
