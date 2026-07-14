import json
import unittest
from unittest.mock import Mock

from core.api.downloads import DownloadTaskService
from core.api.errors import BackendError
from core.download.manager import DownloadTask, ResumeInfo


class DownloadTaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.manager = Mock()
        self.task = DownloadTask(
            id="task-1",
            url="https://signed.example/archive?token=secret",
            filename="archive.zip",
            status="running",
            headers={"Cookie": "secret", "Referer": "gallery"},
            tags=["eh_archive"],
            tag_data={
                "provider": "ehentai",
                "gallery_url": "https://e-hentai.org/g/123/gallery-token",
                "gid": "123",
                "token": "gallery-token",
                "archive_id": "org",
                "archive_title": "Original",
                "download_url_acquired_at": "2026-01-01T00:00:00+00:00",
                "download_url_valid_seconds": 86400,
                "max_ip_count": 2,
                "gallery_details": {"title": "Gallery"},
            },
            temp_dir="C:/private/task-1",
            part_path="C:/private/task-1/payload.part",
            final_path="C:/private/task-1/payload.zip",
            bytes_total=100,
            bytes_done=25,
            error=None,
            resume=ResumeInfo(supported=True, etag="secret-etag"),
        )
        self.manager.list_tasks.return_value = [self.task]
        self.manager.get_task.return_value = self.task
        self.service = DownloadTaskService(self.manager)

    def test_dto_is_rich_json_safe_and_excludes_execution_secrets(self):
        result = self.service.get_task("task-1")
        payload = result.to_dict()

        self.assertEqual(result.progress, 0.25)
        self.assertEqual(result.media["gallery_id"], "123")
        self.assertEqual(result.media["gallery_token"], "gallery-token")
        self.assertEqual(result.expiry["valid_seconds"], 86400)
        self.assertTrue(result.resume_supported)
        serialized = json.dumps(payload)
        for secret in ("signed.example", "Cookie", "secret-etag", "C:/private"):
            self.assertNotIn(secret, serialized)

    def test_filters_and_legacy_eh_provider_inference(self):
        self.task.tag_data.pop("provider")

        results = self.service.list_tasks(provider="ehentai", kind="eh_archive")

        self.assertEqual([task.id for task in results], ["task-1"])

    def test_commands_delegate_by_task_id_and_return_current_view(self):
        self.service.cancel_task("task-1")
        self.service.retry_task("task-1")
        self.service.delete_task("task-1")

        self.manager.cancel_task.assert_called_once_with("task-1")
        self.manager.retry_task.assert_called_once_with("task-1")
        self.manager.delete_task.assert_called_once_with("task-1")

    def test_unknown_task_has_stable_error(self):
        self.manager.get_task.return_value = None

        with self.assertRaises(BackendError) as raised:
            self.service.cancel_task("missing")

        self.assertEqual(raised.exception.to_dict()["code"], "task_not_found")


if __name__ == "__main__":
    unittest.main()
