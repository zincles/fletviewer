from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from core.storage import AppStoragePaths, StorageLayout


@dataclass(frozen=True, slots=True)
class ResolvedStorage:
    paths: AppStoragePaths
    layout: StorageLayout
    sources: dict[str, str]


def resolve_storage(
    environ: Mapping[str, str] | None = None,
    *,
    cwd: Path | None = None,
) -> ResolvedStorage:
    """解析目标四域路径；不创建目录，也不迁移现有数据。"""
    env = os.environ if environ is None else environ
    base_cwd = Path.cwd() if cwd is None else Path(cwd)
    flet_data = env.get("FLET_APP_STORAGE_DATA")
    flet_temp = env.get("FLET_APP_STORAGE_TEMP")
    configured_home = env.get("FLETVIEWER_HOME")

    if flet_data:
        data_root = _absolute(Path(flet_data), base_cwd)
        data = data_root / "Data"
        downloads = data_root / "Downloads"
        data_source = "FLET_APP_STORAGE_DATA"
    else:
        home = _absolute(Path(configured_home or "FletViewer"), base_cwd)
        data = home / "Data"
        downloads = home / "Downloads"
        data_source = "FLETVIEWER_HOME" if configured_home else "desktop fallback"

    if flet_temp:
        temporary_root = _absolute(Path(flet_temp), base_cwd)
        cache = temporary_root / "Cache"
        temp = temporary_root / "Temp"
        temporary_source = "FLET_APP_STORAGE_TEMP"
    else:
        home = _absolute(Path(configured_home or "FletViewer"), base_cwd)
        cache = home / "Cache"
        temp = home / "Temp"
        temporary_source = "FLETVIEWER_HOME" if configured_home else "desktop fallback"

    paths = AppStoragePaths(
        data=data,
        cache=cache,
        downloads=downloads,
        temp=temp,
    ).resolved()
    return ResolvedStorage(
        paths=paths,
        layout=StorageLayout.from_paths(paths),
        sources={
            "data": data_source,
            "cache": temporary_source,
            "downloads": data_source,
            "temp": temporary_source,
        },
    )


def _absolute(path: Path, cwd: Path) -> Path:
    path = path.expanduser()
    return path if path.is_absolute() else cwd / path
