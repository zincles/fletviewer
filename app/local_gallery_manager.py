from __future__ import annotations

import json
import shutil
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path

try:
    from pathvalidate import sanitize_filename
except ModuleNotFoundError:
    def sanitize_filename(value: str, platform: str = "windows") -> str:
        invalid = '<>:"/\\|?*\0'
        return "".join("_" if ch in invalid or ord(ch) < 32 else ch for ch in value)

from app.debug_log import log_exception
from app.download_manager import DownloadTask, download_manager, now_iso
from app.storage import EH_ARCHIVE_DIR, ensure_download_dirs


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


@dataclass
class LocalGallery:
    """本地已归档画廊及其 metadata。"""

    dir_path: Path
    metadata: dict


class LocalGalleryManager:
    """消费下载完成的 EH Archive ZIP，并维护本地画廊索引。"""

    def __init__(self):
        """初始化内存索引和锁。"""
        self._lock = threading.RLock()
        self._galleries: list[LocalGallery] | None = None

    def initialize(self) -> None:
        """注册下载完成回调，并扫描已有本地画廊。"""
        ensure_download_dirs()
        download_manager.add_completion_handler(self.handle_download_completed)
        download_manager.initialize()
        self.scan_local_galleries()

    def handle_download_completed(self, task: DownloadTask) -> None:
        """消费已完成的 EH Archive 下载任务，创建本地画廊目录。"""
        if "eh_archive" not in task.tags:
            return
        try:
            archive_source = task.final_file_path
            if not archive_source.exists():
                raise FileNotFoundError(str(archive_source))

            tag_data = task.tag_data
            gid = str(tag_data.get("gid") or "unknown")
            token = str(tag_data.get("token") or "unknown")
            title = tag_data.get("gallery_details", {}).get("title") or tag_data.get("title") or "Untitled"
            gallery_dir = EH_ARCHIVE_DIR / self._eh_archive_folder_name(gid, token, title)
            gallery_dir.mkdir(parents=True, exist_ok=True)

            archive_name = sanitize_filename(task.filename or "archive.zip", platform="windows").strip() or "archive.zip"
            archive_path = self._unique_path(gallery_dir / archive_name)
            shutil.move(str(archive_source), str(archive_path))

            cover_filename = ""
            try:
                cover_filename = self._extract_cover_from_zip(archive_path, gallery_dir)
            except Exception as ex:
                log_exception("local_gallery", f"extract cover failed {archive_path}: {ex}")

            metadata = self._build_gallery_metadata(task, archive_path, cover_filename)
            (gallery_dir / "gallery.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            download_manager.mark_consumed(task.id)
            self.scan_local_galleries(force=True)
        except Exception as ex:
            download_manager.mark_consumed(task.id, consume_error=str(ex))
            log_exception("local_gallery", f"consume failed {task.id}: {ex}")

    def scan_local_galleries(self, *, force: bool = False) -> list[LocalGallery]:
        """扫描本地 EHArchieve 目录，读取所有 gallery.json。"""
        with self._lock:
            if self._galleries is not None and not force:
                return list(self._galleries)
            galleries: list[LocalGallery] = []
            if EH_ARCHIVE_DIR.exists():
                for entry in sorted(EH_ARCHIVE_DIR.iterdir(), key=lambda p: p.name.lower()):
                    if not entry.is_dir():
                        continue
                    gallery_json = entry / "gallery.json"
                    if not gallery_json.exists():
                        continue
                    try:
                        data = json.loads(gallery_json.read_text(encoding="utf-8"))
                        galleries.append(LocalGallery(dir_path=entry, metadata=data))
                    except Exception as ex:
                        log_exception("local_gallery", f"scan failed {entry}: {ex}")
            self._galleries = galleries
            return list(galleries)

    def list_galleries(self) -> list[LocalGallery]:
        """返回当前本地画廊列表。"""
        return self.scan_local_galleries()

    def get_gallery(self, gid: str, token: str) -> LocalGallery | None:
        """按 EH gid/token 查找本地画廊。"""
        for gallery in self.scan_local_galleries():
            source = gallery.metadata.get("source", {})
            if str(source.get("gid")) == str(gid) and str(source.get("token")) == str(token):
                return gallery
        return None

    def _eh_archive_folder_name(self, gid: str, token: str, title: str) -> str:
        """生成跨平台安全的 EH Archive 本地目录名。"""
        safe_title = sanitize_filename(title or "Untitled", platform="windows").strip()
        if not safe_title:
            safe_title = "Untitled"
        prefix = f"[{gid}][{token}] "
        max_title_len = max(1, 180 - len(prefix))
        safe_title = safe_title[:max_title_len].rstrip(" .") or "Untitled"
        return f"{prefix}{safe_title}"

    def _extract_cover_from_zip(self, zip_path: Path, output_dir: Path) -> str:
        """从 ZIP 中提取排序后的第一张图片作为 thumb 封面。"""
        with zipfile.ZipFile(zip_path) as zf:
            names = sorted(
                name for name in zf.namelist()
                if self._is_image_member(name)
            )
            if not names:
                return ""
            first = names[0]
            data = zf.read(first)
            ext = Path(first).suffix.lower()
            if ext == ".jpeg":
                ext = ".jpg"
            cover_filename = f"thumb{ext}"
            (output_dir / cover_filename).write_bytes(data)
            return cover_filename

    def _is_image_member(self, name: str) -> bool:
        """判断 ZIP member 是否是可用于封面的图片文件。"""
        path = Path(name)
        parts = set(path.parts)
        if "__MACOSX" in parts:
            return False
        if any(part.startswith(".") for part in path.parts):
            return False
        return name.lower().endswith(_IMAGE_EXTS)

    def _build_gallery_metadata(self, task: DownloadTask, archive_path: Path, cover_filename: str) -> dict:
        """根据下载任务构建本地 gallery.json 元数据。"""
        tag_data = task.tag_data
        created = now_iso()
        return {
            "schema_version": 1,
            "provider": "ehentai",
            "storage_method": "eh_archive_zip",
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
            "files": {
                "archive": archive_path.name,
                "cover": cover_filename,
            },
            "created_at": created,
            "updated_at": created,
        }

    def _unique_path(self, path: Path) -> Path:
        """如果目标文件已存在，追加序号生成不冲突路径。"""
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        for idx in range(1, 1000):
            candidate = path.with_name(f"{stem} ({idx}){suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(str(path))


local_gallery_manager = LocalGalleryManager()
