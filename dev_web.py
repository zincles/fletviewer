"""Development web launcher with debounced restart.

Run this instead of `python main.py --web` while testing the web build:

    python dev_web.py

The script starts the normal Flet web server as a child process. When source files
change and no further changes arrive for 10 seconds, the child is restarted.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DELAY_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 1.0

WATCH_FILES = [
    ROOT / "main.py",
    ROOT / "pyproject.toml",
]
WATCH_DIRS = [
    ROOT / "app",
    ROOT / "lib",
    ROOT / "assets",
]
WATCH_SUFFIXES = {".py", ".toml", ".json", ".yaml", ".yml", ".css", ".js", ".html", ".md"}
IGNORE_DIR_NAMES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "FletViewer",
    "tmp",
}


def _log(message: str) -> None:
    print(f"[dev-web] {message}", flush=True)


def _iter_watch_files():
    for file_path in WATCH_FILES:
        if file_path.exists() and file_path.is_file():
            yield file_path
    for root in WATCH_DIRS:
        if not root.exists() or not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in IGNORE_DIR_NAMES]
            base = Path(dirpath)
            for filename in filenames:
                path = base / filename
                if path.suffix.lower() in WATCH_SUFFIXES:
                    yield path


def snapshot_files() -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in _iter_watch_files():
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path.relative_to(ROOT))] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def start_server() -> subprocess.Popen:
    cmd = [sys.executable, "main.py", "--web"]
    kwargs = {
        "cwd": str(ROOT),
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    _log("starting: " + " ".join(cmd))
    return subprocess.Popen(cmd, **kwargs)


def stop_server(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    _log(f"stopping child pid={process.pid}")
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=5)
        return
    except Exception:
        pass
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=3)
            return
        except Exception:
            pass
    if process.poll() is None:
        _log(f"killing child pid={process.pid}")
        process.kill()
        process.wait(timeout=3)


def changed_paths(previous: dict[str, tuple[int, int]], current: dict[str, tuple[int, int]]) -> list[str]:
    changed = []
    for path, stat in current.items():
        if previous.get(path) != stat:
            changed.append(path)
    for path in previous:
        if path not in current:
            changed.append(path)
    return sorted(changed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Flet web server and restart after source changes.")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, help="seconds to wait after the last change before restart")
    parser.add_argument("--poll", type=float, default=POLL_INTERVAL_SECONDS, help="file scan interval in seconds")
    args = parser.parse_args()

    process: subprocess.Popen | None = None
    snapshot = snapshot_files()
    pending_restart_at: float | None = None

    try:
        process = start_server()
        _log(f"watching source files; restart after {args.delay:g}s quiet time")
        while True:
            time.sleep(max(0.1, args.poll))

            if process.poll() is not None:
                _log(f"child exited with code {process.returncode}; restarting")
                process = start_server()

            current = snapshot_files()
            changed = changed_paths(snapshot, current)
            if changed:
                snapshot = current
                pending_restart_at = time.monotonic() + max(0.0, args.delay)
                preview = ", ".join(changed[:5])
                suffix = "" if len(changed) <= 5 else f", +{len(changed) - 5} more"
                _log(f"change detected: {preview}{suffix}; waiting for quiet time")

            if pending_restart_at is not None and time.monotonic() >= pending_restart_at:
                pending_restart_at = None
                _log("quiet time reached; restarting web server")
                stop_server(process)
                process = start_server()
                snapshot = snapshot_files()
    except KeyboardInterrupt:
        _log("received Ctrl+C")
    finally:
        stop_server(process)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
