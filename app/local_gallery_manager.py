from app.debug_log import log_exception
from app.backend import runtime
from app.download_manager import download_manager
from app.lazy import LazyProxy
from app.notifications import notifier
from app.storage import ensure_download_dirs, get_storage_layout
from core.data.data_db import AppDataDB
from core.download.local_gallery import LocalGallery, LocalGalleryManager


def _create_local_gallery_manager() -> LocalGalleryManager:
    layout = get_storage_layout()
    return LocalGalleryManager(
        archive_dir=layout.eh_archive_dir,
        data_db=AppDataDB(layout.data_db, ensure_dirs=ensure_download_dirs),
        ensure_dirs=ensure_download_dirs,
        download_manager=download_manager.resolve(),
        log_exception=log_exception,
        notify=notifier.send,
    )


local_gallery_manager = LazyProxy(_create_local_gallery_manager)
runtime.configure_local_gallery_manager(local_gallery_manager)


__all__ = ["LocalGallery", "LocalGalleryManager", "local_gallery_manager"]
