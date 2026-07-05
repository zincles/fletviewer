import time

import flet as ft

from app.debug_log import format_duration_ms, log_debug
from app.download_manager import DownloadTask, download_manager


def _format_bytes(value: int) -> str:
    """格式化字节数。"""
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def _progress(task: DownloadTask) -> float | None:
    """计算任务进度条值；总大小未知时返回 None。"""
    if task.bytes_total <= 0:
        return None
    return max(0.0, min(1.0, task.bytes_done / task.bytes_total))


def _status_text(task: DownloadTask) -> str:
    """格式化下载任务状态和错误信息。"""
    text = task.status
    if task.error:
        text += f": {task.error}"
    if task.consume_error:
        text += f"，归档失败: {task.consume_error}"
    return text


def create_view(page: ft.Page) -> ft.Control:
    """创建下载任务列表页。"""
    status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    tasks_column = ft.Column(spacing=10)

    def refresh(*, update: bool = True):
        started_at = time.perf_counter()
        tasks = download_manager.list_tasks()
        listed_at = time.perf_counter()
        tasks_column.controls = [_task_card(task, refresh) for task in tasks]
        built_at = time.perf_counter()
        if not tasks:
            tasks_column.controls = [ft.Text("暂无下载任务", color=ft.Colors.ON_SURFACE_VARIANT)]
        status.value = f"共 {len(tasks)} 个任务"
        if update:
            page.update()
        updated_at = time.perf_counter()
        log_debug(
            "下载页",
            f"刷新任务 count={len(tasks)} list={format_duration_ms((listed_at - started_at) * 1000)} "
            f"build={format_duration_ms((built_at - listed_at) * 1000)} update={format_duration_ms((updated_at - built_at) * 1000)} "
            f"total={format_duration_ms((updated_at - started_at) * 1000)}",
        )

    def _task_card(task: DownloadTask, refresh_fn) -> ft.Control:
        gallery = task.tag_data.get("gallery_details", {})
        task_title = gallery.get("title") or task.tag_data.get("archive_title") or task.filename
        progress = _progress(task)
        progress_text = f"{_format_bytes(task.bytes_done)} / {_format_bytes(task.bytes_total)}" if task.bytes_total else _format_bytes(task.bytes_done)

        actions: list[ft.Control] = []
        if task.status in {"failed", "cancelled", "completed"}:
            actions.append(ft.Button("重试", icon=ft.Icons.RESTART_ALT, on_click=lambda e, tid=task.id: (download_manager.retry_task(tid), refresh_fn())))
        if task.status in {"queued", "running"}:
            actions.append(ft.Button("取消", icon=ft.Icons.CANCEL, on_click=lambda e, tid=task.id: (download_manager.cancel_task(tid), refresh_fn())))
        if task.status not in {"running"}:
            actions.append(ft.Button("删除", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda e, tid=task.id: (download_manager.delete_task(tid), refresh_fn())))

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        [
                            ft.Text(task_title, size=16, weight=ft.FontWeight.BOLD, expand=True, selectable=True),
                            ft.Text(task.status, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(task.tag_data.get("gallery_url", task.url), size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                    ft.ProgressBar(value=progress),
                    ft.Row(
                        [
                            ft.Text(progress_text, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(_status_text(task), size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                        ],
                    ),
                    ft.Row(actions, spacing=8),
                ],
                spacing=8,
            ),
            border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=12,
        )

    refresh_button = ft.Button("刷新", icon=ft.Icons.REFRESH, on_click=lambda e: refresh())
    root = ft.Column(
        controls=[
            ft.Row([refresh_button], alignment=ft.MainAxisAlignment.END),
            status,
            ft.Divider(),
            tasks_column,
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    refresh(update=False)
    return root
