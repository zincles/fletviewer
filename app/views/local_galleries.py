import base64
import json

import flet as ft

from app.backend import backend
from app.controls.async_image import image_placeholder, image_src_for_page
from app.grid_layout import runs_count_for_width
from app.storage import should_render_gallery_cards
from app.toast import show_error_toast
from app.views.local_zip_viewer import create_view as local_zip_viewer
from core.api import LocalGalleryDTO


def _cover_control(page: ft.Page, gallery: LocalGalleryDTO) -> ft.Control:
    """创建本地画廊封面控件；Web/桌面统一使用 data URI。"""
    if gallery.cover_available:
        try:
            resource = backend.get_local_gallery_cover(gallery.id)
            return ft.Image(
                src=image_src_for_page(page, base64.b64decode(resource.data_base64), resource.mime),
                width=float("inf"),
                height=float("inf"),
                fit=ft.BoxFit.COVER,
            )
        except Exception:
            return image_placeholder(width=float("inf"), height=float("inf"))
    return image_placeholder(width=float("inf"), height=float("inf"))


def _meta_pill(text: str, icon: str | None = None) -> ft.Control:
    controls = [ft.Icon(icon, size=14)] if icon else []
    controls.append(ft.Text(text, size=12, weight=ft.FontWeight.W_500))
    return ft.Container(
        content=ft.Row(controls, spacing=5, tight=True),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border_radius=999,
        padding=ft.Padding(10, 5, 10, 5),
    )


def _info_item(label: str, value: object, *, selectable: bool = False) -> ft.Control:
    return ft.Column(
        [
            ft.Text(label, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(str(value or "-"), size=14, selectable=selectable),
        ],
        spacing=2,
    )


def _tag_controls(tags: object) -> list[ft.Control]:
    if not isinstance(tags, dict):
        return []
    controls = []
    for namespace, values in tags.items():
        for value in values if isinstance(values, list) else []:
            controls.append(_meta_pill(f"{namespace}: {value}"))
    return controls


def _format_bytes(value: int) -> str:
    """格式化字节数。"""
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def _zip_summary(gallery: LocalGalleryDTO) -> str:
    if not gallery.archive_available:
        return "ZIP 文件不存在"
    return f"{gallery.archive_filename} · {_format_bytes(gallery.archive_bytes)} · {gallery.page_count or '?'} 张图片"


def _gallery_card(page: ft.Page, gallery: LocalGalleryDTO, open_detail) -> ft.Control:
    """创建本地画廊列表卡片。"""
    title = gallery.title
    category = gallery.category or "本地"
    language = gallery.language
    pages = gallery.page_count or "?"
    cover = ft.Stack(
        [
            _cover_control(page, gallery),
            ft.Container(content=ft.Text(category, size=11, color=ft.Colors.WHITE), bgcolor=ft.Colors.with_opacity(0.72, ft.Colors.BLACK), border_radius=999, padding=ft.Padding(8, 3, 8, 3), left=8, top=8),
            ft.Container(content=ft.Icon(ft.Icons.DOWNLOAD_DONE, size=16, color=ft.Colors.WHITE), bgcolor=ft.Colors.with_opacity(0.72, ft.Colors.GREEN), border_radius=999, padding=6, right=8, top=8),
        ],
        expand=True,
    )
    card = ft.Container(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=cover,
                        height=260,
                        border_radius=16,
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    ),
                    ft.Text(title, size=14, weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{language or '未知语言'} · {pages} 页 · {_format_bytes(gallery.archive_bytes)}", size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1),
                ],
                spacing=8,
            ),
            padding=8,
        ),
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=18,
    )
    return ft.GestureDetector(content=card, mouse_cursor=ft.MouseCursor.CLICK, on_tap=lambda e: open_detail(gallery))


def create_view(page: ft.Page) -> ft.Control:
    """创建本地画廊页面，展示已下载 EH Archive 并可进入 ZIP 阅读器。"""
    show_raw_json = not should_render_gallery_cards()
    status = ft.Text("", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
    content = ft.Container(expand=True)
    grid = ft.GridView(
        expand=True,
        runs_count=runs_count_for_width(page.width, min_columns=2, max_columns=9),
        spacing=10,
        run_spacing=10,
        child_aspect_ratio=0.62,
        padding=10,
    )

    def update_grid_columns(e=None):
        new_count = runs_count_for_width(page.width, min_columns=2, max_columns=9)
        if grid.runs_count != new_count:
            grid.runs_count = new_count
            page.update()

    add_resize_handler = getattr(page, "fletviewer_add_resize_handler", None)
    if callable(add_resize_handler):
        add_resize_handler(update_grid_columns)

    def show_list(update: bool = True, *, force: bool = False):
        galleries = backend.list_local_galleries(force=force)
        status.value = f"共 {len(galleries)} 个本地画廊"
        grid.controls = [_gallery_card(page, gallery, show_detail) for gallery in galleries]
        if not galleries:
            content.content = ft.Container(
                content=ft.Text("暂无本地画廊。Archive 下载完成后会出现在这里。", color=ft.Colors.ON_SURFACE_VARIANT),
                alignment=ft.Alignment(0, 0),
                expand=True,
            )
        else:
            content.content = grid
        if update:
            page.update()

    def show_detail(gallery: LocalGalleryDTO):
        metadata_text = ft.Text(json.dumps(gallery.to_dict(), ensure_ascii=False, indent=2), size=12, selectable=True)

        def open_zip_reader(e):
            if not gallery.archive_available:
                status.value = "ZIP 文件不存在，无法阅读"
                show_error_toast(page, "ZIP 文件不存在，无法阅读")
                page.update()
                return
            content.content = local_zip_viewer(page, gallery.id, gallery.title, lambda: show_detail(gallery))
            page.update()

        summary = ft.Wrap(
            [
                _meta_pill(gallery.category or "本地"),
                _meta_pill(f"{gallery.page_count or '?'} 页", ft.Icons.IMAGE_OUTLINED),
                _meta_pill(gallery.language or "未知语言", ft.Icons.LANGUAGE),
                _meta_pill(f"评分 {gallery.rating or '-'}", ft.Icons.STAR_OUTLINE),
            ],
            spacing=8,
            run_spacing=8,
        )
        hero = ft.Container(
            content=ft.Row(
                [
                    ft.Container(content=_cover_control(page, gallery), width=280, height=390, border_radius=16, clip_behavior=ft.ClipBehavior.ANTI_ALIAS),
                    ft.Column(
                        [
                            ft.Text(gallery.title, size=28, weight=ft.FontWeight.W_600, selectable=True),
                            ft.Text(gallery.creator_name or "未知上传者", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                            summary,
                            ft.FilledButton("开始阅读", icon=ft.Icons.MENU_BOOK, disabled=not gallery.archive_available, on_click=open_zip_reader),
                        ],
                        spacing=16,
                        expand=True,
                    ),
                ],
                spacing=24,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=20,
            padding=20,
        )
        detail_controls = [
                ft.Row(
                    [
                        ft.Button("返回", icon=ft.Icons.ARROW_BACK, on_click=lambda e: show_list()),
                    ],
                    spacing=12,
                ),
                hero,
                ft.ExpansionTile(
                    title=ft.Text("本地与归档信息", weight=ft.FontWeight.W_500),
                    controls=[
                        ft.Container(
                            content=ft.Column(
                            [
                                _info_item("归档", _zip_summary(gallery), selectable=True),
                                _info_item("来源", gallery.page_url, selectable=True),
                                _info_item("GID / Token", f"{gallery.source_id} / {gallery.source_token}", selectable=True),
                                _info_item("创建时间", gallery.created_at),
                            ],
                            spacing=10,
                            ),
                            padding=ft.Padding(16, 0, 16, 16),
                        ),
                    ],
                ),
        ]
        tags = _tag_controls(gallery.tags)
        if tags:
            detail_controls.append(ft.ExpansionTile(title=ft.Text("标签", weight=ft.FontWeight.W_500), controls=[ft.Container(content=ft.Wrap(tags, spacing=8, run_spacing=8), padding=16)]))
        if show_raw_json:
            detail_controls.append(ft.ExpansionTile(title=ft.Text("gallery.json"), controls=[ft.Container(content=metadata_text, padding=16)]))
        content.content = ft.Column(
            detail_controls,
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        page.update()

    def open_file_manager(e):
        render_label = getattr(page, "fletviewer_render_label", None)
        if callable(render_label):
            render_label("文件")

    refresh_btn = ft.Button("刷新", icon=ft.Icons.REFRESH, on_click=lambda e: show_list(force=True))
    files_btn = ft.Button("文件", icon=ft.Icons.FOLDER_OPEN, on_click=open_file_manager)
    root = ft.Column(
        [
            ft.Row([files_btn, refresh_btn], alignment=ft.MainAxisAlignment.END),
            status,
            ft.Divider(),
            content,
        ],
        spacing=12,
        expand=True,
    )
    show_list(update=False)
    return root
