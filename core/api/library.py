from __future__ import annotations

import base64
import dataclasses
import re
import threading
import zipfile
from pathlib import Path
from typing import Protocol

from core.api.dto import JSONValue, MediaItemDTO, json_safe
from core.api.errors import BackendError
from core.image.fetcher import ImageFetchCancelled


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_MAX_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_IMAGE_MEMBERS = 100_000
_MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024 * 1024


class LocalGalleryManagerPort(Protocol):
    def scan_local_galleries(self, *, force: bool = False) -> list[object]:
        ...


class HistoryRepositoryPort(Protocol):
    def record(self, entry: object) -> object:
        ...

    def list_entries(self, *, kind: str | None = None, limit: int = 500) -> list[object]:
        ...

    def clear(self, *, kind: str | None = None) -> None:
        ...


@dataclasses.dataclass(slots=True)
class LocalGalleryDTO:
    id: str
    provider: str
    source_id: str
    source_token: str
    title: str
    page_url: str = ""
    creator_name: str = ""
    category: str = ""
    language: str = ""
    page_count: int = 0
    rating: float = 0.0
    tags: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    archive_title: str = ""
    archive_filename: str = ""
    archive_bytes: int = 0
    archive_available: bool = False
    cover_available: bool = False
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, JSONValue] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(dataclasses.asdict(self))


@dataclasses.dataclass(slots=True)
class LocalGalleryPageDTO:
    index: int
    member_id: str
    title: str
    mime: str
    byte_length: int = 0

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(dataclasses.asdict(self))


@dataclasses.dataclass(slots=True)
class LocalResourceDTO:
    mime: str
    data_base64: str
    byte_length: int

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(dataclasses.asdict(self))


@dataclasses.dataclass(slots=True)
class HistoryItemDTO:
    id: str
    provider: str
    kind: str
    source_id: str
    title: str
    page_url: str
    created_at: str
    media: MediaItemDTO

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(dataclasses.asdict(self))


class LocalGalleryService:
    def __init__(self, manager: LocalGalleryManagerPort):
        self._manager = manager

    def list_galleries(self, *, force: bool = False) -> list[LocalGalleryDTO]:
        return [self._to_dto(item) for item in self._manager.scan_local_galleries(force=force)]

    def get_gallery(self, gallery_id: str) -> LocalGalleryDTO:
        return self._to_dto(self._find(gallery_id))

    def get_cover(self, gallery_id: str) -> LocalResourceDTO:
        gallery = self._find(gallery_id)
        path = self._file_path(gallery, "cover", required=True)
        data = path.read_bytes()
        return LocalResourceDTO(_mime_for_name(path.name), base64.b64encode(data).decode("ascii"), len(data))

    def list_pages(self, gallery_id: str) -> list[LocalGalleryPageDTO]:
        gallery = self._find(gallery_id)
        archive_path = self._file_path(gallery, "archive", required=True)
        with zipfile.ZipFile(archive_path) as archive:
            infos = _image_infos(archive)
            return [
                LocalGalleryPageDTO(index, info.filename, f"{self._title(gallery)} #{index + 1}", _mime_for_name(info.filename), info.file_size)
                for index, info in enumerate(infos)
            ]

    def read_page(
        self,
        gallery_id: str,
        member_id: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> LocalResourceDTO:
        gallery = self._find(gallery_id)
        archive_path = self._file_path(gallery, "archive", required=True)
        with zipfile.ZipFile(archive_path) as archive:
            allowed = {info.filename: info for info in _image_infos(archive)}
            info = allowed.get(str(member_id))
            if info is None:
                raise BackendError("local_page_not_found", f"本地画廊页面不存在: {member_id}")
            chunks: list[bytes] = []
            bytes_read = 0
            with archive.open(info) as source:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise ImageFetchCancelled("图像加载已取消")
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                    if bytes_read > _MAX_MEMBER_BYTES:
                        raise BackendError("local_page_too_large", f"图片实际解压大小过大: {bytes_read} bytes")
                    chunks.append(chunk)
        data = b"".join(chunks)
        return LocalResourceDTO(_mime_for_name(info.filename), base64.b64encode(data).decode("ascii"), len(data))

    def _find(self, gallery_id: str):
        for gallery in self._manager.scan_local_galleries(force=False):
            if self._id(gallery) == str(gallery_id):
                return gallery
        raise BackendError("local_gallery_not_found", f"本地画廊不存在: {gallery_id}")

    @staticmethod
    def _id(gallery) -> str:
        metadata = dict(gallery.metadata or {})
        source = dict(metadata.get("source") or {})
        provider = str(metadata.get("provider") or "ehentai")
        return f"{provider}:{source.get('gid') or ''}:{source.get('token') or ''}"

    @staticmethod
    def _title(gallery) -> str:
        details = dict(gallery.metadata.get("gallery") or {})
        return str(details.get("title") or gallery.dir_path.name)

    def _to_dto(self, gallery) -> LocalGalleryDTO:
        metadata = dict(gallery.metadata or {})
        source = dict(metadata.get("source") or {})
        details = dict(metadata.get("gallery") or {})
        archive = dict(metadata.get("archive") or {})
        files = dict(metadata.get("files") or {})
        provider = str(metadata.get("provider") or "ehentai")
        archive_path = self._file_path(gallery, "archive", required=False)
        cover_path = self._file_path(gallery, "cover", required=False)
        page_count = _int(details.get("page_count") or details.get("pages") or details.get("max_page"))
        rating = _float(details.get("rating") or details.get("stars") or details.get("rating_average"))
        tags = details.get("tags") if isinstance(details.get("tags"), dict) else {}
        return LocalGalleryDTO(
            id=self._id(gallery),
            provider=provider,
            source_id=str(source.get("gid") or ""),
            source_token=str(source.get("token") or ""),
            title=self._title(gallery),
            page_url=str(source.get("gallery_url") or ""),
            creator_name=str(details.get("creator_name") or details.get("uploader") or ""),
            category=str(details.get("category") or details.get("type") or "本地"),
            language=str(details.get("language") or details.get("language_detail") or ""),
            page_count=page_count,
            rating=rating,
            tags={str(key): [str(tag) for tag in values] for key, values in tags.items() if isinstance(values, list)},
            archive_title=str(archive.get("title") or ""),
            archive_filename=str(files.get("archive") or archive.get("filename") or ""),
            archive_bytes=_int(archive.get("bytes_total")),
            archive_available=archive_path is not None,
            cover_available=cover_path is not None,
            created_at=str(metadata.get("created_at") or ""),
            updated_at=str(metadata.get("updated_at") or ""),
            metadata={
                "storage_method": str(metadata.get("storage_method") or ""),
                "download_task_id": str(metadata.get("download_task_id") or ""),
                "domain": str(source.get("domain") or ""),
                "archive_id": str(archive.get("archive_id") or ""),
                "archive_description": str(archive.get("description") or ""),
            },
        )

    @staticmethod
    def _file_path(gallery, key: str, *, required: bool) -> Path | None:
        files = gallery.metadata.get("files") if isinstance(gallery.metadata, dict) else {}
        name = str((files or {}).get(key) or "")
        if not name or Path(name).name != name:
            if required:
                raise BackendError("local_file_missing", f"本地画廊 {key} 文件不存在")
            return None
        root = gallery.dir_path.resolve()
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            if required:
                raise BackendError("local_file_missing", f"本地画廊 {key} 文件不存在")
            return None
        return path


class HistoryService:
    def __init__(self, repository: HistoryRepositoryPort):
        self._repository = repository

    def list_items(self, *, kind: str = "gallery", limit: int = 500) -> list[HistoryItemDTO]:
        return [self._to_dto(entry) for entry in self._repository.list_entries(kind=kind, limit=limit)]

    def record_media(
        self,
        item: MediaItemDTO,
        *,
        kind: str = "gallery",
        source_id: str = "",
        created_at: str = "",
    ) -> HistoryItemDTO:
        from core.data.history import HistoryEntry
        from core.download.manager import now_iso

        entry = self._repository.record(HistoryEntry(
            provider=item.provider,
            kind=kind,
            source_id=source_id or item.id,
            title=item.title,
            url=item.page_url or item.id,
            metadata=item.to_dict(),
            created_at=created_at or now_iso(),
        ))
        return self._to_dto(entry)

    def clear(self, *, kind: str = "gallery") -> None:
        self._repository.clear(kind=kind)

    @staticmethod
    def _to_dto(entry) -> HistoryItemDTO:
        data = dict(entry.metadata or {})
        if "provider" in data and "thumbnail_url" in data:
            fields = {field.name for field in dataclasses.fields(MediaItemDTO)}
            media = MediaItemDTO(**{key: data[key] for key in fields if key in data})
        else:
            media = MediaItemDTO(
                provider=str(entry.provider or ""),
                id=str(data.get("id") or entry.url or entry.source_id),
                title=str(entry.title or data.get("title") or ""),
                thumbnail_url=str(data.get("cover") or ""),
                image_url=str(data.get("cover") or ""),
                page_url=str(entry.url or data.get("id") or ""),
                width=_int(data.get("cover_width")),
                height=_int(data.get("cover_height")),
                aspect_ratio=_float(data.get("cover_aspect_ratio")),
                subtitle=str(data.get("sub_title") or ""),
                description=str(data.get("description") or ""),
                tags={"general": [str(tag) for tag in data.get("tags", [])]} if isinstance(data.get("tags"), list) else {},
                page_count=_int(data.get("max_page")),
                creator_name=str(data.get("uploader") or ""),
                category=str(data.get("type") or ""),
                language=str(data.get("language") or ""),
                metadata={"stars": _float(data.get("stars"))},
            )
        return HistoryItemDTO(
            id=str(entry.id or ""),
            provider=str(entry.provider or ""),
            kind=str(entry.kind or ""),
            source_id=str(entry.source_id or ""),
            title=str(entry.title or ""),
            page_url=str(entry.url or ""),
            created_at=str(entry.created_at or ""),
            media=media,
        )


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]


def _image_infos(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = [info for info in archive.infolist() if not info.is_dir() and _is_image_member(info.filename)]
    if len(infos) > _MAX_IMAGE_MEMBERS:
        raise BackendError("local_archive_too_large", f"归档图片数量过多: {len(infos)}")
    if sum(info.file_size for info in infos) > _MAX_TOTAL_IMAGE_BYTES:
        raise BackendError("local_archive_too_large", "归档声明的图片总大小过大")
    infos.sort(key=lambda info: _natural_key(info.filename))
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise BackendError("local_archive_invalid", "归档包含重复的图片文件名")
    if any(info.file_size > _MAX_MEMBER_BYTES for info in infos):
        raise BackendError("local_page_too_large", "归档包含过大的图片")
    return infos


def _is_image_member(name: str) -> bool:
    path = Path(name)
    return "__MACOSX" not in path.parts and not any(part.startswith(".") for part in path.parts) and name.lower().endswith(_IMAGE_EXTS)


def _mime_for_name(name: str) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(Path(name).suffix.lower(), "application/octet-stream")


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
