from __future__ import annotations

import json
from dataclasses import dataclass, field

from core.data.data_db import AppDataDB


@dataclass
class HistoryEntry:
    provider: str
    kind: str
    source_id: str
    title: str
    url: str
    metadata: dict = field(default_factory=dict)
    created_at: str = ""
    id: int | None = None


class HistoryRepository:
    """持久化最近访问记录；同一资源只保留最新快照。"""

    def __init__(self, data_db: AppDataDB):
        self.data_db = data_db

    def record(self, entry: HistoryEntry) -> HistoryEntry:
        with self.data_db.connect() as conn:
            conn.execute(
                "DELETE FROM history WHERE provider = ? AND kind = ? AND source_id = ?",
                (entry.provider, entry.kind, entry.source_id),
            )
            cursor = conn.execute(
                """
                INSERT INTO history(provider, kind, source_id, title, url, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.provider,
                    entry.kind,
                    entry.source_id,
                    entry.title,
                    entry.url,
                    json.dumps(entry.metadata, ensure_ascii=False),
                    entry.created_at,
                ),
            )
            entry.id = int(cursor.lastrowid)
        return entry

    def list_entries(self, *, kind: str | None = None, limit: int = 500) -> list[HistoryEntry]:
        query = "SELECT id, provider, kind, source_id, title, url, metadata_json, created_at FROM history"
        params: list[object] = []
        if kind:
            query += " WHERE kind = ?"
            params.append(kind)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self.data_db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            HistoryEntry(
                id=row[0],
                provider=row[1] or "",
                kind=row[2],
                source_id=row[3] or "",
                title=row[4] or "",
                url=row[5] or "",
                metadata=json.loads(row[6] or "{}"),
                created_at=row[7],
            )
            for row in rows
        ]

    def clear(self, *, kind: str | None = None) -> None:
        with self.data_db.connect() as conn:
            if kind:
                conn.execute("DELETE FROM history WHERE kind = ?", (kind,))
            else:
                conn.execute("DELETE FROM history")


__all__ = ["HistoryEntry", "HistoryRepository"]
