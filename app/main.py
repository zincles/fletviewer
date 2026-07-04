import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft

from app.debug_log import log_debug
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
    if page.web:
        os.environ["FLETVIEWER_WEB"] = "1"

    content = ft.Container(expand=True, padding=40)
    view_cache: dict[str, ft.Control] = {}

    def render_search():
        rail.selected_index = None
        if "search" not in view_cache:
            log_debug("nav", "create view search")
            view_cache["search"] = search_view(page)
        else:
            log_debug("nav", "reuse view search")
        content.content = view_cache["search"]
        page.update()

    def render(idx):
        view_fn = PAGES[idx][2]
        cache_key = f"page:{idx}"
        if view_fn is None:
            label = PAGES[idx][0]
            if cache_key not in view_cache:
                log_debug("nav", f"create placeholder {label}")
                view_cache[cache_key] = ft.Column(
                    controls=[
                        ft.Text(label, size=32, weight=ft.FontWeight.BOLD),
                        ft.Text("（待实现）", size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    expand=True,
                )
            else:
                log_debug("nav", f"reuse placeholder {label}")
            content.content = view_cache[cache_key]
        else:
            label = PAGES[idx][0]
            if cache_key not in view_cache:
                log_debug("nav", f"create view {label}")
                view_cache[cache_key] = view_fn(page)
            else:
                log_debug("nav", f"reuse view {label}")
            content.content = view_cache[cache_key]
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


# Flet build 的入口要求顶层即调用 ft.run，不能包在 if __name__ == "__main__": 内。
# 通过 sys.argv 的 --web 判断走 web 模式还是桌面模式。
web_mode = "--web" in sys.argv or "--server" in sys.argv
if web_mode:
    import uvicorn
    import flet_web.fastapi as flet_fastapi

    os.environ["FLETVIEWER_WEB"] = "1"

    app = flet_fastapi.FastAPI()

    app.mount(
        "/",
        flet_fastapi.app(
            main,
            upload_dir=None,
            assets_dir=str(Path(__file__).resolve().parent / "assets"),
            web_renderer=ft.WebRenderer.AUTO,
            route_url_strategy=ft.RouteUrlStrategy.PATH,
            no_cdn=False,
        ),
    )
    uvicorn.run(app, host="0.0.0.0", port=8765)
else:
    ft.run(main)
