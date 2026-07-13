from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StorageRoot:
    key: str
    path: Path
    description: str


@dataclass(frozen=True, slots=True)
class StorageEntry:
    name: str
    path: Path
    is_dir: bool
    size: int
    mtime: float


def resolve_under_root(root: Path, target: Path) -> Path:
    """确保 target 位于 root 内，防止路径逃逸。"""
    root_resolved = root.expanduser().resolve()
    target_resolved = target.expanduser().resolve()
    target_resolved.relative_to(root_resolved)
    return target_resolved


def list_entries(root: Path, current: Path) -> list[StorageEntry]:
    current_resolved = resolve_under_root(root, current)
    if not current_resolved.exists():
        raise FileNotFoundError(str(current_resolved))
    if not current_resolved.is_dir():
        raise NotADirectoryError(str(current_resolved))

    entries: list[StorageEntry] = []
    for child in current_resolved.iterdir():
        try:
            stat = child.stat()
            entries.append(
                StorageEntry(
                    name=child.name,
                    path=child,
                    is_dir=child.is_dir(),
                    size=0 if child.is_dir() else int(stat.st_size),
                    mtime=float(stat.st_mtime),
                )
            )
        except OSError:
            entries.append(
                StorageEntry(
                    name=child.name,
                    path=child,
                    is_dir=child.is_dir(),
                    size=0,
                    mtime=0.0,
                )
            )
    entries.sort(key=lambda item: (not item.is_dir, item.name.casefold()))
    return entries


def format_size(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(value)} B"
