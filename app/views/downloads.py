import time

import flet as ft

from app.debug_log import format_duration_ms, log_debug
from app.download_manager import DownloadTask, download_manager


def _format_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def _archive_progress(task: DownloadTask) -> float | None:
    if task.bytes_total <= 0:
        return None
    return max(0.0, min(1.0, task.bytes_done / task.bytes_total))


def _archive_status(task: DownloadTask) -> str:
    text = task.status
    if task.error:
        text += f": {task.error}"
    if task.consume_error:
        text += f"，归档失败: {task.consume_error}"
    return text


def _archive_task_card(task: DownloadTask, refresh) -> ft.Control:
    gallery = task.tag_data.get("gallery_details", {})
    title = gallery.get("title") or task.tag_data.get("archive_title") or task.filename
    progress_text = (
        f"{_format_bytes(task.bytes_done)} / {_format_bytes(task.bytes_total)}"
        if task.bytes_total
        else _format_bytes(task.bytes_done)
    )
    actions: list[ft.Control] = []
    if task.status in {"failed", "cancelled", "completed"}:
        actions.append(ft.Button("重试", icon=ft.Icons.RESTART_ALT, on_click=lambda e, task_id=task.id: (download_manager.retry_task(task_id), refresh())))
    if task.status in {"queued", "running"}:
        actions.append(ft.Button("取消", icon=ft.Icons.CANCEL, on_click=lambda e, task_id=task.id: (download_manager.cancel_task(task_id), refresh())))
    if task.status != "running":
        actions.append(ft.Button("删除", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda e, task_id=task.id: (download_manager.delete_task(task_id), refresh())))
    return ft.Container(
        content=ft.Column(
            [
                ft.Row([ft.Text(title, size=16, weight=ft.FontWeight.BOLD, expand=True, selectable=True), ft.Text(task.status, size=13)]),
                ft.Text(task.tag_data.get("gallery_url", task.url), size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ft.ProgressBar(value=_archive_progress(task)),
                ft.Row([ft.Text(progress_text, size=12), ft.Text(_archive_status(task), size=12, expand=True)]),
                ft.Row(actions, spacing=8, wrap=True),
            ],
            spacing=8,
        ),
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=10,
        padding=12,
    )


def _provider_placeholder(provider: str, description: str, icon: str) -> ft.Control:
    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(icon, size=48, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(f"{provider} 下载", size=20, weight=ft.FontWeight.BOLD),
                ft.Text(description, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
                ft.Text("Provider 接入后将在此显示用户创建的下载任务。", size=13, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
        alignment=ft.Alignment(0, 0),
        expand=True,
        padding=24,
    )


class _DownloadsView(ft.Container):
    """用户创建的 Provider 下载任务。"""

    def __init__(self, page: ft.Page):
        super().__init__(expand=True)
        self._page = page
        self._alive = False
        self._archive_status_text = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self._archive_tasks = ft.Column(spacing=10)

        archive_page = ft.Column(
            [
                ft.Row([ft.Button("刷新", icon=ft.Icons.REFRESH, on_click=lambda e: self.refresh_archives())], alignment=ft.MainAxisAlignment.END),
                self._archive_status_text,
                self._archive_tasks,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        tabs = ft.Tabs(
            content=ft.Column(
                [
                    ft.TabBar(tabs=[ft.Tab(label="EH 归档"), ft.Tab(label="Booru"), ft.Tab(label="Pixiv")]),
                    ft.TabBarView(
                        controls=[
                            archive_page,
                            _provider_placeholder("Booru", "预留用于单图、批量帖子和原图下载。", ft.Icons.IMAGE_SEARCH),
                            _provider_placeholder("Pixiv", "预留用于作品、系列和动图资源下载。", ft.Icons.BRUSH),
                        ],
                        expand=True,
                    ),
                ],
                spacing=0,
                expand=True,
            ),
            length=3,
            expand=True,
        )
        self.content = tabs
        self.refresh_archives(update=False)

    def did_mount(self) -> None:
        self._alive = True

    def will_unmount(self) -> None:
        self._alive = False

    def refresh_archives(self, *, update: bool = True) -> None:
        started_at = time.perf_counter()
        tasks = [task for task in download_manager.list_tasks() if "eh_archive" in task.tags]
        self._archive_status_text.value = f"共 {len(tasks)} 个归档任务"
        self._archive_tasks.controls = [_archive_task_card(task, self.refresh_archives) for task in tasks] or [
            ft.Text("暂无归档任务", color=ft.Colors.ON_SURFACE_VARIANT)
        ]
        if update and self._alive:
            self._archive_status_text.update()
            self._archive_tasks.update()
        log_debug("下载页", f"刷新归档任务 数量={len(tasks)} 总耗时={format_duration_ms((time.perf_counter() - started_at) * 1000)}")

def create_view(page: ft.Page) -> ft.Control:
    return _DownloadsView(page)
