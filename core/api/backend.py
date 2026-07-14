from __future__ import annotations

from typing import Callable

from core.api.archive import ArchiveOptionDTO, EHArchiveService, TaskStartedDTO
from core.api.downloads import DownloadTaskDTO, DownloadTaskService
from core.api.images import ImageResultDTO, ImageTaskDTO, ImageTaskService
from core.api.library import HistoryItemDTO, HistoryService, LocalGalleryDTO, LocalGalleryPageDTO, LocalGalleryService, LocalResourceDTO
from core.api.dto import CommentDTO, MediaDetailDTO, MediaItemDTO, PageResultDTO, RelatedMediaDTO, json_safe
from core.api.errors import BackendError


class BackendFacade:
    """Frontend-facing application service with JSON-safe inputs and outputs."""

    def __init__(
        self,
        *,
        get_eh_client: Callable[..., object],
        get_pixiv_client: Callable[[], object],
        get_booru_client: Callable[[str], object],
        eh_archive_service: EHArchiveService | None = None,
        get_download_task_service: Callable[[], DownloadTaskService] | None = None,
        get_image_task_service: Callable[[], ImageTaskService] | None = None,
        get_local_gallery_service: Callable[[], LocalGalleryService] | None = None,
        get_history_service: Callable[[], HistoryService] | None = None,
    ):
        self._get_eh_client = get_eh_client
        self._get_pixiv_client = get_pixiv_client
        self._get_booru_client = get_booru_client
        self._eh_archive_service = eh_archive_service
        self._get_download_task_service = get_download_task_service
        self._get_image_task_service = get_image_task_service
        self._get_local_gallery_service = get_local_gallery_service
        self._get_history_service = get_history_service

    def search_eh(
        self,
        query: str = "",
        *,
        cursor: str | None = None,
        scope: str = "global",
    ) -> PageResultDTO:
        try:
            require_login = scope in {"favorites", "watched"}
            client = self._get_eh_client(require_login=require_login)
            if scope == "favorites":
                result = client.get_favorites(page_url=cursor, keyword=query)
            elif scope == "watched":
                result = client.get_watched(page_url=cursor)
                needle = query.casefold()
                if needle:
                    result.comics = [item for item in result.comics if needle in (item.title or "").casefold()]
            elif scope == "global":
                result = client.search(page_url=cursor) if cursor else client.search(keyword=query)
            else:
                raise BackendError("invalid_scope", f"未知 EH 搜索范围: {scope}", provider="ehentai")
            return PageResultDTO(
                provider="ehentai",
                items=[self._eh_item(item) for item in result.comics],
                next_cursor=result.next_url,
                prev_cursor=result.prev_url,
                query=query,
            )
        except BackendError:
            raise
        except Exception as ex:
            raise self._error("ehentai", ex) from ex

    def search_pixiv(self, query: str, *, cursor: str | None = None) -> PageResultDTO:
        try:
            result = self._get_pixiv_client().search_illusts(query, next_url=cursor)
            return PageResultDTO(
                provider="pixiv",
                items=[self._pixiv_item(item) for item in result.illusts],
                next_cursor=result.next_url,
                prev_cursor=result.prev_url,
                query=result.query,
            )
        except Exception as ex:
            raise self._error("pixiv", ex) from ex

    def get_pixiv_feed(self, feed: str, *, cursor: str | None = None) -> PageResultDTO:
        try:
            client = self._get_pixiv_client()
            if feed == "recommended":
                result = client.get_recommended(next_url=cursor)
                items = result.illusts
                next_cursor = result.next_url
            elif feed == "following":
                result = client.get_following(next_url=cursor)
                items = result.illusts
                next_cursor = result.next_url
            elif feed == "bookmarks":
                result = client.get_bookmarks(next_url=cursor)
                items = result.illusts
                next_cursor = result.next_url
            elif feed == "ranking":
                result = client.get_ranking(next_url=cursor)
                items = result.illusts
                next_cursor = result.next_url
            else:
                raise BackendError("invalid_feed", f"未知 Pixiv feed: {feed}", provider="pixiv")
            return PageResultDTO(
                provider="pixiv",
                items=[self._pixiv_item(item) for item in items],
                next_cursor=next_cursor,
                query=feed,
            )
        except BackendError:
            raise
        except Exception as ex:
            raise self._error("pixiv", ex) from ex

    def search_booru(
        self,
        provider_id: str,
        query: str = "",
        *,
        cursor: str | int | None = None,
        limit: int = 40,
    ) -> PageResultDTO:
        try:
            result = self._get_booru_client(provider_id).search_posts(query, page=cursor, limit=limit)
            return PageResultDTO(
                provider=provider_id,
                items=[self._booru_item(item) for item in result.posts],
                next_cursor=result.next_page,
                query=result.query,
                total_count=result.total_count,
                metadata=json_safe(result.metadata),
            )
        except Exception as ex:
            raise self._error(provider_id, ex) from ex

    def get_eh_detail(self, gallery_url: str) -> MediaDetailDTO:
        try:
            detail = self._get_eh_client(require_login=False).load_comic_info(gallery_url)
            return self._eh_detail(detail)
        except Exception as ex:
            raise self._error("ehentai", ex) from ex

    def get_pixiv_detail(self, illust_id: str) -> MediaDetailDTO:
        try:
            detail = self._get_pixiv_client().get_illust_detail(str(illust_id))
            return self._pixiv_detail(detail)
        except Exception as ex:
            raise self._error("pixiv", ex) from ex

    def get_booru_detail(self, provider_id: str, post_id: str | int) -> MediaDetailDTO:
        try:
            detail = self._get_booru_client(provider_id).get_post(post_id)
            return self._booru_detail(detail)
        except Exception as ex:
            raise self._error(provider_id, ex) from ex

    def get_media_detail(self, provider: str, media_id: str) -> MediaDetailDTO:
        if provider == "ehentai":
            return self.get_eh_detail(media_id)
        if provider == "pixiv":
            return self.get_pixiv_detail(media_id)
        return self.get_booru_detail(provider, media_id)

    def list_eh_archives(self, gallery_url: str) -> list[ArchiveOptionDTO]:
        try:
            return self._require_eh_archive_service().list_options(gallery_url)
        except Exception as ex:
            raise self._error("ehentai", ex) from ex

    def start_eh_archive_download(self, gallery_url: str, archive_id: str) -> TaskStartedDTO:
        try:
            return self._require_eh_archive_service().start_download(gallery_url, archive_id)
        except Exception as ex:
            raise self._error("ehentai", ex) from ex

    def list_download_tasks(self, *, provider: str = "", kind: str = "") -> list[DownloadTaskDTO]:
        return self._download_tasks().list_tasks(provider=provider, kind=kind)

    def get_download_task(self, task_id: str) -> DownloadTaskDTO:
        return self._download_tasks().get_task(task_id)

    def cancel_download_task(self, task_id: str) -> DownloadTaskDTO:
        return self._download_tasks().cancel_task(task_id)

    def retry_download_task(self, task_id: str) -> DownloadTaskDTO:
        return self._download_tasks().retry_task(task_id)

    def delete_download_task(self, task_id: str) -> None:
        self._download_tasks().delete_task(task_id)

    def start_image_task(self, url: str, *, kind: str = "unknown") -> ImageTaskDTO:
        return self._image_tasks().start(url, kind=kind)

    def get_image_task(self, task_id: str) -> ImageTaskDTO:
        return self._image_tasks().status(task_id)

    def list_image_tasks(self) -> list[ImageTaskDTO]:
        return self._image_tasks().list_tasks()

    def cancel_image_task(self, task_id: str) -> ImageTaskDTO:
        return self._image_tasks().cancel(task_id)

    def retry_image_task(self, task_id: str) -> ImageTaskDTO:
        return self._image_tasks().retry(task_id)

    def get_image_result(self, task_id: str) -> ImageResultDTO:
        return self._image_tasks().result(task_id)

    def remove_image_task(self, task_id: str) -> None:
        self._image_tasks().remove(task_id)

    def list_local_galleries(self, *, force: bool = False) -> list[LocalGalleryDTO]:
        return self._local_galleries().list_galleries(force=force)

    def get_local_gallery(self, gallery_id: str) -> LocalGalleryDTO:
        return self._local_galleries().get_gallery(gallery_id)

    def get_local_gallery_cover(self, gallery_id: str) -> LocalResourceDTO:
        return self._local_galleries().get_cover(gallery_id)

    def list_local_gallery_pages(self, gallery_id: str) -> list[LocalGalleryPageDTO]:
        return self._local_galleries().list_pages(gallery_id)

    def read_local_gallery_page(self, gallery_id: str, member_id: str, *, cancel_event=None) -> LocalResourceDTO:
        return self._local_galleries().read_page(gallery_id, member_id, cancel_event=cancel_event)

    def list_history(self, *, kind: str = "gallery", limit: int = 500) -> list[HistoryItemDTO]:
        return self._history().list_items(kind=kind, limit=limit)

    def record_history_media(
        self,
        item: MediaItemDTO,
        *,
        kind: str = "gallery",
        source_id: str = "",
        created_at: str = "",
    ) -> HistoryItemDTO:
        return self._history().record_media(item, kind=kind, source_id=source_id, created_at=created_at)

    def clear_history(self, *, kind: str = "gallery") -> None:
        self._history().clear(kind=kind)

    @staticmethod
    def _eh_item(item) -> MediaItemDTO:
        return MediaItemDTO(
            provider="ehentai",
            id=str(item.id),
            title=str(item.title or ""),
            thumbnail_url=str(item.cover or ""),
            image_url=str(item.cover or ""),
            page_url=str(item.id),
            width=int(item.cover_width or 0),
            height=int(item.cover_height or 0),
            aspect_ratio=float(item.cover_aspect_ratio or 0),
            subtitle=str(item.sub_title or ""),
            description=str(item.description or ""),
            tags={"general": [str(tag) for tag in item.tags]},
            page_count=int(item.max_page or 0),
            creator_name=str(item.uploader or ""),
            category=str(item.type or ""),
            language=str(item.language or ""),
            metadata={"stars": float(item.stars or 0)},
        )

    @staticmethod
    def _pixiv_item(item) -> MediaItemDTO:
        user = item.user
        return MediaItemDTO(
            provider="pixiv",
            id=str(item.id),
            title=str(item.title or ""),
            thumbnail_url=str(item.cover_url or ""),
            image_url=str(item.image_urls.get("large") or item.cover_url or ""),
            page_url=f"https://www.pixiv.net/artworks/{item.id}",
            width=int(item.width or 0),
            height=int(item.height or 0),
            aspect_ratio=(item.width / item.height) if item.width and item.height else 0,
            description=str(item.caption or ""),
            tags={"general": [str(tag) for tag in item.tags]},
            page_count=int(item.page_count or 0),
            creator_id=str(user.id if user else ""),
            creator_name=str(user.name if user else ""),
            category=str(item.type or ""),
            metadata={
                "restrict": int(item.restrict or 0),
                "x_restrict": int(item.x_restrict or 0),
                "total_view": int(item.total_view or 0),
                "total_bookmarks": int(item.total_bookmarks or 0),
                "is_bookmarked": bool(item.is_bookmarked),
                "create_date": str(item.create_date or ""),
            },
        )

    @staticmethod
    def _booru_item(item) -> MediaItemDTO:
        variant = item.original if item.original.url else item.sample if item.sample.url else item.preview
        return MediaItemDTO(
            provider=str(item.provider),
            id=str(item.id),
            title=f"{item.provider} #{item.id}",
            thumbnail_url=str(item.thumbnail_url or ""),
            image_url=str(item.image_url or ""),
            page_url=str(item.page_url or ""),
            width=int(variant.width or 0),
            height=int(variant.height or 0),
            aspect_ratio=(variant.width / variant.height) if variant.width and variant.height else 0,
            tags={str(key): [str(tag) for tag in values] for key, values in item.tags.items()},
            rating=str(item.rating or ""),
            score=int(item.score or 0),
            source=[str(value) for value in item.source],
            metadata=json_safe(item.metadata),
        )

    @staticmethod
    def _eh_detail(item) -> MediaDetailDTO:
        related = [
            RelatedMediaDTO(
                id=str(version.gid or version.url),
                title=str(version.title or ""),
                page_url=str(version.url or ""),
                relation="newer_version",
                subtitle=str(version.posted or ""),
                metadata={"token": str(version.token or "")},
            )
            for version in item.newer_versions
        ]
        return MediaDetailDTO(
            provider="ehentai",
            id=str(item.id),
            title=str(item.title or ""),
            subtitle=str(item.sub_title or ""),
            thumbnail_url=str(item.cover or ""),
            image_url=str(item.cover or ""),
            page_url=str(item.url or item.id),
            tags={str(key): [str(tag) for tag in values] for key, values in item.tags.items()},
            page_count=int(item.max_page or 0),
            creator_name=str(item.uploader or ""),
            language=str(item.language_detail or ""),
            rating=float(item.stars or 0),
            rating_count=int(item.rating_count or 0),
            favorite_count=int(item.favorite_count or 0),
            created_at=str(item.upload_time or ""),
            comments=[
                CommentDTO(
                    id=str(comment.id or ""),
                    author=str(comment.user_name or ""),
                    content=str(comment.content or ""),
                    created_at=str(comment.time or ""),
                    score=comment.score,
                    metadata={"vote_status": int(comment.vote_status or 0)},
                )
                for comment in item.comments
            ],
            related=related,
            metadata={
                "favorite_folder": str(item.folder or ""),
                "is_favorite": bool(item.is_favorite),
                "token": str(item.token or ""),
                "parent_url": str(item.parent or ""),
                "visible": str(item.visible or ""),
                "file_size": str(item.file_size or ""),
            },
        )

    @classmethod
    def _pixiv_detail(cls, item) -> MediaDetailDTO:
        base = cls._pixiv_item(item)
        return MediaDetailDTO(
            provider=base.provider,
            id=base.id,
            title=base.title,
            thumbnail_url=base.thumbnail_url,
            image_url=base.image_url,
            page_url=base.page_url,
            description=base.description,
            tags=base.tags,
            page_count=base.page_count,
            creator_id=base.creator_id,
            creator_name=base.creator_name,
            category=base.category,
            width=base.width,
            height=base.height,
            favorite_count=int(item.total_bookmarks or 0),
            created_at=str(item.create_date or ""),
            metadata={**base.metadata, "image_urls": json_safe(item.image_urls), "meta_pages": json_safe(item.meta_pages)},
        )

    @classmethod
    def _booru_detail(cls, item) -> MediaDetailDTO:
        base = cls._booru_item(item)
        return MediaDetailDTO(
            provider=base.provider,
            id=base.id,
            title=base.title,
            thumbnail_url=base.thumbnail_url,
            image_url=base.image_url,
            page_url=base.page_url,
            tags=base.tags,
            rating=0.0,
            width=base.width,
            height=base.height,
            metadata={
                **base.metadata,
                "rating": base.rating,
                "score": base.score,
                "source": json_safe(base.source),
                "sample": json_safe({"url": item.sample.url, "width": item.sample.width, "height": item.sample.height}),
                "preview": json_safe({"url": item.preview.url, "width": item.preview.width, "height": item.preview.height}),
            },
        )

    @staticmethod
    def _error(provider: str, ex: Exception) -> BackendError:
        message = str(ex) or ex.__class__.__name__
        lowered = message.lower()
        if "cookie" in lowered or "凭据" in message or "登录" in message or "401" in message:
            code = "authentication_required"
        elif "403" in message or "拒绝" in message:
            code = "access_denied"
        elif "timeout" in lowered or "timed out" in lowered or "超时" in message:
            code = "timeout"
        else:
            code = "provider_error"
        return BackendError(code, message, provider=provider, retryable=code in {"timeout", "provider_error"})

    def _require_eh_archive_service(self) -> EHArchiveService:
        if self._eh_archive_service is None:
            raise RuntimeError("EH Archive 服务尚未配置下载管理器")
        return self._eh_archive_service

    def _download_tasks(self) -> DownloadTaskService:
        if self._get_download_task_service is None:
            raise RuntimeError("下载任务服务尚未配置")
        return self._get_download_task_service()

    def _image_tasks(self) -> ImageTaskService:
        if self._get_image_task_service is None:
            raise RuntimeError("图像任务服务尚未配置")
        return self._get_image_task_service()

    def _local_galleries(self) -> LocalGalleryService:
        if self._get_local_gallery_service is None:
            raise RuntimeError("本地画廊服务尚未配置")
        return self._get_local_gallery_service()

    def _history(self) -> HistoryService:
        if self._get_history_service is None:
            raise RuntimeError("历史服务尚未配置")
        return self._get_history_service()
