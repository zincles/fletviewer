from __future__ import annotations

import json
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.storage import StorageLayout

MARKER_NAME = ".storage-layout-v1"


@dataclass(slots=True)
class MigrationResult:
    performed: bool
    marker: Path
    moved: list[str]
    notes: list[str]


def migrate_legacy_storage(
    layout: StorageLayout,
    *,
    legacy_home: Path | None = None,
    log: Callable[[str], None] | None = None,
) -> MigrationResult:
    """把旧的 FletViewer 根布局迁移到 Data/Cache/Downloads/Temp。

    安全约束：
    - marker 只在关键步骤成功后写入
    - Data/Downloads 迁移失败时保留源文件
    - Cache 失败可降级为丢弃并重建
    """
    logger = log or (lambda _message: None)
    marker = layout.paths.data / MARKER_NAME
    moved: list[str] = []
    notes: list[str] = []

    layout.ensure_dirs()
    if marker.exists():
        notes.append("marker exists")
        return MigrationResult(performed=False, marker=marker, moved=moved, notes=notes)

    home = _detect_legacy_home(layout, legacy_home)
    if home is None or not home.exists() or not _is_legacy_home(home, layout):
        _write_marker(marker, moved=["none"], notes=["no legacy home detected"])
        notes.append("no legacy home detected")
        return MigrationResult(performed=False, marker=marker, moved=moved, notes=notes)

    logger(f"legacy home={home}")

    # Data files
    for name in ("config.json", "data.db"):
        src = home / name
        dst = layout.paths.data / name
        if _migrate_path(src, dst, critical=True, logger=logger):
            moved.append(f"{src.name} -> {dst}")
            _migrate_sqlite_sidecars(src, dst, logger=logger)

    # Cache database and files
    cache_db_src = home / "cache.db"
    if _migrate_path(cache_db_src, layout.cache_db, critical=False, logger=logger):
        moved.append(f"cache.db -> {layout.cache_db}")
        _migrate_sqlite_sidecars(cache_db_src, layout.cache_db, logger=logger)

    cache_files_src = home / "Cache"
    try:
        same_cache_root = cache_files_src.exists() and cache_files_src.resolve() == layout.paths.cache.resolve()
    except OSError:
        same_cache_root = False
    if cache_files_src.exists():
        nested = cache_files_src / "files"
        # Old layout stored hashed files directly under Cache/; new layout uses Cache/files/.
        already_new_layout = nested.exists() and _looks_like_hash_tree(nested) and not _looks_like_hash_tree(cache_files_src)
        if already_new_layout and nested.resolve() == layout.cache_files.resolve():
            notes.append("cache files already in Cache/files")
        elif _looks_like_hash_tree(cache_files_src) or same_cache_root:
            if _merge_tree(
                cache_files_src,
                layout.cache_files,
                critical=False,
                logger=logger,
                skip_names={"files", "cache.db", "cache.db-wal", "cache.db-shm"},
            ):
                moved.append(f"Cache/* -> {layout.cache_files}")
        else:
            source = nested if nested.exists() else cache_files_src
            if _merge_tree(source, layout.cache_files, critical=False, logger=logger, skip_names={"files"}):
                moved.append(f"{source} -> {layout.cache_files}")

    # Downloads stay under the downloads domain. Only move when legacy home root
    # previously held Downloads and the target is a different path.
    downloads_src = home / "Downloads"
    if downloads_src.exists() and downloads_src.resolve() != layout.paths.downloads.resolve():
        if _merge_tree(downloads_src, layout.paths.downloads, critical=True, logger=logger):
            moved.append(f"Downloads -> {layout.paths.downloads}")

    # Rewrite absolute download/gallery paths after files are in place.
    rewritten = _rewrite_data_db_paths(layout, legacy_home=home, logger=logger)
    if rewritten:
        notes.append(f"rewrote {rewritten} absolute paths in data.db")

    # Leave old root debug_log.md alone; new logs write to Temp.
    if (home / "debug_log.md").exists():
        notes.append("legacy root debug_log.md left in place")

    _write_marker(marker, moved=moved, notes=notes)
    logger(f"migration complete moved={len(moved)}")
    return MigrationResult(performed=True, marker=marker, moved=moved, notes=notes)


def _detect_legacy_home(layout: StorageLayout, legacy_home: Path | None) -> Path | None:
    if legacy_home is not None:
        return Path(legacy_home)

    candidates: list[Path] = []
    # Desktop old root is usually parent of Downloads or parent of new Data.
    candidates.append(layout.paths.downloads.parent)
    candidates.append(layout.paths.data.parent)
    candidates.append(Path("FletViewer"))

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_legacy_home(resolved, layout):
            return resolved
    return None


def _is_legacy_home(home: Path, layout: StorageLayout) -> bool:
    if not home.exists():
        return False
    # Already new layout if Data/config.json exists and root config is gone.
    if (home / "Data" / "config.json").exists() and not (home / "config.json").exists():
        return False
    legacy_markers = (
        home / "config.json",
        home / "data.db",
        home / "cache.db",
        home / "Cache",
        home / "Downloads",
    )
    if not any(path.exists() for path in legacy_markers):
        return False
    # If the only existing tree is already the target layout domains, skip.
    if home.resolve() == layout.paths.data.resolve():
        return False
    return True


def _migrate_path(src: Path, dst: Path, *, critical: bool, logger: Callable[[str], None]) -> bool:
    if not src.exists():
        return False
    try:
        if src.resolve() == dst.resolve():
            return False
    except OSError:
        pass

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        logger(f"skip existing target {dst}")
        return False

    try:
        src.replace(dst)
        logger(f"moved {src} -> {dst}")
        return True
    except OSError:
        try:
            if src.is_dir():
                shutil.copytree(src, dst)
                shutil.rmtree(src, ignore_errors=True)
            else:
                tmp = dst.with_name(f".{dst.name}.{int(time.time() * 1000)}.tmp")
                shutil.copy2(src, tmp)
                tmp.replace(dst)
                try:
                    src.unlink()
                except OSError:
                    # Windows may keep a brief share lock; destination is already valid.
                    logger(f"copied {src} -> {dst}, source left for later cleanup")
                    return True
            logger(f"copied {src} -> {dst}")
            return True
        except Exception as ex:
            logger(f"failed migrating {src}: {ex}")
            if critical:
                raise
            return False


def _migrate_sqlite_sidecars(src: Path, dst: Path, *, logger: Callable[[str], None]) -> None:
    for suffix in ("-wal", "-shm"):
        side_src = Path(str(src) + suffix)
        side_dst = Path(str(dst) + suffix)
        if not side_src.exists():
            continue
        if side_dst.exists():
            continue
        try:
            side_src.replace(side_dst)
            logger(f"moved {side_src.name} -> {side_dst}")
        except OSError as ex:
            logger(f"failed migrating sqlite sidecar {side_src}: {ex}")


def _looks_like_hash_tree(path: Path) -> bool:
    try:
        children = [child for child in path.iterdir() if child.is_dir() and not child.name.startswith(".")]
    except OSError:
        return False
    if not children:
        return False
    sample = children[:8]
    return all(len(child.name) == 2 for child in sample)


def _merge_tree(
    src: Path,
    dst: Path,
    *,
    critical: bool,
    logger: Callable[[str], None],
    skip_names: set[str] | None = None,
) -> bool:
    if not src.exists():
        return False
    try:
        if src.resolve() == dst.resolve():
            return False
    except OSError:
        pass

    ignored = skip_names or set()
    dst.mkdir(parents=True, exist_ok=True)
    moved_any = False
    try:
        for child in src.iterdir():
            if child.name in ignored:
                continue
            # Avoid moving the destination into itself when src is a parent of dst.
            try:
                if dst.resolve().is_relative_to(child.resolve()):
                    continue
            except (OSError, AttributeError, ValueError):
                pass
            target = dst / child.name
            if target.exists():
                if child.is_dir() and target.is_dir():
                    if _merge_tree(child, target, critical=critical, logger=logger):
                        moved_any = True
                    continue
                logger(f"skip existing target {target}")
                continue
            if _migrate_path(child, target, critical=critical, logger=logger):
                moved_any = True
        # Remove empty source directory when possible.
        try:
            if src.exists() and not any(child for child in src.iterdir() if child.name not in ignored):
                # Keep src itself if it is the cache root that still contains files/.
                if not ignored:
                    src.rmdir()
        except OSError:
            pass
        return moved_any
    except Exception as ex:
        logger(f"failed merging {src} -> {dst}: {ex}")
        if critical:
            raise
        return moved_any


def _rewrite_data_db_paths(
    layout: StorageLayout,
    *,
    legacy_home: Path,
    logger: Callable[[str], None],
) -> int:
    db_path = layout.data_db
    if not db_path.exists():
        return 0

    rewritten = 0
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as ex:
        logger(f"open data.db failed: {ex}")
        return 0

    try:
        conn.row_factory = sqlite3.Row
        # download_tasks.payload_json
        try:
            rows = conn.execute("SELECT id, payload_json FROM download_tasks").fetchall()
        except sqlite3.Error:
            rows = []
        for row in rows:
            payload_text = row["payload_json"] or ""
            new_text, changed = _rewrite_text_paths(payload_text, layout, legacy_home)
            if changed:
                conn.execute("UPDATE download_tasks SET payload_json = ? WHERE id = ?", (new_text, row["id"]))
                rewritten += 1

        # local_galleries.dir_path
        try:
            rows = conn.execute("SELECT provider, gid, token, dir_path FROM local_galleries").fetchall()
        except sqlite3.Error:
            rows = []
        for row in rows:
            old = row["dir_path"] or ""
            new, changed = _rewrite_text_paths(old, layout, legacy_home)
            if changed:
                conn.execute(
                    "UPDATE local_galleries SET dir_path = ? WHERE provider = ? AND gid = ? AND token = ?",
                    (new, row["provider"], row["gid"], row["token"]),
                )
                rewritten += 1
        conn.commit()
    finally:
        conn.close()

    if rewritten:
        logger(f"rewrote {rewritten} data.db path records")
    return rewritten


def _rewrite_text_paths(text: str, layout: StorageLayout, legacy_home: Path) -> tuple[str, bool]:
    if not text:
        return text, False

    # Only rewrite when downloads domain actually moved. Same-path rewrites can
    # corrupt absolute Windows paths by partial prefix replacement.
    try:
        if (legacy_home / "Downloads").resolve() == layout.paths.downloads.resolve():
            return text, False
    except OSError:
        return text, False

    old_downloads = legacy_home / "Downloads"
    new_downloads = layout.paths.downloads
    candidates = [
        (str(old_downloads), str(new_downloads)),
        (old_downloads.as_posix(), new_downloads.as_posix()),
        (str(old_downloads).replace("/", "\\"), str(new_downloads).replace("/", "\\")),
    ]
    try:
        candidates.extend(
            [
                (str(old_downloads.resolve()), str(new_downloads.resolve())),
                (old_downloads.resolve().as_posix(), new_downloads.resolve().as_posix()),
            ]
        )
    except OSError:
        pass

    candidates = sorted({(old, new) for old, new in candidates if old and new and old != new}, key=lambda item: len(item[0]), reverse=True)
    updated = text
    changed = False
    for old, new in candidates:
        if old in updated:
            updated = updated.replace(old, new)
            changed = True
    return updated, changed


def _write_marker(marker: Path, *, moved: list[str], notes: list[str]) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "moved": moved,
        "notes": notes,
    }
    tmp = marker.with_suffix(marker.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(marker)
