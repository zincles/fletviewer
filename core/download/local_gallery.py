from __future__ import annotations

import json
import shutil
import threading
import zipfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from pathvalidate import sanitize_filename
except ModuleNotFoundError:
    def sanitize_filename(value: str, platform: str = "windows") -> str:
        invalid = '<>:"/\\|?*\0'
        return "".join("_" if ch in invalid or ord(ch) < 32 else ch for ch in value)

from core.data.data_db import AppDataDB
from core.atomic_file import atomic_write_bytes, atomic_write_json
from core.download.manager import DownloadManager, DownloadTask, now_iso
from core.notification import Notification


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_MAX_COVER_BYTES = 64 * 1024 * 1024


@dataclass
class LocalGallery:
    dir_path: Path
    metadata: dict


class LocalGalleryManager:
    def __init__(
        self,
        *,
        archive_dir: Path,
        data_db: AppDataDB,
        ensure_dirs: Callable[[], None],
        download_manager: DownloadManager,
        log_exception: Callable[[str, str], None] | None = None,
        notify: Callable[[Notification], None] | None = None,
    ):
        self.archive_dir = archive_dir
        self.data_db = data_db
        self._ensure_dirs = ensure_dirs
        self._download_manager = download_manager
        self._log_exception = log_exception or (lambda _area, _message: None)
        self._notify = notify or (lambda _notification: None)
        self._lock = threading.RLock()
        self._galleries: list[LocalGallery] | None = None

    def initialize(self) -> None:
        self._ensure_dirs()
        self._download_manager.add_completion_handler(self.handle_download_completed)
        self._download_manager.initialize()
        self.scan_local_galleries()

    def handle_download_completed(self, task: DownloadTask) -> None:
        if "eh_archive" not in task.tags:
            return
        try:
            archive_source = task.final_file_path
            if not archive_source.exists():
                raise FileNotFoundError(str(archive_source))

            tag_data = task.tag_data
            gid = str(tag_data.get("gid") or "unknown")
            token = str(tag_data.get("token") or "unknown")
            title = tag_data.get("gallery_details", {}).get("title") or tag_data.get("title") or "未命名"
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            gallery_dir = self.archive_dir / self._eh_archive_folder_name(gid, token, title)
            if self._is_committed_gallery(gallery_dir, task.id):
                self._upsert_gallery(gallery_dir, self._read_gallery_metadata(gallery_dir))
                archive_source.unlink(missing_ok=True)
                self._download_manager.mark_consumed(task.id)
                return
            if gallery_dir.exists():
                gallery_dir = self._unique_path(gallery_dir)
            staging_dir = self.archive_dir / f".{gallery_dir.name}.{task.id}.staging"
            shutil.rmtree(staging_dir, ignore_errors=True)
            staging_dir.mkdir(parents=True)
            archive_name = sanitize_filename(task.filename or "archive.zip", platform="windows").strip() or "archive.zip"
            try:
                staging_archive = staging_dir / archive_name
                shutil.copy2(archive_source, staging_archive)
                self._validate_archive(staging_archive)
                cover_filename = self._extract_cover_from_zip(staging_archive, staging_dir)
                metadata = self._build_gallery_metadata(task, staging_archive, cover_filename)
                atomic_write_json(staging_dir / "gallery.json", metadata)
                staging_dir.replace(gallery_dir)
            except Exception:
                shutil.rmtree(staging_dir, ignore_errors=True)
                raise
            self._upsert_gallery(gallery_dir, metadata)
            archive_source.unlink(missing_ok=True)
            self._download_manager.mark_consumed(task.id)
            self._notify(Notification("本地画廊已归档", title, "gallery.archived", {"task_id": task.id}))
            self.scan_local_galleries(force=True)
        except Exception as ex:
            self._download_manager.mark_consumed(task.id, consume_error=str(ex))
            self._exception(f"消费下载任务失败 {task.id}：{ex}")
            self._notify(Notification("本地画廊归档失败", title if 'title' in locals() else task.filename, "gallery.archive_failed", {"task_id": task.id}))

    def scan_local_galleries(self, *, force: bool = False) -> list[LocalGallery]:
        with self._lock:
            if self._galleries is not None and not force:
                return list(self._galleries)
            if not force:
                galleries = self._load_galleries_from_db()
                if galleries:
                    self._galleries = galleries
                    return list(galleries)
            galleries: list[LocalGallery] = []
            if self.archive_dir.exists():
                for entry in sorted(self.archive_dir.iterdir(), key=lambda p: p.name.lower()):
                    if not entry.is_dir():
                        continue
                    gallery_json = entry / "gallery.json"
                    if not gallery_json.exists():
                        continue
                    try:
                        data = json.loads(gallery_json.read_text(encoding="utf-8"))
                        self._validate_gallery_metadata(entry, data)
                        galleries.append(LocalGallery(dir_path=entry, metadata=data))
                        self._upsert_gallery(entry, data)
                    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError) as ex:
                        target = gallery_json.with_name(f"gallery.json.corrupt-{uuid.uuid4().hex}")
                        try:
                            gallery_json.replace(target)
                        except OSError:
                            pass
                        self._exception(f"扫描本地画廊失败 {entry}：{ex}")
            self._galleries = galleries
            return list(galleries)

    def list_galleries(self) -> list[LocalGallery]:
        return self.scan_local_galleries()

    def get_gallery(self, gid: str, token: str) -> LocalGallery | None:
        for gallery in self.scan_local_galleries():
            source = gallery.metadata.get("source", {})
            if str(source.get("gid")) == str(gid) and str(source.get("token")) == str(token):
                return gallery
        return None

    def _eh_archive_folder_name(self, gid: str, token: str, title: str) -> str:
        safe_title = sanitize_filename(title or "未命名", platform="windows").strip()
        if not safe_title:
            safe_title = "未命名"
        prefix = f"[{gid}][{token}] "
        max_title_len = max(1, 180 - len(prefix))
        safe_title = safe_title[:max_title_len].rstrip(" .") or "未命名"
        return f"{prefix}{safe_title}"

    def _extract_cover_from_zip(self, zip_path: Path, output_dir: Path) -> str:
        with zipfile.ZipFile(zip_path) as zf:
            names = sorted(name for name in zf.namelist() if self._is_image_member(name))
            if not names:
                return ""
            first = names[0]
            info = zf.getinfo(first)
            if info.file_size > _MAX_COVER_BYTES:
                raise ValueError(f"封面过大，拒绝解压: {info.file_size} bytes")
            data = zf.read(first)
            ext = Path(first).suffix.lower()
            if ext == ".jpeg":
                ext = ".jpg"
            cover_filename = f"thumb{ext}"
            atomic_write_bytes(output_dir / cover_filename, data)
            return cover_filename

    def _validate_archive(self, zip_path: Path) -> None:
        with zipfile.ZipFile(zip_path) as archive:
            archive.infolist()

    def _validate_gallery_metadata(self, gallery_dir: Path, metadata: object) -> None:
        if not isinstance(metadata, dict):
            raise ValueError("gallery.json 根节点必须是对象")
        if int(metadata.get("schema_version") or 0) != 1:
            raise ValueError("不支持的 gallery.json schema")
        source = metadata.get("source")
        files = metadata.get("files")
        if not isinstance(source, dict) or not source.get("gid") or not source.get("token"):
            raise ValueError("gallery.json source 不完整")
        if not isinstance(files, dict):
            raise ValueError("gallery.json files 必须是对象")
        archive_name = str(files.get("archive") or "")
        if not archive_name or Path(archive_name).name != archive_name:
            raise ValueError("gallery.json 归档文件名无效")
        if not (gallery_dir / archive_name).is_file():
            raise ValueError("画廊归档文件缺失")
        cover_name = str(files.get("cover") or "")
        if cover_name and Path(cover_name).name != cover_name:
            raise ValueError("gallery.json 封面文件名无效")

    def _is_image_member(self, name: str) -> bool:
        path = Path(name)
        parts = set(path.parts)
        if "__MACOSX" in parts:
            return False
        if any(part.startswith(".") for part in path.parts):
            return False
        return name.lower().endswith(_IMAGE_EXTS)

    def _build_gallery_metadata(self, task: DownloadTask, archive_path: Path, cover_filename: str) -> dict:
        tag_data = task.tag_data
        created = now_iso()
        return {
            "schema_version": 1,
            "provider": "ehentai",
            "storage_method": "eh_archive_zip",
            "download_task_id": task.id,
            "source": {
                "gid": tag_data.get("gid", ""),
                "token": tag_data.get("token", ""),
                "gallery_url": tag_data.get("gallery_url", ""),
                "domain": tag_data.get("domain", "e-hentai.org"),
            },
            "gallery": tag_data.get("gallery_details", {}),
            "thumbnails": tag_data.get("thumbnails_result", {}),
            "archive": {
                "archive_id": tag_data.get("archive_id", ""),
                "title": tag_data.get("archive_title", ""),
                "description": tag_data.get("archive_description", ""),
                "download_url": task.url,
                "download_url_acquired_at": tag_data.get("download_url_acquired_at", ""),
                "download_completed_at": task.completed_at or "",
                "download_url_valid_seconds": tag_data.get("download_url_valid_seconds", 86400),
                "max_ip_count": tag_data.get("max_ip_count", 2),
                "filename": archive_path.name,
                "bytes_total": task.bytes_total,
            },
            "files": {"archive": archive_path.name, "cover": cover_filename},
            "created_at": created,
            "updated_at": created,
        }

    def _read_gallery_metadata(self, gallery_dir: Path) -> dict:
        data = json.loads((gallery_dir / "gallery.json").read_text(encoding="utf-8"))
        self._validate_gallery_metadata(gallery_dir, data)
        return data

    def _is_committed_gallery(self, gallery_dir: Path, task_id: str) -> bool:
        if not gallery_dir.is_dir():
            return False
        try:
            return self._read_gallery_metadata(gallery_dir).get("download_task_id") == task_id
        except Exception:
            return False

    def _unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        for idx in range(1, 1000):
            candidate = path.with_name(f"{stem} ({idx}){suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(str(path))

    def _load_galleries_from_db(self) -> list[LocalGallery]:
        with self.data_db.connect() as conn:
            rows = conn.execute(
                "SELECT dir_path, metadata_json FROM local_galleries ORDER BY updated_at DESC"
            ).fetchall()
        galleries: list[LocalGallery] = []
        for dir_path, metadata_json in rows:
            path = Path(dir_path)
            if not path.exists():
                continue
            try:
                galleries.append(LocalGallery(dir_path=path, metadata=json.loads(metadata_json)))
            except Exception as ex:
                self._exception(f"从数据库加载画廊失败 {dir_path}：{ex}")
        return galleries

    def _upsert_gallery(self, dir_path: Path, metadata: dict) -> None:
        source = metadata.get("source", {})
        files = metadata.get("files", {})
        gallery = metadata.get("gallery", {})
        archive = metadata.get("archive", {})
        provider = str(metadata.get("provider") or source.get("provider") or "ehentai")
        gid = str(source.get("gid") or "")
        token = str(source.get("token") or "")
        if not gid or not token:
            return
        created = str(metadata.get("created_at") or now_iso())
        updated = str(metadata.get("updated_at") or created)
        with self.data_db.connect() as conn:
            conn.execute(
                """
                INSERT INTO local_galleries(
                    provider, gid, token, dir_path, title, gallery_url, archive_filename,
                    cover_filename, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, gid, token) DO UPDATE SET
                    dir_path = excluded.dir_path,
                    title = excluded.title,
                    gallery_url = excluded.gallery_url,
                    archive_filename = excluded.archive_filename,
                    cover_filename = excluded.cover_filename,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    provider,
                    gid,
                    token,
                    dir_path.as_posix(),
                    gallery.get("title") or dir_path.name,
                    source.get("gallery_url", ""),
                    files.get("archive") or archive.get("filename", ""),
                    files.get("cover", ""),
                    json.dumps(metadata, ensure_ascii=False),
                    created,
                    updated,
                ),
            )

    def _exception(self, message: str) -> None:
        self._log_exception("本地画廊", message)
