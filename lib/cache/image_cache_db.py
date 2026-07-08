from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class ImageCacheDB:
    """SQLite index for image files; bytes stay on disk."""

    def __init__(self, cache_dir: Path, files_dir: Path, db_path: Path, legacy_index_path: Path):
        self.cache_dir = cache_dir
        self.files_dir = files_dir
        self.db_path = db_path
        self.legacy_index_path = legacy_index_path
        self._lock = threading.RLock()
        self._initialized = False

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def normalize_url(self, url: str) -> str:
        return url.strip()

    def resource_id_for_url(self, url: str) -> str:
        return hashlib.sha256(self.normalize_url(url).encode("utf-8")).hexdigest()

    def extension_from_mime_or_url(self, mime: str | None, url: str) -> str:
        if mime:
            clean_mime = mime.split(";", 1)[0].strip().lower()
            known = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "image/bmp": ".bmp",
                "image/svg+xml": ".svg",
            }
            ext = known.get(clean_mime)
            if ext:
                return ext
            guessed = mimetypes.guess_extension(clean_mime)
            if guessed:
                return guessed

        suffix = Path(urlsplit(url).path).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}:
            return ".jpg" if suffix == ".jpeg" else suffix
        return ".img"

    def filename_for_url(self, url: str, mime: str | None = None) -> str:
        return f"{self.resource_id_for_url(url)}{self.extension_from_mime_or_url(mime, url)}"

    def path_for_filename(self, filename: str) -> Path:
        return self.files_dir / filename[:2] / filename[2:4] / filename

    def cached_path_for_url(self, url: str, mime: str | None = None) -> Path:
        return self.path_for_filename(self.filename_for_url(url, mime=mime))

    def get_cached_filename(self, url: str) -> str | None:
        normalized = self.normalize_url(url)
        with self._connect() as conn:
            row = conn.execute("SELECT filename FROM image_url_cache WHERE url = ?", (normalized,)).fetchone()
        return str(row[0]) if row else None

    def get_cached_path(self, url: str) -> Path | None:
        filename = self.get_cached_filename(url)
        if not filename:
            return None
        path = self.path_for_filename(filename)
        return path if path.exists() else None

    def put_cached_filename(self, url: str, filename: str, *, kind: str = "unknown") -> None:
        normalized = self.normalize_url(url)
        created = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO image_url_cache(url, filename, kind, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET filename = excluded.filename, kind = excluded.kind
                """,
                (normalized, filename, kind or "unknown", created),
            )

    def drop_cached_filename(self, url: str) -> str | None:
        normalized = self.normalize_url(url)
        with self._connect() as conn:
            row = conn.execute("SELECT filename FROM image_url_cache WHERE url = ?", (normalized,)).fetchone()
            conn.execute("DELETE FROM image_url_cache WHERE url = ?", (normalized,))
        return str(row[0]) if row else None

    def repair_stale_entry(self, url: str) -> bool:
        filename = self.get_cached_filename(url)
        if not filename:
            return False
        if self.path_for_filename(filename).exists():
            return False
        self.drop_cached_filename(url)
        return True

    def get_gallery_page_cached_filename(self, provider: str, gid: str, token: str, page_idx: int) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT filename FROM gallery_page_cache
                WHERE provider = ? AND gid = ? AND token = ? AND page_idx = ?
                """,
                (provider, str(gid), str(token), int(page_idx)),
            ).fetchone()
        return str(row[0]) if row else None

    def get_gallery_page_cached_path(self, provider: str, gid: str, token: str, page_idx: int) -> Path | None:
        filename = self.get_gallery_page_cached_filename(provider, gid, token, page_idx)
        if not filename:
            return None
        path = self.path_for_filename(filename)
        return path if path.exists() else None

    def put_gallery_page_cached_filename(
        self,
        provider: str,
        gid: str,
        token: str,
        page_idx: int,
        filename: str,
        *,
        kind: str = "original",
    ) -> None:
        created = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gallery_page_cache(provider, gid, token, page_idx, filename, kind, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, gid, token, page_idx)
                DO UPDATE SET filename = excluded.filename, kind = excluded.kind
                """,
                (provider, str(gid), str(token), int(page_idx), filename, kind or "original", created),
            )

    def drop_gallery_page_cached_filename(self, provider: str, gid: str, token: str, page_idx: int) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT filename FROM gallery_page_cache
                WHERE provider = ? AND gid = ? AND token = ? AND page_idx = ?
                """,
                (provider, str(gid), str(token), int(page_idx)),
            ).fetchone()
            conn.execute(
                """
                DELETE FROM gallery_page_cache
                WHERE provider = ? AND gid = ? AND token = ? AND page_idx = ?
                """,
                (provider, str(gid), str(token), int(page_idx)),
            )
        return str(row[0]) if row else None

    def repair_gallery_page_entry(self, provider: str, gid: str, token: str, page_idx: int) -> bool:
        filename = self.get_gallery_page_cached_filename(provider, gid, token, page_idx)
        if not filename:
            return False
        if self.path_for_filename(filename).exists():
            return False
        self.drop_gallery_page_cached_filename(provider, gid, token, page_idx)
        return True

    def clear(self) -> None:
        with self._lock:
            shutil.rmtree(self.files_dir, ignore_errors=True)
            self._initialized = False
            self.ensure_dirs()
            self._init_db_locked()
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM image_url_cache")
                conn.execute("DELETE FROM gallery_page_cache")

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if not self._initialized:
                self.ensure_dirs()
                self._init_db_locked()
                self._migrate_legacy_index_locked()
                self._initialized = True
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db_locked(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS image_url_cache (
                    url TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'unknown',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gallery_page_cache (
                    provider TEXT NOT NULL,
                    gid TEXT NOT NULL,
                    token TEXT NOT NULL,
                    page_idx INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'original',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (provider, gid, token, page_idx)
                )
                """
            )

    def _migrate_legacy_index_locked(self) -> None:
        if not self.legacy_index_path.exists():
            return
        migrated_path = self.legacy_index_path.with_name(self.legacy_index_path.name + ".migrated")
        try:
            data = json.loads(self.legacy_index_path.read_text(encoding="utf-8"))
        except Exception:
            self.legacy_index_path.rename(migrated_path)
            return
        if not isinstance(data, dict):
            self.legacy_index_path.rename(migrated_path)
            return
        created = _now_iso()
        with sqlite3.connect(self.db_path) as conn:
            for url, filename in data.items():
                filename = str(filename)
                if not self.path_for_filename(filename).exists():
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO image_url_cache(url, filename, kind, created_at)
                    VALUES (?, ?, 'unknown', ?)
                    """,
                    (self.normalize_url(str(url)), filename, created),
                )
        target = migrated_path
        counter = 1
        while target.exists():
            target = self.legacy_index_path.with_name(f"{self.legacy_index_path.name}.migrated.{counter}")
            counter += 1
        self.legacy_index_path.rename(target)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
