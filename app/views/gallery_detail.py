import dataclasses
import json
from urllib.parse import urlsplit

import flet as ft

from app.browser_session import browser_session
from app.controls.async_image import async_image, image_placeholder
from app.debug_log import Timer, log_debug, log_exception
from app.download_manager import download_manager, now_iso
from app.gallery_cache import get_eh_gallery_cache, put_eh_gallery_cache
from app.gallery_type_colors import gallery_type_color, gallery_type_foreground
from app.grid_layout import runs_count_for_width
from app.storage import should_render_gallery_cards
from app.toast import show_error_toast, show_toast
from app.ui_update import request_update
from core.provider.ehgrabber import EH_MAX_GALLERY_PAGES, Comic, Comment, ThumbnailItem
from app.views.image_viewer import ImageViewerItem


THUMBNAIL_BATCH_SIZE = 12
THUMBNAIL_PLACEHOLDER_LIMIT = 20
THUMBNAIL_TILE_HEIGHT = 150
THUMBNAIL_GRID_SPACING = 6
DETAIL_SECTION_RADIUS = 20
DETAIL_SECTION_PADDING = 16
COVER_FLEX = 1
META_FLEX = 1
COVER_ASPECT_RATIO = 280 / 360


def _to_jsonable(value):
    """把 dataclass 转成可 JSON 序列化的字典。"""
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return value


def _thumbnail_placeholder_count(page_count: int) -> int:
    """根据列表页数准备骨架，但无论输入是否异常都不超过 20 个。"""
    try:
        count = int(page_count or 0)
    except (TypeError, ValueError):
        return 0
    return min(max(0, count), THUMBNAIL_PLACEHOLDER_LIMIT)


def _tag_pill(text: str) -> ft.Control:
    """创建标签胶囊控件。"""
    return ft.Container(
        content=ft.Text(text, size=12, color=ft.Colors.ON_SURFACE),
        padding=ft.Padding(6, 3, 6, 3),
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


def _info_item(label: str, value: str, *, selectable: bool = False) -> ft.Control:
    """创建详情信息行。"""
    return ft.Column(
        [
            ft.Text(label, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(value or "-", size=14, selectable=selectable),
        ],
        spacing=2,
    )


def _make_tag_controls(tags: dict[str, list[str]]) -> list[ft.Control]:
    """把 provider 返回的 namespace tags 渲染为分组标签控件。"""
    controls: list[ft.Control] = []
    for namespace, values in tags.items():
        if not values:
            continue
        controls.append(
            ft.Row(
                [
                    ft.Text(namespace, size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY),
                    *[_tag_pill(tag) for tag in values],
                ],
                wrap=True,
                spacing=6,
                run_spacing=6,
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )
    return controls


def _section_shell(title: str, body: ft.Control, subtitle: ft.Control | None = None, action: ft.Control | None = None) -> ft.Control:
    """创建无背景、无边框的详情区块。"""
    header_column_controls: list[ft.Control] = [ft.Text(title, size=18, weight=ft.FontWeight.BOLD)]
    if subtitle is not None:
        header_column_controls.append(subtitle)
    header = ft.Row(
        [
            ft.Column(header_column_controls, spacing=2, expand=True),
            action or ft.Container(),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return ft.Column([header, body], spacing=10)


def _constrain(control: ft.Control) -> ft.Control:
    """让区块跟随页面可用宽度，避免固定宽度把移动端撑爆。"""
    return ft.Row(
        [ft.Container(content=control, expand=True)],
        alignment=ft.MainAxisAlignment.CENTER,
    )


def _section_divider() -> ft.Control:
    """详情页使用和设置页类似的分隔线。"""
    return ft.Divider(height=1, thickness=1, color=ft.Colors.OUTLINE_VARIANT)


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


def create_view(page: ft.Page, comic: Comic, on_back, register_refresh=None) -> ft.Control:
    """创建在线画廊详情页，展示 metadata、评论、缩略图和 Archive 下载入口。"""
    state = {"details": None, "thumbs": None, "loading": False}
    show_raw_json = not should_render_gallery_cards()
    title = ft.Text(
        comic.title or "加载中...",
        size=18,
        weight=ft.FontWeight.BOLD,
        max_lines=3,
        overflow=ft.TextOverflow.ELLIPSIS,
        selectable=True,
    )
    uploader_text = ft.Text(
        comic.uploader or comic.sub_title or "未知上传者",
        size=13,
        color=ft.Colors.ON_SURFACE_VARIANT,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
        selectable=True,
    )
    gallery_type_text = ft.Text(
        comic.type or "未知类型",
        size=11,
        weight=ft.FontWeight.BOLD,
        color=gallery_type_foreground(comic.type),
    )
    gallery_type_pill = ft.Container(
        content=gallery_type_text,
        padding=ft.Padding(9, 4, 9, 4),
        bgcolor=gallery_type_color(comic.type),
        border_radius=999,
        alignment=ft.Alignment(0, 0),
    )
    status = ft.Text("加载中...", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    tags_status = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
    comments_status = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
    thumbs_status = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
    download_status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    cover_box = ft.Container(
        content=async_image(page, comic.cover, expand=True, fit=ft.BoxFit.COVER, cache_width=520),
        expand=COVER_FLEX,
        aspect_ratio=COVER_ASPECT_RATIO,
        border_radius=16,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
    )
    title_box = ft.Container(
        content=ft.Column(
            [
                title,
                uploader_text,
                ft.Row([gallery_type_pill], spacing=0),
            ],
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.START,
        ),
        padding=16,
        bgcolor=ft.Colors.TRANSPARENT,
        expand=META_FLEX,
        alignment=ft.Alignment(-1, 0),
    )
    read_first_button = ft.FilledButton("阅读", icon=ft.Icons.MENU_BOOK, disabled=True, width=float("inf"))
    archive_button = ft.OutlinedButton("下载", icon=ft.Icons.DOWNLOAD, width=float("inf"), on_click=lambda e: load_archives(e))
    action_section = ft.Column(
        [
            ft.Row(
                [
                    ft.Container(content=read_first_button, expand=1),
                    ft.Container(content=archive_button, expand=1),
                ],
                spacing=12,
            ),
            download_status,
        ],
        spacing=10,
    )
    info_extra_column = ft.Column(spacing=12)
    versions_column = ft.Column(spacing=8, visible=False)
    versions_group = ft.Column(
        [
            ft.Text("版本关系", size=13, weight=ft.FontWeight.W_500),
            versions_column,
        ],
        spacing=8,
        visible=False,
    )
    info_expand_tile = ft.ExpansionTile(
        title=ft.Text("更多信息", size=13, weight=ft.FontWeight.W_500),
        subtitle=ft.Text("链接、上传者、分类等", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        controls=[info_extra_column, versions_group],
        maintain_state=True,
        tile_padding=ft.Padding(0, 0, 0, 0),
        controls_padding=ft.Padding(0, 8, 0, 0),
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.START,
        bgcolor=ft.Colors.TRANSPARENT,
        collapsed_bgcolor=ft.Colors.TRANSPARENT,
    )
    info_section = ft.Column([status, info_expand_tile], spacing=12)
    hero_layout_box = ft.Container()
    tags_wrap = ft.Column(
        spacing=8,
        horizontal_alignment=ft.CrossAxisAlignment.START,
        alignment=ft.MainAxisAlignment.START,
        tight=True,
    )
    thumb_columns = {"value": runs_count_for_width(page.width, min_columns=3, max_columns=12)}
    thumb_controls: list[ft.Control] = []
    thumbs_grid = ft.Column(spacing=THUMBNAIL_GRID_SPACING)
    comments_column = ft.Column(spacing=8)
    root_view = ft.Column(spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)
    detail_controls: list[ft.Control] = []
    hero_section = ft.Container(
        content=hero_layout_box,
        padding=DETAIL_SECTION_PADDING,
        border_radius=DETAIL_SECTION_RADIUS,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
    )
    tags_section = ft.ExpansionTile(
        title=ft.Text("标签", size=14, weight=ft.FontWeight.W_500),
        subtitle=tags_status,
        controls=[tags_wrap],
        maintain_state=True,
        tile_padding=ft.Padding(0, 0, 0, 0),
        controls_padding=ft.Padding(0, 6, 0, 0),
        expanded_alignment=ft.Alignment(-1, -1),
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.START,
        bgcolor=ft.Colors.TRANSPARENT,
        collapsed_bgcolor=ft.Colors.TRANSPARENT,
    )
    show_more_comments_button = ft.TextButton("显示更多评论", visible=False)
    comments_section = _section_shell(
        "评论",
        ft.Column([comments_column, show_more_comments_button], spacing=10),
        subtitle=comments_status,
    )
    load_more_thumbs_button = ft.OutlinedButton("加载更多缩略图", visible=False)
    thumbs_section = _section_shell(
        "缩略图",
        ft.Column([thumbs_grid, load_more_thumbs_button], spacing=12),
        subtitle=thumbs_status,
    )
    raw_json = ft.Text("{}", size=12, selectable=True)
    raw_json_section = ft.ExpansionTile(
        title=ft.Text("原始详情 JSON", size=14, weight=ft.FontWeight.W_500),
        subtitle=ft.Text("展开查看完整 provider 响应", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        controls=[
            ft.Container(
                content=ft.Column([raw_json], scroll=ft.ScrollMode.AUTO),
                height=420,
                padding=ft.Padding(0, 8, 0, 0),
            )
        ],
        maintain_state=True,
        tile_padding=ft.Padding(0, 0, 0, 0),
        controls_padding=ft.Padding(0, 12, 0, 0),
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.START,
        bgcolor=ft.Colors.TRANSPARENT,
        collapsed_bgcolor=ft.Colors.TRANSPARENT,
    )

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

    def show_thumbnail_placeholders() -> None:
        """在详情 fetch 完成前，用列表页数预渲染有限数量的缩略图骨架。"""
        placeholder_count = _thumbnail_placeholder_count(comic.max_page)
        try:
            listed_page_count = int(comic.max_page or 0)
        except (TypeError, ValueError):
            listed_page_count = 0
        thumb_controls[:] = [
            ft.Container(
                content=image_placeholder(height=THUMBNAIL_TILE_HEIGHT, loading=True),
                height=THUMBNAIL_TILE_HEIGHT,
                border_radius=6,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            )
            for _ in range(placeholder_count)
        ]
        if listed_page_count > EH_MAX_GALLERY_PAGES:
            thumbs_status.value = f"页数待详情确认 · 预渲染 {placeholder_count} 个占位"
        elif placeholder_count:
            thumbs_status.value = f"预计 {listed_page_count} 页 · 预渲染 {placeholder_count} 个占位"
        else:
            thumbs_status.value = "正在获取缩略图..."
        rebuild_thumb_grid()

    def rebuild_hero_layout():
        """详情首屏固定 40/60 横向布局，封面按长宽比计算高度。"""
        hero_layout_box.content = ft.Row(
            [cover_box, title_box],
            spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    def update_thumb_grid_columns(e=None):
        new_count = runs_count_for_width(page.width, min_columns=3, max_columns=12)
        rebuild_hero_layout()
        if thumb_columns["value"] != new_count:
            thumb_columns["value"] = new_count
            rebuild_thumb_grid()
        page.update()

    add_resize_handler = getattr(page, "fletviewer_add_resize_handler", None)
    if callable(add_resize_handler):
        add_resize_handler(update_thumb_grid_columns)
    thumb_state = {"items": [], "loaded": 0, "make_thumb": None}
    resolved_image_urls: dict[int, str] = {}
    image_key_state = {"key": None}

    def update_info_panel(details=None):
        """刷新标题下方的信息容器。"""
        if details is None:
            status.value = "加载中..."
            info_extra_column.controls = []
            versions_group.visible = False
            info_expand_tile.visible = False
            return
        status.value = f"{details.max_page or comic.max_page or '-'} 页，{details.favorite_count} 收藏，评分 {(details.stars or comic.stars):.1f}"
        uploader_text.value = details.uploader or comic.uploader or comic.sub_title or "未知上传者"
        info_extra_column.controls = [
            _info_item("语言", details.language_detail or "-"),
            _info_item("大小", details.file_size or "-"),
            _info_item("上传时间", details.upload_time or "-"),
            _info_item("链接", details.url or comic.id, selectable=True),
            _info_item("上传者", details.uploader or comic.uploader or "-"),
            _info_item("分类", comic.type or "-"),
            _info_item("可见性", details.visible or "-"),
            _info_item("评分数", str(details.rating_count) if details.rating_count else "0"),
        ]
        info_expand_tile.visible = True

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
            _constrain(
                _section_shell(
                    "全部评论",
                    ft.Column(
                        [_make_comment_card(comment) for comment in comments] or [ft.Text("暂无评论", size=14, color=ft.Colors.ON_SURFACE_VARIANT)],
                        spacing=10,
                    ),
                    subtitle=ft.Text(f"{len(comments)} 条评论", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    action=ft.OutlinedButton("返回画廊详情", icon=ft.Icons.ARROW_BACK, on_click=lambda ev: show_detail_view()),
                )
            ),
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

    def update_versions(details):
        """刷新版本链区域。"""
        controls: list[ft.Control] = []
        if details.parent:
            parent_comic = Comic(id=details.parent, title="父版本画廊", cover="")
            controls.append(
                ft.ListTile(
                    title=ft.Text("父版本画廊"),
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
        versions_group.visible = bool(controls)

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
            thumbs_status.value = f"已渲染 {end}/{len(viewer_items)} 张"
        else:
            thumbs_status.value = "暂无缩略图"
        rebuild_thumb_grid()

    def load_more_thumbs(e):
        render_thumb_batch()
        page.update()

    load_more_thumbs_button.on_click = load_more_thumbs

    def show_archive_dialog(archives):
        options = [archive for archive in archives if not archive.id.startswith("h@h_")]
        if not options:
            download_status.value = "没有可用的 Archive 下载选项"
            show_toast(page, "没有可用的 Archive 下载选项")
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
            show_error_toast(page, "创建下载任务失败", ex)
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
                show_error_toast(page, "加载 Archive 失败", ex)
                log_exception("detail", f"load archives failed {comic.id}: {ex}")
                request_update(page)

        page.run_thread(archive_worker)

    def worker(force_refresh: bool = False):
        if state["loading"]:
            return
        state["loading"] = True
        try:
            log_debug("detail", f"load start {comic.id}")
            client = browser_session.get_eh_client(require_login=False)
            cached = None if force_refresh else get_eh_gallery_cache(comic.id)
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
            if details.cover:
                cover_box.content = async_image(page, details.cover, expand=True, fit=ft.BoxFit.COVER, cache_width=520)

            update_info_panel(details)
            tags_wrap.controls = _make_tag_controls(details.tags) or [ft.Text("暂无标签", size=14, color=ft.Colors.ON_SURFACE_VARIANT)]
            tags_status.value = f"{sum(len(values) for values in details.tags.values())} 个标签"
            update_versions(details)
            comments = list(details.comments or [])
            comments_column.controls = [
                _make_comment_card(comment)
                for comment in comments[:2]
            ] or [ft.Text("暂无评论", size=14, color=ft.Colors.ON_SURFACE_VARIANT)]
            show_more_comments_button.visible = len(comments) > 2
            show_more_comments_button.text = f"显示更多评论（{len(comments)} 条）"
            comments_status.value = f"{len(comments)} 条评论"
            thumb_items = thumbs.items or [
                ThumbnailItem(url=thumb, page_url=page_url)
                for page_url, thumb in zip(thumbs.urls, thumbs.thumbnails)
            ]
            gid, token = client.parse_url(comic.id)
            viewer_items = [
                ImageViewerItem(
                    url=item.page_url,
                    title=f"{details.title or comic.title} #{idx + 1}",
                    detail={
                        "provider": "ehentai",
                        "gid": str(gid),
                        "token": token,
                        "page_idx": idx,
                        "kind": "original",
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
            read_first_button.disabled = not bool(viewer_items)
            open_viewer = getattr(page, "fletviewer_open_image_viewer", None)
            if callable(open_viewer) and viewer_items:
                read_first_button.on_click = lambda e: open_viewer(viewer_items, 0, resolve_full_image)
            render_thumb_batch()
            raw_json.value = json.dumps(
                {
                    "details": _to_jsonable(details),
                    "thumbnails": _to_jsonable(thumbs),
                },
                ensure_ascii=False,
                indent=2,
            )
            thumbs_status.value = f"{len(viewer_items)} 张缩略图"
            log_debug("detail", f"load done {comic.id} thumbs={len(thumbs.thumbnails)}")
        except Exception as ex:
            status.value = f"错误: {ex}"
            show_error_toast(page, "画廊详情加载失败", ex)
            log_exception("detail", f"load failed {comic.id}: {ex}")
        finally:
            state["loading"] = False
            request_update(page)

    def refresh_detail(e=None):
        """绕过详情缓存，重新加载当前画廊详情和缩略图。"""
        if state["loading"]:
            return
        status.value = "正在刷新..."
        read_first_button.disabled = True
        resolved_image_urls.clear()
        image_key_state["key"] = None
        page.update()
        page.run_thread(lambda: worker(force_refresh=True))

    if callable(register_refresh):
        register_refresh(refresh_detail)

    page.run_thread(worker)

    update_info_panel()
    rebuild_hero_layout()
    show_thumbnail_placeholders()
    detail_controls = [
            _constrain(hero_section),
            _constrain(action_section),
            _constrain(_section_divider()),
            _constrain(info_section),
            _constrain(_section_divider()),
            _constrain(tags_section),
            _constrain(_section_divider()),
            _constrain(comments_section),
            _constrain(_section_divider()),
            _constrain(thumbs_section),
    ]

    if show_raw_json:
        detail_controls.extend([_constrain(_section_divider()), _constrain(raw_json_section)])

    show_detail_view(update=False)
    return root_view
