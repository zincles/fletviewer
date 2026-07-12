import unittest

from app.views.gallery_detail import _thumbnail_preview_count


class GalleryDetailLayoutTests(unittest.TestCase):
    def test_preview_count_uses_configured_columns_and_rows(self) -> None:
        self.assertEqual(_thumbnail_preview_count(100, 5, 2), 10)
        self.assertEqual(_thumbnail_preview_count(100, 5, 3), 15)
        self.assertEqual(_thumbnail_preview_count(100, 5, 4), 20)

    def test_preview_count_does_not_exceed_gallery_size(self) -> None:
        self.assertEqual(_thumbnail_preview_count(7, 5, 3), 7)

    def test_all_rows_show_every_page(self) -> None:
        self.assertEqual(_thumbnail_preview_count(100, 5, None), 100)

    def test_invalid_page_count_is_empty(self) -> None:
        self.assertEqual(_thumbnail_preview_count("invalid", 5, 3), 0)


if __name__ == "__main__":
    unittest.main()
