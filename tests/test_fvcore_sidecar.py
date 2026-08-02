import json
import os
import shutil
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from app.fvcore_sidecar import (
    FvcoreSidecarError,
    FvcoreSidecarSupervisor,
    discover_fvcore_executable,
)


class _RuntimeHandler(BaseHTTPRequestHandler):
    snapshot = {}

    def do_GET(self):
        if self.path == "/health/ready":
            body = b"ready\n"
            content_type = "text/plain"
        elif self.path == "/api/v1/runtime":
            body = json.dumps(self.snapshot).encode("utf-8")
            content_type = "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class FvcoreSidecarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.storage = {
            "data": root / "Data",
            "cache": root / "Cache",
            "downloads": root / "Downloads",
            "temp": root / "Temp",
        }
        _RuntimeHandler.snapshot = {
            "api_protocol_version": 1,
            "core_version": "0.1.0-test",
            "runtime_id": "runtime-test",
            "instance_name": "desktop-smoke",
            "state": "ready",
            "storage": {key: str(value.resolve()) for key, value in self.storage.items()},
        }
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _RuntimeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_reuses_matching_runtime_without_taking_process_ownership(self):
        supervisor = FvcoreSidecarSupervisor(
            self.url,
            expected_instance_name="desktop-smoke",
            expected_storage=self.storage,
        )
        with patch("app.fvcore_sidecar._start_process") as start:
            connection = supervisor.connect()
        self.assertEqual(connection.runtime_id, "runtime-test")
        self.assertFalse(connection.started_by_supervisor)
        self.assertEqual(connection.api_protocol_version, 1)
        self.assertEqual(connection.core_version, "0.1.0-test")
        start.assert_not_called()
        supervisor.close()

    def test_rejects_runtime_with_wrong_storage_owner(self):
        supervisor = FvcoreSidecarSupervisor(
            self.url,
            expected_storage={"data": Path(self.temp.name) / "OtherData"},
        )
        with self.assertRaisesRegex(FvcoreSidecarError, "data storage mismatch"):
            supervisor.connect()

    def test_rejects_runtime_with_incompatible_api_protocol(self):
        _RuntimeHandler.snapshot["api_protocol_version"] = 2
        supervisor = FvcoreSidecarSupervisor(self.url)
        with self.assertRaisesRegex(FvcoreSidecarError, "API protocol mismatch"):
            supervisor.connect()

    def test_starts_waits_for_and_stops_owned_process(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        process = Mock(pid=4321, returncode=None)
        process.poll.return_value = None
        executable = Path(self.temp.name) / "fvcore"
        executable.touch()
        supervisor = FvcoreSidecarSupervisor(
            self.url,
            executable=executable,
            startup_timeout=1,
            expected_instance_name="desktop-smoke",
        )

        def start(_executable):
            self.server = ThreadingHTTPServer(("127.0.0.1", int(self.url.rsplit(":", 1)[1])), _RuntimeHandler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            return process

        with (
            patch("app.fvcore_sidecar._start_process", side_effect=start),
            patch("app.fvcore_sidecar.os.killpg") as killpg,
        ):
            connection = supervisor.connect()
            supervisor.close(timeout=1)
        self.assertTrue(connection.started_by_supervisor)
        killpg.assert_called_once()
        process.wait.assert_called_once_with(timeout=1)

    def test_requires_loopback_origin(self):
        for url in ("https://127.0.0.1:8787", "http://0.0.0.0:8787", "http://localhost"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                FvcoreSidecarSupervisor(url)

    def test_discovers_explicit_development_executable(self):
        root = Path(self.temp.name)
        executable = root / "fvcore" / "target" / "debug" / "fvcore"
        executable.parent.mkdir(parents=True)
        executable.touch(mode=0o755)
        executable.chmod(0o755)
        discovered = discover_fvcore_executable({}, project_root=root)
        self.assertEqual(discovered, executable.resolve())

    @unittest.skipUnless(
        (Path(__file__).parents[1] / "fvcore" / "target" / "debug" / ("fvcore.exe" if os.name == "nt" else "fvcore")).is_file(),
        "requires a built fvcore debug executable",
    )
    def test_real_sidecar_reuse_shutdown_and_storage_restart(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        root = Path(self.temp.name)
        source = Path(__file__).parents[1] / "fvcore" / "target" / "debug" / ("fvcore.exe" if os.name == "nt" else "fvcore")
        executable = root / source.name
        shutil.copy2(source, executable)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        config = {
            "instance_name": "desktop-real-smoke",
            "control": {
                "enabled": True,
                "listen": f"127.0.0.1:{port}",
                "allow_lan": False,
                "webui_enabled": False,
            },
            "storage": {key: str(value) for key, value in self.storage.items()},
        }
        (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
        owner = FvcoreSidecarSupervisor(
            url,
            executable=executable,
            expected_instance_name="desktop-real-smoke",
            expected_storage=self.storage,
            startup_timeout=10,
        )
        follower = FvcoreSidecarSupervisor(
            url,
            expected_instance_name="desktop-real-smoke",
            expected_storage=self.storage,
        )
        restarted = None
        try:
            first = owner.connect()
            reused = follower.connect()
            self.assertTrue(first.started_by_supervisor)
            self.assertFalse(reused.started_by_supervisor)
            self.assertEqual(reused.runtime_id, first.runtime_id)
            follower.close()
            with urllib.request.urlopen(url + "/api/v1/download-tasks", timeout=2) as response:
                self.assertEqual(json.load(response), [])
            owner.close()

            restarted = FvcoreSidecarSupervisor(
                url,
                executable=executable,
                expected_instance_name="desktop-real-smoke",
                expected_storage=self.storage,
                startup_timeout=10,
            )
            second = restarted.connect()
            self.assertNotEqual(second.runtime_id, first.runtime_id)
            with urllib.request.urlopen(url + "/api/v1/runtime", timeout=2) as response:
                snapshot = json.load(response)
            self.assertEqual(
                snapshot["storage"]["data"],
                str(self.storage["data"].resolve()),
            )
        finally:
            follower.close()
            owner.close()
            if restarted is not None:
                restarted.close()


    @unittest.skipUnless(
        (Path(__file__).parents[1] / "fvcore" / "target" / "debug" / ("fvcore.exe" if os.name == "nt" else "fvcore")).is_file(),
        "requires a built fvcore debug executable",
    )
    def test_real_sidecar_recovers_nonempty_persistent_tasks(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        root = Path(self.temp.name)
        source = Path(__file__).parents[1] / "fvcore" / "target" / "debug" / ("fvcore.exe" if os.name == "nt" else "fvcore")
        executable = root / source.name
        shutil.copy2(source, executable)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        config = {
            "instance_name": "persistent-task-smoke",
            "control": {
                "enabled": True,
                "listen": f"127.0.0.1:{port}",
                "allow_lan": False,
                "webui_enabled": False,
            },
            "storage": {key: str(value) for key, value in self.storage.items()},
        }
        (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
        now = "2026-08-01T00:00:00Z"
        image_id = "01989abc-def0-7000-8000-000000000001"
        archive_download_id = "01989abc-def0-7000-8000-000000000002"
        archive_submit_id = "01989abc-def0-7000-8000-000000000003"
        image_dir = self.storage["downloads"] / "ImageTasks" / image_id
        image_dir.mkdir(parents=True)
        (image_dir / "task.json").write_text(
            json.dumps({
                "snapshot": {
                    "id": image_id,
                    "state": "running",
                    "revision": 4,
                    "kind": "booru_original",
                    "profile": {"provider": "danbooru", "profile": "default"},
                    "post_id": 123,
                    "phase": "network",
                    "bytes_done": 4096,
                    "bytes_total": 8192,
                    "byte_length": None,
                    "content_md5": None,
                    "output": None,
                    "error": None,
                    "created_at": now,
                    "updated_at": now,
                }
            }),
            encoding="utf-8",
        )

        def archive_task(task_id, state, signed_url):
            directory = self.storage["downloads"] / "Downloading" / task_id
            directory.mkdir(parents=True)
            (directory / "task.json").write_text(
                json.dumps({
                    "snapshot": {
                        "id": task_id,
                        "state": state,
                        "revision": 7,
                        "profile": {"provider": "eh", "profile": "default"},
                        "gallery": {"gid": 123456, "token": "abcdef1234"},
                        "variant": "resample",
                        "title": "Recovery fixture",
                        "bytes_done": 1024,
                        "bytes_total": 4096,
                        "resume_supported": True,
                        "retry_supported": False,
                        "final_path": None,
                        "error": None,
                        "consume_error": None,
                        "created_at": now,
                        "updated_at": now,
                        "url_acquired_at": now if signed_url else None,
                        "url_valid_seconds": 86400,
                        "max_ip_count": 2,
                    },
                    "signed_url": signed_url,
                    "referer": "https://e-hentai.org/g/123456/abcdef1234/",
                    "part_path": str(directory / "payload.part"),
                    "final_path": str(directory / "payload.zip"),
                    "etag": "fixture-etag" if signed_url else None,
                    "last_modified": None,
                }),
                encoding="utf-8",
            )

        archive_task(archive_download_id, "downloading", "https://e-hentai.org/archive.zip")
        archive_task(archive_submit_id, "submitting", None)
        owner = FvcoreSidecarSupervisor(
            url,
            executable=executable,
            expected_instance_name="persistent-task-smoke",
            expected_storage=self.storage,
            startup_timeout=10,
        )
        restarted = None
        try:
            first = owner.connect()
            with urllib.request.urlopen(url + "/api/v1/download-tasks", timeout=2) as response:
                tasks = {task["id"]: task for task in json.load(response)}
            self.assertEqual(tasks[image_id]["status"], "failed")
            self.assertEqual(tasks[image_id]["kind"], "booru_original")
            self.assertTrue(tasks[image_id]["can_retry"])
            self.assertTrue(tasks[image_id]["can_delete"])
            self.assertEqual(tasks[archive_download_id]["status"], "failed")
            self.assertTrue(tasks[archive_download_id]["can_retry"])
            self.assertFalse(tasks[archive_download_id]["can_delete"])
            self.assertEqual(tasks[archive_submit_id]["status"], "failed")
            self.assertFalse(tasks[archive_submit_id]["can_retry"])
            self.assertEqual(tasks[archive_submit_id]["metadata"]["archive_state"], "costunknown")
            self.assertNotIn(str(self.storage["downloads"]), json.dumps(tasks))
            owner.close()

            restarted = FvcoreSidecarSupervisor(
                url,
                executable=executable,
                expected_instance_name="persistent-task-smoke",
                expected_storage=self.storage,
                startup_timeout=10,
            )
            second = restarted.connect()
            self.assertNotEqual(second.runtime_id, first.runtime_id)
            with urllib.request.urlopen(url + "/api/v1/download-tasks", timeout=2) as response:
                recovered = {task["id"]: task for task in json.load(response)}
            self.assertEqual(set(recovered), set(tasks))
            for task_id in tasks:
                self.assertEqual(recovered[task_id]["provider"], tasks[task_id]["provider"])
                self.assertEqual(recovered[task_id]["kind"], tasks[task_id]["kind"])
                self.assertEqual(recovered[task_id]["status"], tasks[task_id]["status"])
                self.assertEqual(recovered[task_id]["created_at"], tasks[task_id]["created_at"])
        finally:
            owner.close()
            if restarted is not None:
                restarted.close()

if __name__ == "__main__":
    unittest.main()
