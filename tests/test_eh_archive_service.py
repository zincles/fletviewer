import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from core.api.archive import EHArchiveService
from core.api.backend import BackendFacade
from core.api.errors import BackendError
from core.provider.ehgrabber import Archive, ComicDetails, ThumbnailItem, ThumbnailsResult


class EHArchiveServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.manager = Mock()
        self.get_client = Mock(return_value=self.client)
        self.service = EHArchiveService(
            get_eh_client=self.get_client,
            get_download_manager=lambda: self.manager,
        )
        self.gallery_url = "https://e-hentai.org/g/123/token"

    def test_list_options_is_json_safe_and_marks_hath_unavailable(self):
        self.client.get_archives.return_value = [
            Archive("org", "Original", "10 MiB"),
            Archive("h@h_1", "H@H", "delivery"),
        ]

        options = self.service.list_options(self.gallery_url)

        self.get_client.assert_called_once_with(require_login=True)
        self.assertTrue(options[0].available)
        self.assertFalse(options[1].available)
        json.dumps([option.to_dict() for option in options])

    def test_start_download_builds_existing_eh_task_contract(self):
        option = Archive("org", "Original", "10 MiB")
        self.client.get_archives.return_value = [option]
        self.client.load_comic_info.return_value = ComicDetails(
            id=self.gallery_url,
            title="Gallery",
            url=self.gallery_url,
        )
        self.client.load_thumbnails.return_value = ThumbnailsResult(
            thumbnails=["thumb"],
            urls=["page"],
            items=[ThumbnailItem("thumb", "page")],
        )
        self.client.get_archive_download_url.return_value = "https://download.test/archive.zip"
        self.client.parse_url.return_value = (123, "token")
        self.manager.create_task.return_value = SimpleNamespace(id="task-1", status="queued")

        result = self.service.start_download(self.gallery_url, "org")

        create = self.manager.create_task.call_args
        self.assertEqual(create.args, ("https://download.test/archive.zip", "archive.zip"))
        self.assertEqual(create.kwargs["headers"], {"Referer": self.gallery_url})
        self.assertEqual(create.kwargs["tags"], ["eh_archive"])
        tag_data = create.kwargs["tag_data"]
        self.assertEqual(tag_data["gid"], "123")
        self.assertEqual(tag_data["token"], "token")
        self.assertEqual(tag_data["download_url_valid_seconds"], 86400)
        self.assertEqual(tag_data["max_ip_count"], 2)
        self.assertNotIn("headers", tag_data)
        self.manager.start_task.assert_called_once_with("task-1")
        self.assertEqual(result.task_id, "task-1")
        json.dumps(result.to_dict())

    def test_unknown_archive_does_not_create_task(self):
        self.client.get_archives.return_value = []

        with self.assertRaises(ValueError):
            self.service.start_download(self.gallery_url, "missing")

        self.manager.create_task.assert_not_called()

    def test_facade_converts_archive_auth_failure(self):
        self.client.get_archives.side_effect = RuntimeError("请先登录")
        backend = BackendFacade(
            get_eh_client=self.get_client,
            get_pixiv_client=Mock(),
            get_booru_client=Mock(),
            eh_archive_service=self.service,
        )

        with self.assertRaises(BackendError) as raised:
            backend.list_eh_archives(self.gallery_url)

        self.assertEqual(raised.exception.to_dict()["code"], "authentication_required")


if __name__ == "__main__":
    unittest.main()
