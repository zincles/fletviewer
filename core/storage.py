from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppStoragePaths:
    """平台解析后的四个存储域根目录。"""

    data: Path
    cache: Path
    downloads: Path
    temp: Path

    def resolved(self) -> "AppStoragePaths":
        return AppStoragePaths(
            data=self.data.expanduser().resolve(),
            cache=self.cache.expanduser().resolve(),
            downloads=self.downloads.expanduser().resolve(),
            temp=self.temp.expanduser().resolve(),
        )

    def ensure_dirs(self) -> None:
        for path in (self.data, self.cache, self.downloads, self.temp):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True, slots=True)
class StorageLayout:
    """FletViewer 在四个存储域内使用的固定布局。"""

    paths: AppStoragePaths
    config_file: Path
    data_db: Path
    cache_db: Path
    cache_files: Path
    downloading_dir: Path
    eh_archive_dir: Path
    debug_log_file: Path
    import_staging_dir: Path
    export_staging_dir: Path

    @classmethod
    def from_paths(cls, paths: AppStoragePaths) -> "StorageLayout":
        return cls(
            paths=paths,
            config_file=paths.data / "config.json",
            data_db=paths.data / "data.db",
            cache_db=paths.cache / "cache.db",
            cache_files=paths.cache / "files",
            downloading_dir=paths.downloads / "Downloading",
            eh_archive_dir=paths.downloads / "EHArchieve",
            debug_log_file=paths.temp / "debug_log.md",
            import_staging_dir=paths.temp / "import",
            export_staging_dir=paths.temp / "export",
        )

    def ensure_dirs(self) -> None:
        self.paths.ensure_dirs()
        for path in (
            self.cache_files,
            self.downloading_dir,
            self.eh_archive_dir,
            self.import_staging_dir,
            self.export_staging_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
