import unittest
from unittest.mock import Mock, patch

from app.views.settings import _ImageCacheSizeText


class ImageCacheSizeTextTests(unittest.TestCase):
    def test_successful_load_does_not_log_missing_exception(self):
        page = Mock()
        text = _ImageCacheSizeText(page)
        text._alive = True
        stats = Mock(bytes_used=2048, file_count=3)

        with (
            patch("app.views.settings.get_image_cache_stats", return_value=stats),
            patch("app.views.settings.log_exception") as log_exception,
            patch("app.views.settings.request_update") as request_update,
        ):
            text._load()

        self.assertEqual(text.value, "2.0 KB · 3 个文件")
        log_exception.assert_not_called()
        request_update.assert_called_once_with(page)


if __name__ == "__main__":
    unittest.main()
