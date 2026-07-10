import time

import flet as ft

from app.debug_log import format_duration_ms, log_debug, log_exception
from app.download_manager import DownloadTask, download_manager
from app.image_fetcher import ImageFetchTaskState, image_fetcher


def _format_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def _image_progress(task: ImageFetchTaskState) -> float | None:
    if task.bytes_total > 0:
        return max(0.0, min(1.0, task.bytes_done / task.bytes_total))
    if task.status == "queued":
        return 0
    if task.status == "running":
        return None
    if task.status in {"completed", "cache_hit"}:
        return 1
    return None


def _image_task_card(task: ImageFetchTaskState) -> ft.Control:
    status_color = {
        "queued": ft.Colors.AMBER,
        "running": ft.Colors.BLUE,
        "completed": ft.Colors.GREEN,
        "cache_hit": ft.Colors.GREEN,
        "failed": ft.Colors.ERROR,
    }.get(task.status, ft.Colors.ON_SURFACE_VARIANT)
    progress_text = (
        f"{_format_bytes(task.bytes_done)} / {_format_bytes(task.bytes_total)}"
        if task.bytes_total
        else _format_bytes(task.bytes_done)
    )
    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(task.status, size=12, color=status_color, weight=ft.FontWeight.BOLD),
                        ft.Text(task.kind, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(progress_text, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.ProgressBar(value=_image_progress(task)),
                ft.Text(task.url, size=12, selectable=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(task.error, size=12, color=ft.Colors.ERROR, visible=bool(task.error), selectable=True),
            ],
            spacing=5,
        ),
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=10,
        padding=10,
    )


def _image_task_section(title: str, tasks: list[ImageFetchTaskState], empty: str) -> ft.Control:
    return ft.Column(
        [
            ft.Text(f"{title} ({len(tasks)})", size=16, weight=ft.FontWeight.W_600),
            *([_image_task_card(task) for task in tasks] or [ft.Text(empty, size=13, color=ft.Colors.ON_SURFACE_VARIANT)]),
        ],
        spacing=8,
    )


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


class _DownloadsView(ft.Container):
    """下载中心；挂载期间每 0.5 秒刷新图片任务快照。"""

    def __init__(self, page: ft.Page):
        super().__init__(expand=True)
        self._page = page
        self._alive = False
        self._thumbnail_status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self._thumbnail_tasks = ft.Column(spacing=16)
        self._archive_status_text = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self._archive_tasks = ft.Column(spacing=10)

        thumbnail_page = ft.Column(
            [self._thumbnail_status, self._thumbnail_tasks],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
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
                    ft.TabBar(tabs=[ft.Tab(label="缩略图"), ft.Tab(label="归档")]),
                    ft.TabBarView(controls=[thumbnail_page, archive_page], expand=True),
                ],
                spacing=0,
                expand=True,
            ),
            length=2,
            expand=True,
        )
        self.content = tabs
        self.refresh_thumbnails(update=False)
        self.refresh_archives(update=False)

    def did_mount(self) -> None:
        self._alive = True
        self._page.run_thread(self._thumbnail_refresh_worker)

    def will_unmount(self) -> None:
        self._alive = False

    def refresh_thumbnails(self, *, update: bool = True) -> None:
        snapshot = image_fetcher.snapshot()
        failed = [task for task in snapshot.recent if task.status == "failed"]
        self._thumbnail_status.value = (
            f"每 0.5 秒刷新 · 正在下载 {len(snapshot.active)} · 排队 {len(snapshot.queued)} · "
            f"最近 {len(snapshot.recent)} · 失败 {len(failed)} · 并发 {snapshot.max_workers}"
        )
        self._thumbnail_tasks.controls = [
            _image_task_section("正在下载", snapshot.active, "当前没有正在下载的图片任务"),
            _image_task_section("排队中", snapshot.queued, "当前没有排队的图片任务"),
            _image_task_section("最近完成/失败", snapshot.recent[:30], "暂无最近任务"),
        ]
        if update and self._alive:
            self._thumbnail_status.update()
            self._thumbnail_tasks.update()

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
        log_debug("下载页", f"刷新归档任务 count={len(tasks)} total={format_duration_ms((time.perf_counter() - started_at) * 1000)}")

    def _thumbnail_refresh_worker(self) -> None:
        while self._alive:
            try:
                self.refresh_thumbnails()
            except Exception as ex:
                if self._alive:
                    log_exception("下载页", f"刷新缩略图任务失败: {ex}")
            time.sleep(0.5)


def create_view(page: ft.Page) -> ft.Control:
    return _DownloadsView(page)
