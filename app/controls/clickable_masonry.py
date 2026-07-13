from __future__ import annotations

from typing import Callable, Generic, Hashable, TypeVar

import flet as ft

from app.controls.masonry_gallery import MasonryGallery, MasonryItem


ItemT = TypeVar("ItemT")


class ClickableMasonryImageList(ft.Container, Generic[ItemT]):
    """Map data items to clickable image controls arranged in a masonry layout."""

    def __init__(
        self,
        *,
        build_image: Callable[[ItemT, int], ft.Control],
        item_key: Callable[[ItemT], Hashable],
        aspect_ratio: Callable[[ItemT], float],
        on_item_click: Callable[[ItemT, int], None] | None = None,
        column_count: int = 2,
        spacing: float = 8,
    ) -> None:
        super().__init__()
        self._build_image = build_image
        self._item_key = item_key
        self._aspect_ratio = aspect_ratio
        self._on_item_click = on_item_click
        self.items: list[ItemT] = []
        self.gallery = MasonryGallery(column_count=column_count, spacing=spacing)
        self.content = self.gallery

    def set_items(self, items: list[ItemT], *, update: bool = False) -> None:
        self.items = list(items)
        self.gallery.set_items(
            [self._masonry_item(item, index) for index, item in enumerate(self.items)],
            update=update,
        )

    def append_batch(self, items: list[ItemT], *, update: bool = False) -> None:
        start = len(self.items)
        incoming = list(items)
        self.items.extend(incoming)
        self.gallery.append_batch(
            [self._masonry_item(item, start + index) for index, item in enumerate(incoming)],
            update=update,
        )

    def set_column_count(self, column_count: int, *, update: bool = False) -> bool:
        return self.gallery.set_column_count(column_count, update=update)

    def _masonry_item(self, item: ItemT, index: int) -> MasonryItem:
        image = self._build_image(item, index)
        if self._on_item_click is not None:
            image = ft.GestureDetector(
                content=image,
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda e, value=item, position=index: self._on_item_click(value, position),
            )
        return MasonryItem(
            control=image,
            aspect_ratio=self._aspect_ratio(item),
            key=str(self._item_key(item)),
        )


__all__ = ["ClickableMasonryImageList"]
