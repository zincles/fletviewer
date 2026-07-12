from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar


_CORRUPTION_MESSAGES = (
    "file is not a database",
    "database disk image is malformed",
    "file is encrypted",
    "malformed database schema",
)
_T = TypeVar("_T")
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[Path, threading.RLock] = {}


def is_corrupt_database_error(error: BaseException) -> bool:
    """只识别明确的数据损坏，不把锁、权限或磁盘错误误判为损坏。"""
    return isinstance(error, sqlite3.DatabaseError) and any(
        message in str(error).lower() for message in _CORRUPTION_MESSAGES
    )


def quarantine_database(db_path: Path) -> list[Path]:
    """保留损坏的 SQLite 主文件及 WAL/SHM，并返回隔离后的路径。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    quarantined = []
    for path in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if not path.exists():
            continue
        target = path.with_name(f"{path.name}.corrupt-{stamp}")
        path.replace(target)
        quarantined.append(target)
    return quarantined


def run_with_corruption_recovery(db_path: Path, operation: Callable[[], _T]) -> _T:
    """串行初始化同一数据库；仅在明确损坏时隔离并重试一次。"""
    lock = _lock_for(db_path)
    with lock:
        try:
            return operation()
        except sqlite3.DatabaseError as ex:
            if not is_corrupt_database_error(ex):
                raise
            quarantine_database(db_path)
            return operation()


def _lock_for(db_path: Path) -> threading.RLock:
    key = db_path.expanduser().resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())
