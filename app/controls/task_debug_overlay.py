import time

import flet as ft

from app.debug_log import log_exception
from app.download_manager import download_manager
from app.image_fetcher import image_fetcher
from app.ui_update import request_update


class TaskDebugOverlay(ft.Container):
    """常驻任务监视浮层，只读取现有图片和下载服务状态。"""

    def __init__(self, page: ft.Page):
        super().__init__(right=12, top=12, width=360)
        self._page = page
        self._alive = False
        self._collapsed = False
        self._summary = ft.Text("任务监视器", size=13, weight=ft.FontWeight.W_600, expand=True)
        self._image_status = ft.Text(size=12)
        self._download_status = ft.Text(size=12)
        self._active_items = ft.Column(spacing=4)
        self._details = ft.Column(
            [
                self._image_status,
                self._download_status,
                ft.Divider(height=1),
                self._active_items,
            ],
            spacing=8,
        )
        self._toggle = ft.IconButton(ft.Icons.EXPAND_LESS, tooltip="折叠", on_click=self._toggle_collapsed)
        self.content = ft.Container(
            content=ft.Column(
                [
                    ft.Row([ft.Icon(ft.Icons.MONITOR_HEART, size=18), self._summary, self._toggle], spacing=6),
                    self._details,
                ],
                spacing=8,
            ),
            padding=ft.Padding(12, 8, 8, 12),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=14,
            shadow=ft.BoxShadow(blur_radius=18, color=ft.Colors.with_opacity(0.22, ft.Colors.SHADOW)),
        )

    def did_mount(self) -> None:
        self._alive = True
        self._page.run_thread(self._poll)

    def will_unmount(self) -> None:
        self._alive = False

    def _toggle_collapsed(self, e=None) -> None:
        self._collapsed = not self._collapsed
        self._details.visible = not self._collapsed
        self._toggle.icon = ft.Icons.EXPAND_MORE if self._collapsed else ft.Icons.EXPAND_LESS
        self._toggle.tooltip = "展开" if self._collapsed else "折叠"
        request_update(self._page)

    def _poll(self) -> None:
        try:
            while self._alive:
                self._refresh()
                if not request_update(self._page):
                    break
                time.sleep(1)
        except Exception as ex:
            log_exception("任务监视器", f"刷新调试浮层失败：{ex}")

    def _refresh(self) -> None:
        image_snapshot = image_fetcher.snapshot()
        downloads = download_manager.list_tasks()
        running_downloads = [task for task in downloads if task.status == "running"]
        queued_downloads = [task for task in downloads if task.status == "queued"]
        failed_images = [task for task in image_snapshot.recent if task.status == "failed"]

        self._summary.value = (
            f"图片 {len(image_snapshot.active)}/{len(image_snapshot.queued)} · "
            f"下载 {len(running_downloads)}/{len(queued_downloads)}"
        )
        self._image_status.value = (
            f"图片：{len(image_snapshot.active)} 活跃，{len(image_snapshot.queued)} 排队，"
            f"{len(failed_images)} 最近失败"
        )
        self._download_status.value = f"下载：{len(running_downloads)} 运行，{len(queued_downloads)} 排队"

        items: list[ft.Control] = []
        for task in image_snapshot.active[:4]:
            items.append(ft.Text(f"图像 · {task.url}", size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
        for task in running_downloads[:3]:
            progress = f"{task.bytes_done * 100 / task.bytes_total:.0f}%" if task.bytes_total else "进行中"
            items.append(ft.Text(f"下载 · {progress} · {task.filename}", size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
        self._active_items.controls = items or [ft.Text("当前没有活跃任务", size=11, color=ft.Colors.ON_SURFACE_VARIANT)]
