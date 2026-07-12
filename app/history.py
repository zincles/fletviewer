import dataclasses

from app.lazy import LazyProxy
from app.storage import ensure_dirs, get_storage_layout
from core.data.data_db import AppDataDB
from core.data.history import HistoryEntry, HistoryRepository
from core.download.manager import now_iso
from core.provider.ehgrabber import Comic, EHentaiClient


def _create_history_repository() -> HistoryRepository:
    return HistoryRepository(AppDataDB(get_storage_layout().data_db, ensure_dirs=ensure_dirs))


history_repository = LazyProxy(_create_history_repository)


def record_gallery_history(comic: Comic) -> HistoryEntry:
    """保存画廊列表 Comic 快照，供历史页重建统一画廊卡片。"""
    gid, _token = EHentaiClient.parse_url(comic.id)
    return history_repository.record(
        HistoryEntry(
            provider="ehentai",
            kind="gallery",
            source_id=str(gid),
            title=comic.title,
            url=comic.id,
            metadata=dataclasses.asdict(comic),
            created_at=now_iso(),
        )
    )


def history_entry_to_comic(entry: HistoryEntry) -> Comic:
    """从历史快照重建 Comic，并兼容未来新增字段。"""
    fields = {field.name for field in dataclasses.fields(Comic)}
    payload = {key: value for key, value in entry.metadata.items() if key in fields}
    payload.update(id=entry.url or payload.get("id", ""), title=entry.title or payload.get("title", ""))
    return Comic(**payload)


__all__ = ["HistoryEntry", "HistoryRepository", "history_entry_to_comic", "history_repository", "record_gallery_history"]
