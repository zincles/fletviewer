"""Isolated desktop supervisor for a future fvcore sidecar cutover."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


class FvcoreSidecarError(RuntimeError):
    """Raised when a sidecar cannot be safely discovered or supervised."""


@dataclass(frozen=True, slots=True)
class FvcoreConnection:
    base_url: str
    runtime_id: str
    instance_name: str
    started_by_supervisor: bool


class FvcoreSidecarSupervisor:
    """Discovers or starts one loopback fvcore process without touching Python Core."""

    def __init__(
        self,
        base_url: str,
        *,
        executable: Path | None = None,
        expected_instance_name: str | None = None,
        expected_storage: Mapping[str, Path] | None = None,
        startup_timeout: float = 10.0,
        request_timeout: float = 0.5,
    ) -> None:
        self._base_url = _loopback_base_url(base_url)
        self._executable = Path(executable).resolve() if executable else None
        self._expected_instance_name = expected_instance_name
        self._expected_storage = {
            key: str(Path(value).resolve()) for key, value in (expected_storage or {}).items()
        }
        unknown = self._expected_storage.keys() - {"data", "cache", "downloads", "temp"}
        if unknown:
            raise ValueError(f"unknown fvcore storage domains: {', '.join(sorted(unknown))}")
        if startup_timeout <= 0 or request_timeout <= 0:
            raise ValueError("sidecar timeouts must be positive")
        self._startup_timeout = startup_timeout
        self._request_timeout = request_timeout
        self._process: subprocess.Popen[bytes] | None = None
        self._connection: FvcoreConnection | None = None

    @property
    def connection(self) -> FvcoreConnection | None:
        return self._connection

    def connect(self) -> FvcoreConnection:
        """Reuses a ready Runtime or starts the configured executable and waits for it."""
        if self._connection is not None:
            return self._connection
        snapshot = self._try_snapshot()
        started = False
        if snapshot is None:
            executable = self._executable or discover_fvcore_executable()
            self._process = _start_process(executable)
            started = True
            try:
                snapshot = self._wait_until_ready()
            except Exception:
                self.close()
                raise
        try:
            self._validate_snapshot(snapshot)
        except Exception:
            if started:
                self.close()
            raise
        self._connection = FvcoreConnection(
            base_url=self._base_url,
            runtime_id=str(snapshot["runtime_id"]),
            instance_name=str(snapshot["instance_name"]),
            started_by_supervisor=started,
        )
        return self._connection

    def close(self, *, timeout: float = 10.0) -> None:
        """Gracefully stops only a process started by this supervisor."""
        process = self._process
        self._process = None
        self._connection = None
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=min(timeout, 2.0))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)

    def _wait_until_ready(self) -> dict[str, object]:
        deadline = time.monotonic() + self._startup_timeout
        while time.monotonic() < deadline:
            process = self._process
            if process is not None and process.poll() is not None:
                raise FvcoreSidecarError(
                    f"fvcore exited before ready with status {process.returncode}"
                )
            snapshot = self._try_snapshot()
            if snapshot is not None:
                return snapshot
            time.sleep(0.05)
        raise FvcoreSidecarError(
            f"fvcore did not become ready at {self._base_url} within "
            f"{self._startup_timeout:g} seconds"
        )

    def _try_snapshot(self) -> dict[str, object] | None:
        try:
            ready = _request(self._base_url + "/health/ready", self._request_timeout)
            if ready != b"ready\n":
                return None
            payload = _request(self._base_url + "/api/v1/runtime", self._request_timeout)
            snapshot = json.loads(payload)
            if not isinstance(snapshot, dict) or snapshot.get("state") != "ready":
                return None
            return snapshot
        except (OSError, UnicodeError, json.JSONDecodeError, urllib.error.URLError):
            return None

    def _validate_snapshot(self, snapshot: Mapping[str, object]) -> None:
        runtime_id = snapshot.get("runtime_id")
        instance_name = snapshot.get("instance_name")
        if not isinstance(runtime_id, str) or not runtime_id:
            raise FvcoreSidecarError("fvcore Runtime snapshot has no runtime_id")
        if not isinstance(instance_name, str) or not instance_name:
            raise FvcoreSidecarError("fvcore Runtime snapshot has no instance_name")
        if self._expected_instance_name and instance_name != self._expected_instance_name:
            raise FvcoreSidecarError(
                f"fvcore instance mismatch: expected {self._expected_instance_name!r}, "
                f"received {instance_name!r}"
            )
        storage = snapshot.get("storage")
        if self._expected_storage and not isinstance(storage, dict):
            raise FvcoreSidecarError("fvcore Runtime snapshot has no storage identity")
        for domain, expected in self._expected_storage.items():
            actual = storage.get(domain) if isinstance(storage, dict) else None
            if not isinstance(actual, str) or str(Path(actual).resolve()) != expected:
                raise FvcoreSidecarError(
                    f"fvcore {domain} storage mismatch: expected {expected!r}, received {actual!r}"
                )


def discover_fvcore_executable(
    environ: Mapping[str, str] | None = None,
    *,
    project_root: Path | None = None,
) -> Path:
    """Finds an explicitly configured, packaged, or development fvcore executable."""
    env = os.environ if environ is None else environ
    suffix = ".exe" if os.name == "nt" else ""
    configured = env.get("FVCORE_EXECUTABLE")
    root = Path(__file__).resolve().parents[1] if project_root is None else Path(project_root)
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            root / "fvcore" / f"fvcore{suffix}",
            root / "fvcore" / "target" / "release" / f"fvcore{suffix}",
            root / "fvcore" / "target" / "debug" / f"fvcore{suffix}",
        ]
    )
    for candidate in candidates:
        if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
            return candidate.resolve()
    rendered = ", ".join(str(candidate) for candidate in candidates)
    raise FvcoreSidecarError(
        f"fvcore executable was not found; set FVCORE_EXECUTABLE or provide one explicitly; "
        f"checked: {rendered}"
    )


def _loopback_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.port is None
    ):
        raise ValueError("fvcore sidecar URL must be an HTTP loopback origin with an explicit port")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"http://{host}:{parsed.port}"


def _request(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise OSError(f"unexpected fvcore HTTP status {response.status}")
        return response.read()


def _start_process(executable: Path) -> subprocess.Popen[bytes]:
    if not executable.is_file():
        raise FvcoreSidecarError(f"fvcore executable does not exist: {executable}")
    options: dict[str, object] = {
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": None,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        return subprocess.Popen([str(executable), "run"], **options)
    except OSError as error:
        raise FvcoreSidecarError(f"failed to start fvcore executable {executable}: {error}") from error


__all__ = [
    "FvcoreConnection",
    "FvcoreSidecarError",
    "FvcoreSidecarSupervisor",
    "discover_fvcore_executable",
]
