from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from core.sqlite_recovery import run_with_corruption_recovery


class AppDataDB:
    def __init__(self, db_path: Path, *, ensure_dirs=None):
        self.db_path = db_path
        self._ensure_dirs = ensure_dirs

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.ensure_schema()
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        if self._ensure_dirs:
            self._ensure_dirs()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        run_with_corruption_recovery(self.db_path, self._ensure_schema_once)

    def _ensure_schema_once(self) -> None:
        with closing(sqlite3.connect(self.db_path, timeout=10)) as conn:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS download_tasks (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT,
                    source_url TEXT,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_download_tasks_updated ON download_tasks(updated_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_download_tasks_status ON download_tasks(status)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS local_galleries (
                    provider TEXT NOT NULL,
                    gid TEXT NOT NULL,
                    token TEXT NOT NULL,
                    dir_path TEXT NOT NULL,
                    title TEXT,
                    gallery_url TEXT,
                    archive_filename TEXT,
                    cover_filename TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (provider, gid, token)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_local_galleries_updated ON local_galleries(updated_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT,
                    kind TEXT NOT NULL,
                    source_id TEXT,
                    title TEXT,
                    url TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at)")
            conn.commit()
