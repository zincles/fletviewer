import asyncio
import unittest
from unittest.mock import Mock

import flet as ft

from app.navigation import AppNavigator


class _Page:
    def __init__(self):
        self.route = "/"
        self.views = []
        self.navigated = []
        self.updated = 0
        self.on_route_change = None
        self.on_view_pop = None

    def navigate(self, route):
        self.navigated.append(route)

    async def push_route(self, route):
        self.navigated.append(route)

    def update(self):
        self.updated += 1


class AppNavigatorTests(unittest.TestCase):
    def setUp(self):
        self.page = _Page()
        self.navigator = AppNavigator(self.page)
        self.root = ft.View(route="/", controls=[ft.Text("根")])
        self.navigator.set_root_view(self.root)

    def test_push_builds_parent_chain(self):
        gallery = ft.View(route=self.navigator.next_route("gallery"))
        gallery_route = self.navigator.push_view(gallery)
        self.page.route = gallery_route
        self.navigator.rebuild(gallery_route)
        viewer = ft.View(route=self.navigator.next_route("viewer"))
        viewer_route = self.navigator.push_view(viewer)
        self.navigator.rebuild(viewer_route)

        self.assertEqual([view.route for view in self.page.views], ["/", gallery_route, viewer_route])

    def test_routes_are_unique(self):
        self.assertNotEqual(self.navigator.next_route("gallery"), self.navigator.next_route("gallery"))

    def test_pop_uses_registered_parent(self):
        gallery = ft.View(route=self.navigator.next_route("gallery"))
        route = self.navigator.push_view(gallery, parent_route="/")
        self.navigator.rebuild(route)

        self.navigator.pop_view()

        self.assertEqual(self.page.navigated[-1], "/")

    def test_browser_forward_can_restore_unmounted_view(self):
        gallery = ft.View(route=self.navigator.next_route("gallery"))
        route = self.navigator.push_view(gallery)
        self.navigator.rebuild(route)
        self.navigator.rebuild("/")
        self.navigator.rebuild(route)

        self.assertEqual([view.route for view in self.page.views], ["/", route])

    def test_system_pop_uses_parent(self):
        gallery = ft.View(route=self.navigator.next_route("gallery"))
        route = self.navigator.push_view(gallery)
        self.navigator.rebuild(route)

        asyncio.run(self.navigator.handle_view_pop(Mock(view=gallery)))

        self.assertEqual(self.page.navigated[-1], "/")


if __name__ == "__main__":
    unittest.main()
