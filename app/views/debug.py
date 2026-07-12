import time

import flet as ft

from app.image_fetcher import ImageFetchTaskState, image_fetcher, image_load_coordinator
from app.image_results import image_result_pump
from app.debug_log import log_exception
from app.ui_update import request_update


def _format_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def _format_age(value: float) -> str:
    if not value:
        return "-"
    seconds = max(0, time.time() - value)
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}m"


def _progress_text(task: ImageFetchTaskState) -> str:
    if task.bytes_total:
        return f"{_format_bytes(task.bytes_done)} / {_format_bytes(task.bytes_total)}"
    if task.bytes_done:
        return _format_bytes(task.bytes_done)
    return "-"


def _progress_value(task: ImageFetchTaskState) -> float | None:
    if task.bytes_total <= 0:
        if task.status == "queued":
            return 0
        if task.status == "running":
            age = max(0.0, time.time() - (task.started_at or task.created_at or time.time()))
            return min(0.9, 0.08 + age * 0.06)
        if task.status in {"completed", "cache_hit"}:
            return 1
        return None
    return max(0.0, min(1.0, task.bytes_done / task.bytes_total))


def _task_row(task: ImageFetchTaskState) -> ft.Control:
    status_color = {
        "queued": ft.Colors.AMBER,
        "running": ft.Colors.BLUE,
        "cancelling": ft.Colors.ORANGE,
        "cancelled": ft.Colors.ON_SURFACE_VARIANT,
        "completed": ft.Colors.GREEN,
        "cache_hit": ft.Colors.GREEN,
        "failed": ft.Colors.ERROR,
    }.get(task.status, ft.Colors.ON_SURFACE_VARIANT)
    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text(task.status, size=12, color=status_color, weight=ft.FontWeight.BOLD),
                        ft.Text(task.kind, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(_progress_text(task), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(f"age {_format_age(task.started_at or task.created_at)}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.ProgressBar(value=_progress_value(task)),
                ft.Text(task.url, size=12, selectable=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(task.error, size=12, color=ft.Colors.ERROR, visible=bool(task.error), selectable=True),
            ],
            spacing=4,
        ),
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        padding=8,
    )


def _section(title: str, tasks: list[ImageFetchTaskState], empty: str) -> ft.Control:
    return ft.Column(
        [
            ft.Text(f"{title} ({len(tasks)})", size=18, weight=ft.FontWeight.BOLD),
            *( [_task_row(task) for task in tasks] or [ft.Text(empty, size=13, color=ft.Colors.ON_SURFACE_VARIANT)] ),
        ],
        spacing=8,
    )


def _shared_section(entries: list[dict]) -> ft.Control:
    rows = [
        ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        f"任务 {entry['task_key']} · 订阅 {entry['subscribers']} · "
                        f"{'取消中' if entry['cancelling'] else '已完成待清理' if entry['done'] else '等待/运行中'}",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(entry["url"], size=12, selectable=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ],
                spacing=4,
            ),
            border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=8,
        )
        for entry in entries
    ]
    return ft.Column(
        [
            ft.Text(f"共享图像订阅 ({len(entries)})", size=18, weight=ft.FontWeight.BOLD),
            *(rows or [ft.Text("当前没有共享图像订阅", size=13, color=ft.Colors.ON_SURFACE_VARIANT)]),
        ],
        spacing=8,
    )


class _TaskDebugView(ft.Container):
    def __init__(self, page: ft.Page):
        super().__init__(expand=True)
        self._page = page
        self._alive = False
        self._refreshing = False
        self._worker_generation = 0
        self._status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self._auto_status = ft.Text("自动刷新中", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self._content = ft.Column(spacing=16)
        refresh_button = ft.Button("刷新", icon=ft.Icons.REFRESH, on_click=lambda e: self._refresh())
        self.content = ft.Column(
            [
                ft.Row([self._auto_status, refresh_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self._status,
                ft.Divider(),
                self._content,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        self._refresh(update=False)

    def did_mount(self) -> None:
        self._alive = True
        self._worker_generation += 1
        generation = self._worker_generation
        self._page.run_thread(lambda: self._auto_refresh_worker(generation))

    def will_unmount(self) -> None:
        self._alive = False
        self._worker_generation += 1

    def _refresh(self, update: bool = True):
        if self._refreshing:
            return True
        self._refreshing = True
        try:
            snapshot = image_fetcher.snapshot()
            entries = image_load_coordinator.debug_entries()
            failed = [task for task in snapshot.recent if task.status == "failed"]
            subscribers = sum(entry["subscribers"] for entry in entries)
            pending_results = image_result_pump(self._page).pending_count()
            if pending_results:
                diagnosis = f"有 {pending_results} 个已完成图片等待合并应用；远程客户端慢时导航会优先于这些结果"
            elif not snapshot.active and not snapshot.queued and not entries:
                diagnosis = "任务层空闲；若图片仍在转圈，请检查异步图像结果应用日志"
            elif entries and not snapshot.active and not snapshot.queued:
                diagnosis = "存在共享订阅但没有活动 fetcher 任务；检查已完成 Future 的回调清理"
            else:
                diagnosis = "任务正在 fetcher 中运行；可按 age、进度和 URL 定位网络或缓存卡点"
            self._status.value = (
                f"图像 fetcher：活跃={len(snapshot.active)} 排队={len(snapshot.queued)} 最近={len(snapshot.recent)} "
                f"最近失败={len(failed)} 共享任务={len(entries)} 订阅={subscribers} worker={snapshot.max_workers}\n"
                f"待显示={pending_results}\n诊断：{diagnosis}"
            )
            self._auto_status.value = f"自动刷新中 · {time.strftime('%H:%M:%S')}"
            self._content.controls = [
                _section("正在下载", snapshot.active, "当前没有正在下载的小图任务"),
                _section("排队中", snapshot.queued, "当前没有排队的小图任务"),
                _shared_section(entries),
                _section("最近完成/失败", snapshot.recent[:30], "暂无最近任务"),
            ]
            if update:
                return request_update(self._page)
            return True
        finally:
            self._refreshing = False

    def _auto_refresh_worker(self, generation: int):
        try:
            while self._alive and generation == self._worker_generation:
                if not self._refresh(update=True):
                    return
                time.sleep(0.5)
        except Exception as ex:
            log_exception("任务调试", f"自动刷新失败：{ex}")


def create_view(page: ft.Page) -> ft.Control:
    return _TaskDebugView(page)
