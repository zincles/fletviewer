from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import flet as ft


@dataclass(frozen=True, slots=True)
class PersistentTabSpec:
    key: str
    label: str
    build: Callable[[], ft.Control]


class PersistentTabView(ft.Column):
    """懒创建并常驻挂载的 Tab 容器，避免 TabBarView 卸载大型控件树。"""

    def __init__(
        self,
        tabs: list[PersistentTabSpec],
        *,
        selected_key: str | None = None,
        on_change: Callable[[str], None] | None = None,
        tab_bar_kwargs: dict | None = None,
        show_tab_bar: bool = True,
    ) -> None:
        self._specs: list[PersistentTabSpec] = []
        self._spec_by_key: dict[str, PersistentTabSpec] = {}
        self._hosts: dict[str, ft.Container] = {}
        self._built: dict[str, ft.Control] = {}
        self._on_change = on_change
        self.selected_key = ""
        self.tab_bar = ft.TabBar(tabs=[], **(tab_bar_kwargs or {}))
        self.tab_bar.visible = show_tab_bar
        self.content_stack = ft.Stack([], expand=True)
        self.tabs_controller = ft.Tabs(
            content=ft.Column([self.tab_bar, self.content_stack], spacing=0, expand=True),
            length=max(1, len(tabs)),
            selected_index=0,
            on_change=self._handle_tabs_change,
            expand=True,
        )
        super().__init__([self.tabs_controller], spacing=0, expand=True)
        self.set_tabs(tabs, selected_key=selected_key)

    @property
    def keys(self) -> list[str]:
        return [spec.key for spec in self._specs]

    def set_tabs(self, tabs: list[PersistentTabSpec], *, selected_key: str | None = None) -> None:
        old_hosts = self._hosts
        old_built = self._built
        self._specs = list(tabs)
        self._spec_by_key = {spec.key: spec for spec in tabs}
        self._hosts = {}
        self._built = {}
        for spec in tabs:
            host = old_hosts.get(spec.key) or ft.Container(expand=True, visible=False, ignore_interactions=True)
            self._hosts[spec.key] = host
            if spec.key in old_built:
                self._built[spec.key] = old_built[spec.key]
        self.content_stack.controls = list(self._hosts.values())
        self.tab_bar.tabs = [ft.Tab(label=spec.label) for spec in tabs]
        self.tabs_controller.length = max(1, len(tabs))
        target = selected_key if selected_key in self._spec_by_key else (tabs[0].key if tabs else "")
        if target:
            self.select(target, notify=False)
        else:
            self.selected_key = ""

    def select(self, key: str, *, notify: bool = True) -> bool:
        if key not in self._spec_by_key:
            return False
        if key not in self._built:
            control = self._spec_by_key[key].build()
            self._built[key] = control
            self._hosts[key].content = control
        self.selected_key = key
        selected_index = self.keys.index(key)
        self.tabs_controller.selected_index = selected_index
        self.tab_bar.selected_index = selected_index
        for host_key, host in self._hosts.items():
            selected = host_key == key
            host.visible = selected
            host.ignore_interactions = not selected
        if notify and self._on_change is not None:
            self._on_change(key)
        return True

    def control_for(self, key: str) -> ft.Control | None:
        return self._built.get(key)

    def set_control(self, key: str, control: ft.Control) -> bool:
        if key not in self._hosts:
            return False
        self._built[key] = control
        self._hosts[key].content = control
        return True

    def clear_control(self, key: str) -> None:
        self._built.pop(key, None)
        host = self._hosts.get(key)
        if host is not None:
            host.content = None

    def _handle_tabs_change(self, e) -> None:
        index = int(getattr(e.control, "selected_index", 0) or 0)
        if 0 <= index < len(self._specs):
            self.select(self._specs[index].key)


__all__ = ["PersistentTabSpec", "PersistentTabView"]
