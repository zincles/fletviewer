import unittest

import flet as ft

from app.controls.persistent_tabs import PersistentTabSpec, PersistentTabView


class PersistentTabViewTests(unittest.TestCase):
    def test_uses_an_isolated_tabs_controller(self) -> None:
        tabs = PersistentTabView([PersistentTabSpec("a", "A", lambda: ft.Text("A"))])

        self.assertIsInstance(tabs.tabs_controller, ft.Tabs)
        self.assertIs(tabs.controls[0], tabs.tabs_controller)
        self.assertIs(tabs.tabs_controller.content.controls[0], tabs.tab_bar)

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

    def test_switching_keeps_all_built_hosts_mounted(self):
        tabs = PersistentTabView([
            PersistentTabSpec("a", "A", lambda: ft.ListView([ft.Text("A")])),
            PersistentTabSpec("b", "B", lambda: ft.ListView([ft.Text("B")])),
        ], selected_key="a")
        tabs.select("b")
        hosts = tabs._hosts

        self.assertTrue(hosts["a"].visible)
        self.assertTrue(hosts["b"].visible)
        self.assertEqual(hosts["a"].opacity, 0.0)
        self.assertEqual(hosts["b"].opacity, 1.0)
        self.assertTrue(hosts["a"].ignore_interactions)
        self.assertFalse(hosts["b"].ignore_interactions)

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
