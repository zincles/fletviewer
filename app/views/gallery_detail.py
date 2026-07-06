import dataclasses
import json
from urllib.parse import urlsplit

import flet as ft

from app.browser_session import browser_session
from app.controls.async_image import async_image
from app.debug_log import Timer, log_debug, log_exception
from app.download_manager import download_manager, now_iso
from app.gallery_cache import get_eh_gallery_cache, put_eh_gallery_cache
from app.grid_layout import runs_count_for_width
from app.storage import should_render_gallery_cards
from app.ui_update import request_update
from lib.provider.ehgrabber import Comic, Comment, ThumbnailItem
from app.views.image_viewer import ImageViewerItem


THUMBNAIL_BATCH_SIZE = 12
THUMBNAIL_TILE_HEIGHT = 150
THUMBNAIL_GRID_SPACING = 8


def _to_jsonable(value):
    """把 dataclass 转成可 JSON 序列化的字典。"""
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return value


def _tag_pill(text: str) -> ft.Control:
    """创建标签胶囊控件。"""
    return ft.Container(
        content=ft.Text(text, size=12, color=ft.Colors.ON_SURFACE),
        padding=ft.Padding(8, 4, 8, 4),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_radius=999,
    )


def _meta_pill(label: str, value: str) -> ft.Control:
    """创建画廊详情中的短元信息胶囊。"""
    return ft.Container(
        content=ft.Text(f"{label}: {value}", size=12, color=ft.Colors.ON_SURFACE),
        padding=ft.Padding(8, 4, 8, 4),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=999,
    )


def _make_tag_controls(tags: dict[str, list[str]]) -> list[ft.Control]:
    """把 provider 返回的 namespace tags 渲染为一组标签控件。"""
    controls: list[ft.Control] = []
    for namespace, values in tags.items():
        if not values:
            continue
        controls.append(ft.Text(f"{namespace}:", size=13, weight=ft.FontWeight.BOLD))
        controls.extend(_tag_pill(tag) for tag in values)
    return controls


def _comment_value(comment: Comment | dict, key: str, default=None):
    """兼容缓存反序列化后的 dict 评论和 provider 返回的 Comment 对象。"""
    if isinstance(comment, dict):
        return comment.get(key, default)
    return getattr(comment, key, default)


def _make_comment_card(comment: Comment | dict) -> ft.Control:
    """创建画廊评论卡片。"""
    user_name = _comment_value(comment, "user_name") or "Unknown"
    comment_time = _comment_value(comment, "time") or ""
    score = _comment_value(comment, "score")
    content = _comment_value(comment, "content") or ""
    meta = ft.Row(
        [
            ft.Text(user_name, size=13, weight=ft.FontWeight.BOLD),
            ft.Text(comment_time, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(f"score: {score}", size=12, color=ft.Colors.ON_SURFACE_VARIANT) if score is not None else ft.Container(),
        ],
        spacing=10,
        wrap=True,
    )
    return ft.Container(
        content=ft.Column(
            [
                meta,
                ft.Text(content, size=13, selectable=True),
            ],
            spacing=6,
        ),
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        padding=10,
    )


def create_view(page: ft.Page, comic: Comic, on_back) -> ft.Control:
    """创建在线画廊详情页，展示 metadata、评论、缩略图和 Archive 下载入口。"""
    state = {"details": None, "thumbs": None}
    show_raw_json = not should_render_gallery_cards()
    title = ft.Text(
        comic.title or "加载中...",
        size=28,
        weight=ft.FontWeight.BOLD,
        max_lines=3,
        overflow=ft.TextOverflow.ELLIPSIS,
        selectable=True,
    )
    subtitle = ft.Text(
        comic.id,
        size=13,
        color=ft.Colors.ON_SURFACE_VARIANT,
        max_lines=2,
        overflow=ft.TextOverflow.ELLIPSIS,
        selectable=True,
    )
    status = ft.Text("加载中...", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
    download_status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    cover_box = ft.Container(
        content=async_image(page, comic.cover, width=float("inf"), height=360, fit=ft.BoxFit.COVER, cache_width=520),
        expand=4,
        height=360,
        border_radius=8,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
    )
    meta = ft.Column(
        controls=[
            title,
            subtitle,
            ft.Row(
                [
                    ft.Text(comic.type, size=13),
                    ft.Text(f"{comic.max_page}P", size=13),
                    ft.Text(f"★{comic.stars}", size=13),
                ],
                spacing=12,
            ),
            status,
        ],
        spacing=8,
        alignment=ft.MainAxisAlignment.START,
        horizontal_alignment=ft.CrossAxisAlignment.START,
        expand=6,
    )
    tags_wrap = ft.Row(wrap=True, spacing=8, run_spacing=8)
    extra_meta_wrap = ft.Row(wrap=True, spacing=8, run_spacing=8)
    versions_column = ft.Column(spacing=8, visible=False)
    thumb_columns = {"value": runs_count_for_width(page.width, min_columns=3, max_columns=12)}
    thumb_controls: list[ft.Control] = []
    thumbs_grid = ft.Column(spacing=THUMBNAIL_GRID_SPACING)

    def rebuild_thumb_grid():
        """用普通 Row/Column 铺缩略图，避免详情页里出现独立滚动条。"""
        columns = max(1, int(thumb_columns["value"] or 1))
        rows: list[ft.Control] = []
        for start in range(0, len(thumb_controls), columns):
            chunk = thumb_controls[start:start + columns]
            cells = [ft.Container(content=control, expand=1) for control in chunk]
            if len(cells) < columns:
                cells.extend(ft.Container(expand=1) for _ in range(columns - len(cells)))
            rows.append(ft.Row(cells, spacing=THUMBNAIL_GRID_SPACING, height=THUMBNAIL_TILE_HEIGHT))
        thumbs_grid.controls = rows

    def update_thumb_grid_columns(e=None):
        new_count = runs_count_for_width(page.width, min_columns=3, max_columns=12)
        if thumb_columns["value"] != new_count:
            thumb_columns["value"] = new_count
            rebuild_thumb_grid()
            page.update()

    add_resize_handler = getattr(page, "fletviewer_add_resize_handler", None)
    if callable(add_resize_handler):
        add_resize_handler(update_thumb_grid_columns)
    raw_json = ft.Text("{}", size=12, selectable=True)
    comments_column = ft.Column(spacing=8)
    show_more_comments_button = ft.Button("显示更多评论", visible=False)
    load_more_thumbs_button = ft.Button("加载更多缩略图", visible=False)
    thumb_state = {"items": [], "loaded": 0, "make_thumb": None}
    resolved_image_urls: dict[int, str] = {}
    image_key_state = {"key": None}
    root_view = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)
    detail_controls: list[ft.Control] = []

    def show_detail_view(update: bool = True):
        """回到画廊详情主体内容。"""
        root_view.controls = detail_controls
        if update:
            page.update()

    def show_all_comments(e=None):
        """在当前详情页内展示完整评论列表。"""
        details = state.get("details")
        comments = list(getattr(details, "comments", []) or [])
        root_view.controls = [
            ft.Row(
                [
                    ft.Button("返回画廊详情", icon=ft.Icons.ARROW_BACK, on_click=lambda ev: show_detail_view()),
                    ft.Text(f"全部评论（{len(comments)}）", size=22, weight=ft.FontWeight.BOLD),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            *( [_make_comment_card(comment) for comment in comments] or [ft.Text("暂无评论", size=14, color=ft.Colors.ON_SURFACE_VARIANT)] ),
        ]
        page.update()

    show_more_comments_button.on_click = show_all_comments

    def open_version(version):
        """打开 newer version 指向的画廊详情。"""
        open_detail = getattr(page, "fletviewer_open_gallery_detail", None)
        if not callable(open_detail) or not version.url:
            return
        version_comic = Comic(
            id=version.url,
            title=version.title or version.url,
            cover="",
            sub_title=version.posted,
        )
        open_detail(version_comic)

    def update_extra_meta(details):
        """刷新详情顶部的扩展元信息。"""
        controls: list[ft.Control] = []
        if details.visible:
            controls.append(_meta_pill("Visible", details.visible))
        if details.language_detail:
            controls.append(_meta_pill("Language", details.language_detail))
        if details.file_size:
            controls.append(_meta_pill("Size", details.file_size))
        if details.favorite_count:
            controls.append(_meta_pill("Favorited", str(details.favorite_count)))
        if details.rating_count:
            controls.append(_meta_pill("Ratings", str(details.rating_count)))
        extra_meta_wrap.controls = controls

    def update_versions(details):
        """刷新版本链区域。"""
        controls: list[ft.Control] = []
        if details.parent:
            parent_comic = Comic(id=details.parent, title="Parent Gallery", cover="")
            controls.append(
                ft.ListTile(
                    title=ft.Text("Parent Gallery"),
                    subtitle=ft.Text(details.parent, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    trailing=ft.Icon(ft.Icons.OPEN_IN_NEW),
                    on_click=lambda e, c=parent_comic: getattr(page, "fletviewer_open_gallery_detail", lambda _comic: None)(c),
                )
            )
        for version in details.newer_versions:
            controls.append(
                ft.ListTile(
                    title=ft.Text(version.title or version.url, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    subtitle=ft.Text(version.posted or version.url, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    trailing=ft.Icon(ft.Icons.OPEN_IN_NEW),
                    on_click=lambda e, v=version: open_version(v),
                )
            )
        versions_column.controls = controls
        versions_column.visible = bool(controls)

    def render_thumb_batch():
        viewer_items = thumb_state["items"]
        start = thumb_state["loaded"]
        end = min(len(viewer_items), start + THUMBNAIL_BATCH_SIZE)
        make_thumb_fn = thumb_state.get("make_thumb")
        if not callable(make_thumb_fn):
            return
        for idx in range(start, end):
            item = viewer_items[idx]
            thumb_controls.append(make_thumb_fn(idx, item.detail["thumbnail_url"]))
        thumb_state["loaded"] = end
        load_more_thumbs_button.visible = end < len(viewer_items)
        if viewer_items:
            load_more_thumbs_button.text = f"加载更多缩略图（{end}/{len(viewer_items)}）"
        rebuild_thumb_grid()

    def load_more_thumbs(e):
        render_thumb_batch()
        page.update()

    load_more_thumbs_button.on_click = load_more_thumbs

    def show_archive_dialog(archives):
        options = [archive for archive in archives if not archive.id.startswith("h@h_")]
        if not options:
            download_status.value = "没有可用的 Archive 下载选项"
            page.update()
            return

        dialog = ft.AlertDialog(title=ft.Text("选择 Archive 下载"))

        def choose_archive(archive):
            page.pop_dialog()
            download_status.value = f"正在获取 {archive.title} 下载链接..."
            page.update()
            page.run_thread(lambda: create_archive_task(archive))

        dialog.content = ft.Column(
            controls=[
                ft.ListTile(
                    title=ft.Text(archive.title),
                    subtitle=ft.Text(archive.description or ""),
                    trailing=ft.Icon(ft.Icons.DOWNLOAD),
                    on_click=lambda e, a=archive: choose_archive(a),
                )
                for archive in options
            ],
            width=520,
            tight=True,
        )
        dialog.actions = [ft.Button("取消", on_click=lambda e: page.pop_dialog())]
        dialog.open = True
        page.show_dialog(dialog)

    def create_archive_task(archive):
        try:
            client = browser_session.get_eh_client(require_login=True)
            details = state["details"]
            thumbs = state["thumbs"]
            if details is None:
                with Timer("detail", f"download load_comic_info {comic.id}"):
                    details = client.load_comic_info(comic.id)
            if thumbs is None:
                with Timer("detail", f"download load_thumbnails {comic.id}"):
                    thumbs = client.load_thumbnails(comic.id)
            with Timer("detail", f"get archive url {comic.id} {archive.id}"):
                download_url = client.get_archive_download_url(comic.id, archive.id)
            if not download_url:
                raise RuntimeError("该 Archive 选项未返回可下载 URL")

            gid, token = client.parse_url(comic.id)
            domain = urlsplit(comic.id).netloc or "e-hentai.org"
            task = download_manager.create_task(
                download_url,
                "archive.zip",
                tags=["eh_archive"],
                headers={"Referer": comic.id},
                tag_data={
                    "provider": "ehentai",
                    "domain": domain,
                    "gallery_url": comic.id,
                    "gid": str(gid),
                    "token": token,
                    "archive_id": archive.id,
                    "archive_title": archive.title,
                    "archive_description": archive.description,
                    "download_url_acquired_at": now_iso(),
                    "download_url_valid_seconds": 86400,
                    "max_ip_count": 2,
                    "gallery_details": dataclasses.asdict(details) if dataclasses.is_dataclass(details) else {},
                    "thumbnails_result": dataclasses.asdict(thumbs) if dataclasses.is_dataclass(thumbs) else {},
                },
            )
            download_manager.start_task(task.id)
            download_status.value = f"已加入下载队列: {archive.title}"
            log_debug("detail", f"archive task created {task.id} {comic.id}")
        except Exception as ex:
            download_status.value = f"创建下载任务失败: {ex}"
            log_exception("detail", f"create archive task failed {comic.id}: {ex}")
        finally:
            request_update(page)

    def load_archives(e):
        download_status.value = "正在加载 Archive 选项..."
        page.update()

        def archive_worker():
            try:
                client = browser_session.get_eh_client(require_login=True)
                with Timer("detail", f"get archives {comic.id}"):
                    archives = client.get_archives(comic.id)
                show_archive_dialog(archives)
            except Exception as ex:
                download_status.value = f"加载 Archive 失败: {ex}"
                log_exception("detail", f"load archives failed {comic.id}: {ex}")
                request_update(page)

        page.run_thread(archive_worker)

    set_header_actions = getattr(page, "fletviewer_set_header_actions", None)
    if callable(set_header_actions):
        set_header_actions(
            [
                ft.Button("返回", icon=ft.Icons.ARROW_BACK, on_click=lambda e: on_back()),
                ft.Button("下载 Archive", icon=ft.Icons.DOWNLOAD, on_click=load_archives),
            ]
        )

    def worker():
        try:
            log_debug("detail", f"load start {comic.id}")
            client = browser_session.get_eh_client(require_login=False)
            cached = get_eh_gallery_cache(comic.id)
            if cached is not None:
                details = cached.details
                thumbs = cached.thumbnails
                log_debug("detail", f"gallery cache used {comic.id}")
            else:
                with Timer("detail", f"load_comic_info {comic.id}"):
                    details = client.load_comic_info(comic.id)
                with Timer("detail", f"load_thumbnails {comic.id}"):
                    thumbs = client.load_thumbnails(comic.id)
                put_eh_gallery_cache(comic.id, details, thumbs)
            state["details"] = details
            state["thumbs"] = thumbs

            title.value = details.title or comic.title
            subtitle.value = details.sub_title or details.url or comic.id
            if details.cover:
                cover_box.content = async_image(page, details.cover, width=float("inf"), height=360, fit=ft.BoxFit.COVER, cache_width=520)

            tags_wrap.controls = _make_tag_controls(details.tags)
            update_extra_meta(details)
            update_versions(details)
            comments = list(details.comments or [])
            comments_column.controls = [
                _make_comment_card(comment)
                for comment in comments[:2]
            ] or [ft.Text("暂无评论", size=14, color=ft.Colors.ON_SURFACE_VARIANT)]
            show_more_comments_button.visible = len(comments) > 2
            show_more_comments_button.text = f"显示更多评论（{len(comments)} 条）"
            thumb_items = thumbs.items or [
                ThumbnailItem(url=thumb, page_url=page_url)
                for page_url, thumb in zip(thumbs.urls, thumbs.thumbnails)
            ]
            viewer_items = [
                ImageViewerItem(
                    url=item.page_url,
                    title=f"{details.title or comic.title} #{idx + 1}",
                    detail={
                        "gallery_url": comic.id,
                        "page_url": item.page_url,
                        "thumbnail_url": item.url,
                        "thumbnail_width": item.width,
                        "thumbnail_height": item.height,
                        "thumbnail_aspect_ratio": item.aspect_ratio,
                    },
                )
                for idx, item in enumerate(thumb_items)
            ]

            def resolve_full_image(item: ImageViewerItem, idx: int) -> str:
                if idx in resolved_image_urls:
                    log_debug("detail", f"resolve full image cache hit {comic.id} index={idx}")
                    return resolved_image_urls[idx]
                client = browser_session.get_eh_client(require_login=False)
                with Timer("detail", f"resolve full image {comic.id} index={idx}"):
                    resolve_thumbs = state["thumbs"] or thumbs
                    key = image_key_state.get("key")
                    if key is None:
                        key = client.get_key(resolve_thumbs.urls[0])
                        image_key_state["key"] = key
                    gid, _token = client.parse_url(comic.id)
                    if key.mpvkey:
                        result = client._get_image_mpv(gid, key, idx)
                    else:
                        result = client._get_image_showkey(gid, key, idx, resolve_thumbs, comic.id)
                    resolved_image_urls[idx] = result.url
                return result.url

            def make_thumb(idx: int, thumb: str) -> ft.Control:
                item = viewer_items[idx]
                box = ft.Container(
                    content=async_image(page, thumb, width=float("inf"), height=150, fit=ft.BoxFit.COVER, cache_width=220),
                    border_radius=6,
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                )
                open_viewer = getattr(page, "fletviewer_open_image_viewer", None)
                if callable(open_viewer):
                    return ft.GestureDetector(
                        content=box,
                        mouse_cursor=ft.MouseCursor.CLICK,
                        on_tap=lambda e, i=idx: open_viewer(viewer_items, i, resolve_full_image),
                    )
                return box

            thumb_controls.clear()
            thumbs_grid.controls = []
            thumb_state["items"] = viewer_items
            thumb_state["loaded"] = 0
            thumb_state["make_thumb"] = make_thumb
            render_thumb_batch()
            raw_json.value = json.dumps(
                {
                    "details": _to_jsonable(details),
                    "thumbnails": _to_jsonable(thumbs),
                },
                ensure_ascii=False,
                indent=2,
            )
            status.value = f"{details.max_page} 页，{len(thumbs.thumbnails)} 个缩略图"
            log_debug("detail", f"load done {comic.id} thumbs={len(thumbs.thumbnails)}")
        except Exception as ex:
            status.value = f"错误: {ex}"
            log_exception("detail", f"load failed {comic.id}: {ex}")
        finally:
            request_update(page)

    page.run_thread(worker)

    detail_controls = [
            download_status,
            ft.Divider(),
            ft.Row([cover_box, meta], spacing=24, vertical_alignment=ft.CrossAxisAlignment.START),
            extra_meta_wrap,
            versions_column,
            ft.Text("标签", size=18, weight=ft.FontWeight.BOLD),
            tags_wrap,
            ft.Text("评论", size=18, weight=ft.FontWeight.BOLD),
            comments_column,
            show_more_comments_button,
            ft.Text("缩略图", size=18, weight=ft.FontWeight.BOLD),
            thumbs_grid,
            load_more_thumbs_button,
    ]

    if show_raw_json:
        detail_controls.extend(
            [
                ft.Text("原始详情 JSON", size=18, weight=ft.FontWeight.BOLD),
                ft.Container(
                    content=ft.Column([raw_json], scroll=ft.ScrollMode.AUTO),
                    height=420,
                    border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=8,
                    padding=16,
                ),
            ]
        )

    show_detail_view(update=False)
    return root_view
