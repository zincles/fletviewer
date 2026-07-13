from __future__ import annotations

import time
from pathlib import Path

import flet as ft

from app.debug_log import log_exception
from app.storage import get_storage_layout
from app.ui_update import request_update
from core.storage_browser import StorageEntry, StorageRoot, format_size, list_entries, resolve_under_root


def _format_mtime(value: float) -> str:
    if not value:
        return "-"
    return time.strftime("%m-%d %H:%M", time.localtime(value))


def create_view(page: ft.Page) -> ft.Control:
    """Android 风格四域文件管理器：顶部路径，下方网格占满。"""
    layout = get_storage_layout()
    roots = [
        StorageRoot("Data", layout.paths.data, "配置、数据库与持久索引"),
        StorageRoot("Cache", layout.paths.cache, "图片缓存和可重建索引"),
        StorageRoot("Downloads", layout.paths.downloads, "下载任务与本地画廊"),
        StorageRoot("Temp", layout.paths.temp, "日志、导入导出临时文件"),
    ]
    state = {
        "mode": "roots",  # roots | browse
        "root": None,
        "current": None,
    }

    path_text = ft.Text(
        "内部存储",
        size=15,
        weight=ft.FontWeight.W_600,
        expand=True,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    status_text = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
    grid = ft.GridView(
        expand=True,
        runs_count=0,
        max_extent=118,
        child_aspect_ratio=0.86,
        spacing=10,
        run_spacing=10,
        padding=ft.Padding(12, 8, 12, 12),
    )

    def set_status(message: str, *, error: bool = False) -> None:
        status_text.value = message
        status_text.color = ft.Colors.ERROR if error else ft.Colors.ON_SURFACE_VARIANT

    def breadcrumb() -> str:
        if state["mode"] == "roots":
            return "内部存储"
        root: StorageRoot = state["root"]
        current: Path = state["current"]
        try:
            rel = current.resolve().relative_to(root.path.resolve())
            if str(rel) == ".":
                return f"内部存储 / {root.key}"
            return f"内部存储 / {root.key} / {rel.as_posix()}"
        except Exception:
            return f"内部存储 / {root.key}"

    def tile(icon, title: str, subtitle: str, on_click, *, folder: bool = False) -> ft.Control:
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(
                            icon,
                            size=34,
                            color=ft.Colors.PRIMARY if folder else ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        width=56,
                        height=56,
                        border_radius=16,
                        bgcolor=ft.Colors.PRIMARY_CONTAINER if folder else ft.Colors.SURFACE_CONTAINER_HIGH,
                        alignment=ft.Alignment(0, 0),
                    ),
                    ft.Text(
                        title,
                        size=12,
                        weight=ft.FontWeight.W_600,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Text(
                        subtitle,
                        size=10,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.START,
            ),
            padding=8,
            border_radius=14,
            bgcolor=ft.Colors.SURFACE,
            border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            ink=True,
            on_click=on_click,
        )

    def open_root(root: StorageRoot) -> None:
        state["mode"] = "browse"
        state["root"] = root
        state["current"] = root.path.resolve()
        reload()

    def open_preview(entry: StorageEntry) -> None:
        push_view = getattr(page, "fletviewer_push_view", None)
        pop_view = getattr(page, "fletviewer_pop_view", None)
        if not callable(push_view):
            set_status("当前环境不支持打开预览页", error=True)
            request_update(page)
            return

        body = ft.Column(
            [
                ft.Text(entry.name, size=18, weight=ft.FontWeight.W_600, selectable=True),
                ft.Text(
                    f"{'文件夹' if entry.is_dir else '文件'} · {_format_size_safe(entry)} · {_format_mtime(entry.mtime)}",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Text(str(entry.path), size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ft.Divider(),
                ft.Container(
                    content=ft.Column(
                        [ft.Text(_preview_file(entry.path), size=13, selectable=True)],
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    expand=True,
                    border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=12,
                    padding=12,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                ),
            ],
            expand=True,
            spacing=10,
        )
        push_view(
            ft.View(
                route=f"/files/preview/{abs(hash(str(entry.path))) % 10_000_000}",
                controls=[ft.Container(content=body, padding=12, expand=True)],
                padding=0,
                appbar=ft.AppBar(
                    title=ft.Text("文件预览"),
                    leading=ft.IconButton(
                        ft.Icons.ARROW_BACK,
                        tooltip="返回",
                        on_click=lambda e: pop_view() if callable(pop_view) else None,
                    ),
                    automatically_imply_leading=False,
                ),
            )
        )

    def open_entry(entry: StorageEntry) -> None:
        if entry.is_dir:
            state["current"] = entry.path
            reload()
            return
        open_preview(entry)

    def show_roots() -> None:
        state["mode"] = "roots"
        state["root"] = None
        state["current"] = None
        path_text.value = "内部存储"
        cards = []
        for root in roots:
            exists = root.path.exists()
            subtitle = root.description if exists else "尚未创建"
            cards.append(
                tile(
                    ft.Icons.FOLDER,
                    root.key,
                    subtitle if len(subtitle) <= 16 else ("可打开" if exists else "尚未创建"),
                    on_click=lambda e, item=root: open_root(item),
                    folder=True,
                )
            )
        grid.controls = cards
        set_status("四个存储域")
        request_update(page)

    def reload() -> None:
        if state["mode"] == "roots":
            show_roots()
            return
        root: StorageRoot = state["root"]
        current: Path = state["current"]
        try:
            current = resolve_under_root(root.path, current)
            state["current"] = current
            entries = list_entries(root.path, current)
            cards = [
                tile(
                    ft.Icons.FOLDER if entry.is_dir else _file_icon(entry.name),
                    entry.name,
                    "文件夹" if entry.is_dir else f"{_format_size_safe(entry)} · {_format_mtime(entry.mtime)}",
                    on_click=lambda e, item=entry: open_entry(item),
                    folder=entry.is_dir,
                )
                for entry in entries
            ]
            grid.controls = cards or [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.INBOX, size=42, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text("此文件夹为空", color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    alignment=ft.Alignment(0, 0),
                    expand=True,
                    height=180,
                )
            ]
            path_text.value = breadcrumb()
            set_status(f"{len(entries)} 项")
        except Exception as ex:
            grid.controls = [ft.Text(f"无法读取目录：{ex}", color=ft.Colors.ERROR)]
            set_status(str(ex), error=True)
            log_exception("文件管理器", f"读取失败：{ex}")
        request_update(page)

    def go_up(_e=None) -> None:
        if state["mode"] == "roots":
            set_status("已在根目录")
            request_update(page)
            return
        root: StorageRoot = state["root"]
        current: Path = state["current"]
        if current.resolve() == root.path.resolve():
            show_roots()
            return
        parent = current.parent
        try:
            parent.resolve().relative_to(root.path.resolve())
        except Exception:
            show_roots()
            return
        state["current"] = parent
        reload()

    def go_home(_e=None) -> None:
        show_roots()

    top_bar = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回上级", on_click=go_up),
                        ft.IconButton(ft.Icons.HOME, tooltip="根目录", on_click=go_home),
                        path_text,
                        ft.IconButton(ft.Icons.REFRESH, tooltip="刷新", on_click=lambda e: reload()),
                    ],
                    spacing=2,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                status_text,
            ],
            spacing=2,
        ),
        padding=ft.Padding(4, 4, 4, 8),
        border=ft.border.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
    )

    show_roots()
    return ft.Column(
        [
            top_bar,
            ft.Container(content=grid, expand=True),
        ],
        expand=True,
        spacing=0,
    )


def _format_size_safe(entry: StorageEntry) -> str:
    try:
        return format_size(entry.size)
    except Exception:
        return "-"


def _file_icon(name: str):
    lower = name.lower()
    if lower.endswith((".zip", ".cbz")):
        return ft.Icons.FOLDER_ZIP
    if lower.endswith((".json", ".txt", ".md", ".log", ".xml", ".html", ".htm", ".csv")):
        return ft.Icons.DESCRIPTION
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        return ft.Icons.IMAGE
    if lower.endswith((".db", ".sqlite")):
        return ft.Icons.STORAGE
    return ft.Icons.INSERT_DRIVE_FILE


def _preview_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".json", ".md", ".txt", ".log", ".csv", ".xml", ".html", ".htm"}:
        try:
            data = path.read_text(encoding="utf-8", errors="replace")
            if len(data) > 8000:
                return data[:8000] + "\n…(截断)"
            return data or "(空文件)"
        except Exception as ex:
            return f"无法预览：{ex}"
    if suffix == ".zip" or path.name.lower().endswith(".cbz"):
        try:
            import zipfile

            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()[:80]
            more = "" if len(names) < 80 else "\n…"
            return "ZIP 成员：\n" + "\n".join(names) + more
        except Exception as ex:
            return f"无法读取 ZIP：{ex}"
    try:
        size = path.stat().st_size if path.exists() else 0
    except OSError:
        size = 0
    return f"二进制或不支持预览的文件\n大小：{format_size(size)}"
