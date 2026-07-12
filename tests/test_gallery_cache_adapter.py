import unittest
from unittest.mock import patch

from app.gallery_cache import get_eh_gallery_cache, put_eh_gallery_cache


class GalleryCacheAdapterTests(unittest.TestCase):
    def test_read_failure_becomes_cache_miss(self):
        with patch("app.gallery_cache.gallery_cache.get", side_effect=PermissionError("denied")):
            self.assertIsNone(get_eh_gallery_cache("https://e-hentai.org/g/1/abc/"))

    def test_write_failure_does_not_escape(self):
        with patch("app.gallery_cache.gallery_cache.put", side_effect=PermissionError("denied")):
            self.assertIsNone(put_eh_gallery_cache("url", object(), object()))


if __name__ == "__main__":
    unittest.main()
