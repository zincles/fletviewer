import unittest

from app.navigation import reading_label_for_index


class ReadingTabNavigationTests(unittest.TestCase):
    def test_local_tab_index_resolves_to_reading_label(self) -> None:
        pages = [
            ("Safebooru", "", None, None),
            ("Gelbooru", "", None, None),
            ("Danbooru", "", None, None),
            ("本地画廊", "", None, None),
            ("下载", "", None, None),
        ]

        self.assertEqual(reading_label_for_index(pages, [0, 1, 2], 1), "Gelbooru")

    def test_non_contiguous_reading_indexes_do_not_route_to_adjacent_section(self) -> None:
        pages = [
            ("主页", "", None, None),
            ("本地画廊", "", None, None),
            ("下载", "", None, None),
            ("热门", "", None, None),
        ]

        self.assertEqual(reading_label_for_index(pages, [0, 3], 1), "热门")
        self.assertIsNone(reading_label_for_index(pages, [0, 3], 2))


if __name__ == "__main__":
    unittest.main()
