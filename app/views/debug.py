import time

import flet as ft

from app.image_fetcher import ImageFetchTaskState, image_fetcher


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


def create_view(page: ft.Page) -> ft.Control:
    status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    auto_status = ft.Text("自动刷新中", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
    content = ft.Column(spacing=16)
    state = {"alive": True, "refreshing": False}

    def refresh(update: bool = True):
        if state["refreshing"]:
            return
        state["refreshing"] = True
        snapshot = image_fetcher.snapshot()
        failed = [task for task in snapshot.recent if task.status == "failed"]
        status.value = f"小图 fetcher: active={len(snapshot.active)} queued={len(snapshot.queued)} recent={len(snapshot.recent)} failed_recent={len(failed)} max_workers={snapshot.max_workers}"
        auto_status.value = f"自动刷新中 · {time.strftime('%H:%M:%S')}"
        content.controls = [
            _section("正在下载", snapshot.active, "当前没有正在下载的小图任务"),
            _section("排队中", snapshot.queued, "当前没有排队的小图任务"),
            _section("最近完成/失败", snapshot.recent[:30], "暂无最近任务"),
        ]
        try:
            if update:
                page.update()
        finally:
            state["refreshing"] = False

    def auto_refresh_worker():
        created_generation = getattr(page, "fletviewer_content_generation", None)
        while state["alive"]:
            current_generation = getattr(page, "fletviewer_content_generation", None)
            if created_generation is not None and current_generation != created_generation:
                state["alive"] = False
                return
            refresh(update=True)
            time.sleep(0.5)

    refresh_button = ft.Button("刷新", icon=ft.Icons.REFRESH, on_click=lambda e: refresh())
    refresh(update=False)
    page.run_thread(auto_refresh_worker)
    return ft.Column(
            [
                ft.Row([auto_status, refresh_button], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                status,
                ft.Divider(),
                content,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
    )
