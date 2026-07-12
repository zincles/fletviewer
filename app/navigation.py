from __future__ import annotations

from dataclasses import dataclass

import flet as ft

from app.debug_log import log_debug, log_exception


@dataclass(slots=True)
class ViewEntry:
    route: str
    parent_route: str
    view: ft.View
    transient: bool = True


class AppNavigator:
    """统一维护 Flet 二级 View、路由父链和返回行为。"""

    def __init__(self, page: ft.Page):
        self.page = page
        self._root_view: ft.View | None = None
        self._entries: dict[str, ViewEntry] = {}
        self._sequence = 0
        self._rebuilding = False

    @property
    def registered_count(self) -> int:
        return len(self._entries)

    def install(self) -> None:
        self.page.on_route_change = self.handle_route_change
        self.page.on_view_pop = self.handle_view_pop

    def set_root_view(self, view: ft.View) -> None:
        view.route = "/"
        self._root_view = view
        self.rebuild(self.page.route or "/")

    def next_route(self, prefix: str) -> str:
        normalized = prefix.strip("/").replace("/", "-") or "view"
        while True:
            self._sequence += 1
            route = f"/{normalized}/{self._sequence}"
            if route not in self._entries:
                return route

    def current_route(self) -> str:
        if self.page.views:
            return self.page.views[-1].route or "/"
        return self.page.route or "/"

    def navigate(self, route: str) -> None:
        self.page.navigate(route or "/")

    def push_view(self, view: ft.View, parent_route: str | None = None) -> str:
        route = view.route
        if not route or route == "/":
            route = self.next_route("view")
        elif route in self._entries:
            route = self.next_route(route)
        parent = parent_route or self.current_route() or "/"
        if parent == route:
            parent = "/"
        view.route = route
        self._entries[route] = ViewEntry(route=route, parent_route=parent, view=view)
        log_debug("导航", f"入栈 路由={route} 父路由={parent} 已登记={len(self._entries)}")
        self.navigate(route)
        return route

    def pop_view(self) -> None:
        if len(self.page.views) <= 1:
            return
        route = self.page.views[-1].route or "/"
        entry = self._entries.get(route)
        target = entry.parent_route if entry is not None else (self.page.views[-2].route or "/")
        log_debug("导航", f"出栈 路由={route} 目标={target}")
        self.navigate(target)

    def rebuild(self, route: str | None = None) -> None:
        if self._root_view is None or self._rebuilding:
            return
        target = route or self.page.route or "/"
        try:
            self._rebuilding = True
            views = [self._root_view]
            for child_route in self._resolve_chain(target):
                views.append(self._entries[child_route].view)
            self.page.views.clear()
            self.page.views.extend(views)
            self.page.update()
        except Exception as ex:
            log_exception("导航", f"重建路由失败 路由={target}：{ex}")
        finally:
            self._rebuilding = False

    def _resolve_chain(self, target: str) -> list[str]:
        if target == "/":
            return []
        chain: list[str] = []
        seen: set[str] = set()
        cursor = target
        while cursor != "/":
            if cursor in seen:
                log_debug("导航", f"检测到路由父链循环 路由={cursor}")
                return []
            seen.add(cursor)
            entry = self._entries.get(cursor)
            if entry is None:
                log_debug("导航", f"未登记路由 路由={target}，显示根页面")
                return []
            chain.append(cursor)
            cursor = entry.parent_route or "/"
        chain.reverse()
        return chain

    def handle_route_change(self, e=None) -> None:
        route = getattr(e, "route", None) or self.page.route or "/"
        log_debug("导航", f"路由变更 路由={route} 已登记={len(self._entries)}")
        self.rebuild(route)

    async def handle_view_pop(self, e) -> None:
        if len(self.page.views) <= 1:
            return
        view = getattr(e, "view", None)
        route = getattr(view, "route", None) or self.current_route()
        entry = self._entries.get(route)
        if entry is not None:
            target = entry.parent_route
        elif view in self.page.views and self.page.views.index(view) > 0:
            target = self.page.views[self.page.views.index(view) - 1].route or "/"
        else:
            target = self.page.views[-2].route or "/"
        await self.page.push_route(target)
