from __future__ import annotations

from typing import Callable, Generic, Hashable, TypeVar

import flet as ft

from app.controls.clickable_masonry import ClickableMasonryImageList
from app.grid_layout import runs_count_for_width
from app.ui_update import request_update
from core.paged_feed import PageBatch, PagedFeedState


ItemT = TypeVar("ItemT")
CursorT = TypeVar("CursorT")


class PagedMasonryView(ft.Container, Generic[ItemT, CursorT]):
    """分页瀑布流的 Flet 适配器；数据状态机位于 core.paged_feed。"""

    def __init__(
        self,
        page: ft.Page,
        *,
        load_page: Callable[[CursorT | None], PageBatch[ItemT, CursorT]],
        build_image: Callable[[ItemT, int], ft.Control],
        item_key: Callable[[ItemT], Hashable],
        aspect_ratio: Callable[[ItemT], float],
        on_item_click: Callable[[ItemT, int], None] | None = None,
        padding: ft.Padding | int = ft.Padding(10, 108, 10, 86),
        spacing: float = 8,
        empty_text: str = "没有可显示的内容",
        on_items_changed: Callable[[list[ItemT]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        autoload: bool = True,
    ) -> None:
        super().__init__(expand=True, padding=padding)
        self._page = page
        self._load_page = load_page
        self._item_key = item_key
        self._on_items_changed = on_items_changed
        self._on_error = on_error
        self.state: PagedFeedState[ItemT, CursorT] = PagedFeedState()

        columns = runs_count_for_width(page.width, min_columns=2, max_columns=10)
        self.image_list = ClickableMasonryImageList[ItemT](
            build_image=build_image,
            item_key=item_key,
            aspect_ratio=aspect_ratio,
            on_item_click=on_item_click,
            column_count=columns,
            spacing=spacing,
        )
        self.status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT, visible=False)
        self.load_more_button = ft.FilledButton(
            "加载下一页", icon=ft.Icons.EXPAND_MORE, disabled=True, on_click=lambda e: self.load_more()
        )
        self.list_view = ft.ListView(
            expand=True,
            padding=ft.Padding(0, 4, 0, 0),
            controls=[
                self.image_list,
                ft.Container(
                    content=self.load_more_button,
                    alignment=ft.Alignment(0, 0),
                    padding=ft.Padding(0, 12, 0, 12),
                ),
            ],
            on_scroll=self._on_scroll,
        )
        self.empty = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED, size=42, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(empty_text, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            alignment=ft.Alignment(0, 0),
            expand=True,
            visible=False,
            ignore_interactions=True,
        )
        self.content = ft.Column([self.status, ft.Stack([self.list_view, self.empty], expand=True)], spacing=4, expand=True)

        add_resize_handler = getattr(page, "fletviewer_add_resize_handler", None)
        if callable(add_resize_handler):
            add_resize_handler(self._update_columns)
        if autoload:
            self.reload()

    @property
    def items(self) -> list[ItemT]:
        return self.state.items

    def reload(self) -> None:
        self._start_load(None, replace=True)

    def load_more(self) -> None:
        if self.state.next_cursor is not None:
            self._start_load(self.state.next_cursor, replace=False)

    def _start_load(self, cursor: CursorT | None, *, replace: bool) -> None:
        request = self.state.begin(cursor, replace=replace)
        if request is None:
            return
        if replace:
            self.image_list.set_items([])
            self.empty.visible = False
        if replace:
            self.status.value = "正在加载..."
            self.status.visible = True
            self.status.color = ft.Colors.ON_SURFACE_VARIANT
        self.load_more_button.disabled = True
        request_update(self._page)

        def worker() -> None:
            try:
                batch = self._load_page(request.cursor)
                incoming = self.state.complete(request, batch, key_of=self._item_key)
                if request.generation != self.state.generation:
                    return
                if request.replace:
                    self.image_list.set_items(incoming)
                else:
                    # Sync only the empty TailHosts touched by this batch. A page-wide
                    # update here remounts old image controls and can reset scrolling.
                    self.image_list.append_batch(incoming, update=True)
                self.empty.visible = not self.state.items
                self.status.value = ""
                self.status.visible = False
                if self._on_items_changed is not None:
                    self._on_items_changed(self.state.items)
            except Exception as ex:
                self.state.fail(request)
                self.status.value = str(ex)
                self.status.visible = True
                self.status.color = ft.Colors.ERROR
                if self._on_error is not None:
                    self._on_error(ex)
            finally:
                self.load_more_button.disabled = self.state.loading or self.state.next_cursor is None
                request_update(self._page)

        self._page.run_thread(worker)

    def _on_scroll(self, e) -> None:
        if self.state.loading or self.state.next_cursor is None:
            return
        pixels = float(getattr(e, "pixels", 0) or 0)
        max_extent = float(getattr(e, "max_scroll_extent", 0) or 0)
        if max_extent and pixels >= max_extent - 480:
            self.load_more()

    def _update_columns(self, e=None) -> None:
        columns = runs_count_for_width(self._page.width, min_columns=2, max_columns=10)
        if self.image_list.set_column_count(columns):
            request_update(self._page)


__all__ = ["PagedMasonryView"]
