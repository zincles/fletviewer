from app.debug_log import log_exception
from app.download_manager import download_manager
from app.storage import DATA_DB_PATH, EH_ARCHIVE_DIR, ensure_download_dirs
from core.data.data_db import AppDataDB
from core.download.local_gallery import LocalGallery, LocalGalleryManager


local_gallery_manager = LocalGalleryManager(
    archive_dir=EH_ARCHIVE_DIR,
    data_db=AppDataDB(DATA_DB_PATH, ensure_dirs=ensure_download_dirs),
    ensure_dirs=ensure_download_dirs,
    download_manager=download_manager,
    log_exception=log_exception,
)


__all__ = ["LocalGallery", "LocalGalleryManager", "local_gallery_manager"]
