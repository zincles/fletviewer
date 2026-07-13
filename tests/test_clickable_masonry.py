import unittest
from unittest.mock import patch

import flet as ft

from app.controls.clickable_masonry import ClickableMasonryImageList


class ClickableMasonryImageListTests(unittest.TestCase):
    def test_items_are_built_as_clickable_images(self) -> None:
        clicked: list[tuple[str, int]] = []
        images = ClickableMasonryImageList[str](
            build_image=lambda item, index: ft.Text(f"{index}:{item}"),
            item_key=lambda item: item,
            aspect_ratio=lambda _item: 1,
            on_item_click=lambda item, index: clicked.append((item, index)),
        )

        images.set_items(["a", "b"])
        first = images.gallery.items[0].control

        self.assertIsInstance(first, ft.GestureDetector)
        self.assertEqual(first.content.value, "0:a")
        first.on_tap(None)
        self.assertEqual(clicked, [("a", 0)])

    def test_appended_items_keep_global_indexes_and_old_controls(self) -> None:
        clicked: list[tuple[str, int]] = []
        images = ClickableMasonryImageList[str](
            build_image=lambda item, index: ft.Text(f"{index}:{item}"),
            item_key=lambda item: item,
            aspect_ratio=lambda _item: 1,
            on_item_click=lambda item, index: clicked.append((item, index)),
        )
        images.set_items(["a"])
        old_control = images.gallery.items[0].control

        images.append_batch(["b", "c"])

        self.assertIs(images.gallery.items[0].control, old_control)
        appended = images.gallery.items[2].control
        self.assertEqual(appended.content.value, "2:c")
        appended.on_tap(None)
        self.assertEqual(clicked, [("c", 2)])

    def test_click_wrapper_is_optional(self) -> None:
        images = ClickableMasonryImageList[str](
            build_image=lambda item, _index: ft.Text(item),
            item_key=lambda item: item,
            aspect_ratio=lambda _item: 1,
        )

        images.set_items(["a"])

        self.assertIsInstance(images.gallery.items[0].control, ft.Text)

    def test_append_update_only_syncs_touched_tail_hosts(self) -> None:
        images = ClickableMasonryImageList[str](
            build_image=lambda item, _index: ft.Text(item),
            item_key=lambda item: item,
            aspect_ratio=lambda _item: 1,
            column_count=2,
        )
        images.set_items(["a", "b"])
        old_controls = [item.control for item in images.gallery.items]

        with patch.object(ft.Container, "update", autospec=True) as update:
            images.append_batch(["c"], update=True)

        self.assertEqual(update.call_count, 1)
        self.assertEqual([item.control for item in images.gallery.items[:2]], old_controls)


if __name__ == "__main__":
    unittest.main()
