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
        start.assert_not_called()
        supervisor.close()

    def test_rejects_runtime_with_wrong_storage_owner(self):
        supervisor = FvcoreSidecarSupervisor(
            self.url,
            expected_storage={"data": Path(self.temp.name) / "OtherData"},
        )
        with self.assertRaisesRegex(FvcoreSidecarError, "data storage mismatch"):
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


if __name__ == "__main__":
    unittest.main()
