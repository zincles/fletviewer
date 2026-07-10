"""Flet 画廊瀑布流布局。

正常分页禁止向已有 ``Column.controls`` 直接追加子项：实测 Flet 会重绘该列，
导致列内所有封面闪烁。每列因此始终以一个空 TailHost 结尾；新一页先按
全局累计列高完成整批分配，再把该列的新卡片作为一个 Column 填入当前
TailHost，并在批次末尾留下下一代 TailHost。这样只会 patch 原本为空的
Host，旧列、旧卡片和图片控件均保持挂载。

列数变化属于低频操作，允许通过 ``set_column_count()`` 全量重建。
"""

from dataclasses import dataclass

import flet as ft


DEFAULT_ASPECT_RATIO = 0.72
MIN_ASPECT_RATIO = 0.4
MAX_ASPECT_RATIO = 2.0
SPACING_REFERENCE_WIDTH = 200.0


@dataclass(frozen=True)
class MasonryItem:
    """Masonry 子项；aspect_ratio 为宽/高。"""

    control: ft.Control
    aspect_ratio: float = DEFAULT_ASPECT_RATIO
    key: str | None = None


def safe_aspect_ratio(value: float | int | None) -> float:
    """限制异常封面比例，避免生成极高或极宽的卡片。"""
    try:
        ratio = float(value or DEFAULT_ASPECT_RATIO)
    except (TypeError, ValueError):
        ratio = DEFAULT_ASPECT_RATIO
    if ratio <= 0:
        ratio = DEFAULT_ASPECT_RATIO
    return max(MIN_ASPECT_RATIO, min(MAX_ASPECT_RATIO, ratio))


class MasonryGallery(ft.Container):
    """使用等宽列、全局最短列算法和每列 TailHost 排列子项。"""

    def __init__(self, *, column_count: int = 2, spacing: float = 8) -> None:
        super().__init__()
        self.column_count = max(1, int(column_count))
        self.spacing = max(0.0, float(spacing))
        self.items: list[MasonryItem] = []
        self.column_heights: list[float] = []
        self._columns: list[ft.Column] = []
        self._tail_hosts: list[ft.Container] = []
        self._rebuild()

    def set_items(self, items: list[MasonryItem], *, update: bool = False) -> None:
        """替换全部子项并重新按最短列排列。"""
        self.items = list(items)
        self._rebuild()
        if update:
            self.update()

    def set_column_count(self, column_count: int, *, update: bool = False) -> bool:
        """修改列数；列数未变化时返回 False。"""
        normalized = max(1, int(column_count))
        if normalized == self.column_count:
            return False
        self.column_count = normalized
        self._rebuild()
        if update:
            self.update()
        return True

    def append_batch(self, items: list[MasonryItem], *, update: bool = False) -> list[ft.Container]:
        """按全局最短列分配一批新项，只更新每列当前的空 TailHost。"""
        # 先完成整批分配，保留 Provider 顺序，同时持续更新全局累计列高。
        batches: list[list[ft.Control]] = [[] for _ in range(self.column_count)]
        normalized_spacing = self.spacing / SPACING_REFERENCE_WIDTH

        for item in items:
            ratio = safe_aspect_ratio(item.aspect_ratio)
            target = min(range(self.column_count), key=self.column_heights.__getitem__)
            self.items.append(item)
            batches[target].append(ft.Container(content=item.control, aspect_ratio=ratio, key=item.key))
            self.column_heights[target] += (1.0 / ratio) + normalized_spacing

        touched_hosts: list[ft.Container] = []
        for index, controls in enumerate(batches):
            if not controls:
                continue
            # 不修改外层 Column；只填充此前为空的 Host，并留下下一代空 Host。
            old_tail = self._tail_hosts[index]
            next_tail = ft.Container()
            old_tail.content = ft.Column(
                [*controls, next_tail],
                spacing=self.spacing,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
            self._tail_hosts[index] = next_tail
            touched_hosts.append(old_tail)

        if update:
            for host in touched_hosts:
                host.update()
        return touched_hosts

    def _rebuild(self) -> None:
        self._columns = [
            ft.Column(spacing=self.spacing, expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
            for _ in range(self.column_count)
        ]
        self._tail_hosts = [ft.Container() for _ in range(self.column_count)]
        self.column_heights = [0.0] * self.column_count
        normalized_spacing = self.spacing / SPACING_REFERENCE_WIDTH

        for item in self.items:
            ratio = safe_aspect_ratio(item.aspect_ratio)
            target = min(range(self.column_count), key=self.column_heights.__getitem__)
            self._columns[target].controls.append(
                ft.Container(
                    content=item.control,
                    aspect_ratio=ratio,
                    key=item.key,
                )
            )
            self.column_heights[target] += (1.0 / ratio) + normalized_spacing

        # 初始构建后，各列末尾也必须保留一个空 Host，供首个追加批次使用。
        for column, tail_host in zip(self._columns, self._tail_hosts):
            column.controls.append(tail_host)

        self.content = ft.Row(
            self._columns,
            spacing=self.spacing,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )


__all__ = ["MasonryGallery", "MasonryItem", "safe_aspect_ratio"]
