"""Stable, UI-independent API exposed to application frontends."""

from core.api.backend import BackendFacade
from core.api.archive import ArchiveOptionDTO, EHArchiveService, TaskStartedDTO
from core.api.downloads import DownloadTaskDTO, DownloadTaskService
from core.api.images import ImageResultDTO, ImageTaskDTO, ImageTaskService
from core.api.library import HistoryItemDTO, HistoryService, LocalGalleryDTO, LocalGalleryPageDTO, LocalGalleryService, LocalResourceDTO
from core.api.dto import CommentDTO, MediaDetailDTO, MediaItemDTO, PageResultDTO, RelatedMediaDTO
from core.api.errors import BackendError

__all__ = [
    "BackendError",
    "BackendFacade",
    "ArchiveOptionDTO",
    "CommentDTO",
    "DownloadTaskDTO",
    "DownloadTaskService",
    "MediaDetailDTO",
    "MediaItemDTO",
    "PageResultDTO",
    "RelatedMediaDTO",
    "EHArchiveService",
    "ImageResultDTO",
    "ImageTaskDTO",
    "ImageTaskService",
    "HistoryItemDTO",
    "HistoryService",
    "LocalGalleryDTO",
    "LocalGalleryPageDTO",
    "LocalGalleryService",
    "LocalResourceDTO",
    "TaskStartedDTO",
]
