import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft

from app.views.home import create_view as home_view
from app.views.subscriptions import create_view as subscriptions_view
from app.views.popular import create_view as popular_view
from app.views.leaderboard import create_view as leaderboard_view
from app.views.favorites import create_view as favorites_view
from app.views.search import create_view as search_view
from app.views.settings import create_view as settings_view

PAGES = [
    ("主页", ft.Icons.HOME, home_view),
    ("订阅", ft.Icons.SUBSCRIPTIONS, subscriptions_view),
    ("热门", ft.Icons.LOCAL_FIRE_DEPARTMENT, popular_view),
    ("排行榜", ft.Icons.LEADERBOARD, leaderboard_view),
    ("收藏", ft.Icons.BOOKMARK, favorites_view),
    ("历史", ft.Icons.HISTORY, None),
    ("下载", ft.Icons.DOWNLOAD, None),
    ("设置", ft.Icons.SETTINGS, settings_view),
]


def main(page: ft.Page):
    page.title = "FletViewer"

    content = ft.Container(expand=True, padding=40)

    def render_search():
        rail.selected_index = None
        content.content = search_view(page)
        page.update()

    def render(idx):
        view_fn = PAGES[idx][2]
        if view_fn is None:
            label = PAGES[idx][0]
            content.content = ft.Column(
                controls=[
                    ft.Text(label, size=32, weight=ft.FontWeight.BOLD),
                    ft.Text("（待实现）", size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            )
        else:
            content.content = view_fn(page)
        page.update()

    def on_nav_change(e):
        render(e.control.selected_index)

    rail = ft.NavigationRail(
        selected_index=0,
        leading=ft.IconButton(
            icon=ft.Icons.SEARCH,
            tooltip="搜索",
            on_click=lambda e: render_search(),
        ),
        destinations=[
            ft.NavigationRailDestination(
                icon=icon,
                selected_icon=icon,
                label=label,
            )
            for label, icon, _ in PAGES
        ],
        on_change=on_nav_change,
    )

    page.add(
        ft.Row(
            [
                rail,
                ft.VerticalDivider(width=1),
                content,
            ],
            expand=True,
        ),
    )

    render(0)


if __name__ == "__main__":
    ft.run(main)
