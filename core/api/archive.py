from __future__ import annotations

import dataclasses
from typing import Callable, Protocol
from urllib.parse import urlsplit

from core.api.dto import JSONValue, json_safe
from core.download.manager import now_iso


class ArchiveDownloadManager(Protocol):
    def create_task(
        self,
        url: str,
        filename: str,
        *,
        tags: list[str] | None = None,
        tag_data: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        ...

    def start_task(self, task_id: str) -> None:
        ...


@dataclasses.dataclass(slots=True)
class ArchiveOptionDTO:
    id: str
    title: str
    description: str = ""
    available: bool = True
    metadata: dict[str, JSONValue] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(dataclasses.asdict(self))


@dataclasses.dataclass(slots=True)
class TaskStartedDTO:
    task_id: str
    status: str = "queued"
    provider: str = ""
    kind: str = ""
    title: str = ""
    metadata: dict[str, JSONValue] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(dataclasses.asdict(self))


class EHArchiveService:
    """UI-independent EH Archive orchestration over provider and download ports."""

    def __init__(
        self,
        *,
        get_eh_client: Callable[..., object],
        get_download_manager: Callable[[], ArchiveDownloadManager],
    ):
        self._get_eh_client = get_eh_client
        self._get_download_manager = get_download_manager

    def list_options(self, gallery_url: str) -> list[ArchiveOptionDTO]:
        client = self._get_eh_client(require_login=True)
        return [
            ArchiveOptionDTO(
                id=str(option.id),
                title=str(option.title or ""),
                description=str(option.description or ""),
                available=not str(option.id).startswith("h@h_"),
                metadata={"delivery": "hath" if str(option.id).startswith("h@h_") else "archive"},
            )
            for option in client.get_archives(gallery_url)
        ]

    def start_download(self, gallery_url: str, archive_id: str) -> TaskStartedDTO:
        client = self._get_eh_client(require_login=True)
        options = client.get_archives(gallery_url)
        option = next((item for item in options if str(item.id) == str(archive_id)), None)
        if option is None:
            raise ValueError(f"未知 Archive 选项: {archive_id}")
        if str(option.id).startswith("h@h_"):
            raise ValueError("H@H 下载选项不能创建 Archive 任务")

        details = client.load_comic_info(gallery_url)
        thumbnails = client.load_thumbnails(gallery_url)
        download_url = client.get_archive_download_url(gallery_url, str(option.id))
        if not download_url:
            raise RuntimeError("该 Archive 选项未返回可下载 URL")

        gid, token = client.parse_url(gallery_url)
        manager = self._get_download_manager()
        task = manager.create_task(
            download_url,
            "archive.zip",
            tags=["eh_archive"],
            headers={"Referer": gallery_url},
            tag_data={
                "provider": "ehentai",
                "domain": urlsplit(gallery_url).netloc or "e-hentai.org",
                "gallery_url": gallery_url,
                "gid": str(gid),
                "token": token,
                "archive_id": str(option.id),
                "archive_title": str(option.title or ""),
                "archive_description": str(option.description or ""),
                "download_url_acquired_at": now_iso(),
                "download_url_valid_seconds": 86400,
                "max_ip_count": 2,
                "gallery_details": json_safe(dataclasses.asdict(details)),
                "thumbnails_result": json_safe(dataclasses.asdict(thumbnails)),
            },
        )
        task_id = str(getattr(task, "id"))
        manager.start_task(task_id)
        return TaskStartedDTO(
            task_id=task_id,
            status=str(getattr(task, "status", "queued") or "queued"),
            provider="ehentai",
            kind="archive",
            title=str(option.title or ""),
            metadata={"gallery_url": gallery_url, "archive_id": str(option.id)},
        )
