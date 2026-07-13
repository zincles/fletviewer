import unittest

import flet as ft

from app.controls.persistent_tabs import PersistentTabSpec, PersistentTabView


class PersistentTabViewTests(unittest.TestCase):
    def test_tabs_are_lazy_and_keep_built_controls(self):
        built = []

        def build(key):
            built.append(key)
            return ft.Text(key)

        tabs = PersistentTabView([
            PersistentTabSpec("a", "A", lambda: build("a")),
            PersistentTabSpec("b", "B", lambda: build("b")),
        ], selected_key="a")
        first = tabs.control_for("a")
        self.assertEqual(built, ["a"])
        tabs.select("b")
        tabs.select("a")
        self.assertIs(tabs.control_for("a"), first)
        self.assertEqual(built, ["a", "b"])

    def test_dynamic_tabs_reuse_matching_key(self):
        tabs = PersistentTabView([PersistentTabSpec("a", "A", lambda: ft.Text("old"))])
        old = tabs.control_for("a")
        tabs.set_tabs([
            PersistentTabSpec("a", "A2", lambda: ft.Text("new")),
            PersistentTabSpec("b", "B", lambda: ft.Text("b")),
        ], selected_key="a")
        self.assertIs(tabs.control_for("a"), old)
        self.assertIsNone(tabs.control_for("b"))

    def test_clear_control_restores_lazy_build(self):
        count = {"value": 0}

        def build():
            count["value"] += 1
            return ft.Text(str(count["value"]))

        tabs = PersistentTabView([PersistentTabSpec("a", "A", build)])
        tabs.clear_control("a")
        tabs.select("a")
        self.assertEqual(count["value"], 2)


if __name__ == "__main__":
    unittest.main()
