"""Minimal Flet web scene for testing Android/Web back behavior.

Run:

    python test_scene.py

Then open http://<host>:8765/ on Android. Tap the button to enter a second
view and use Android's back gesture to test whether the browser/Flet route stack
shows the expected predictive-back preview.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import flet as ft
import flet_web.fastapi as flet_fastapi
import uvicorn


def main(page: ft.Page):
    page.title = "Flet Back Test"
    page.theme = ft.Theme(
        color_scheme_seed=ft.Colors.DEEP_PURPLE,
        use_material3=True,
        page_transitions=ft.PageTransitionsTheme(android=ft.PageTransitionTheme.PREDICTIVE),
    )
    page.theme_mode = ft.ThemeMode.SYSTEM
    state = {"method": "go"}

    def go_detail(method: str):
        state["method"] = method
        print(f"[test-scene] open detail method={method} route_before={page.route} views={len(page.views)}", flush=True)
        if method == "go":
            page.go("/detail-go")
        elif method == "navigate":
            page.navigate("/detail-navigate")
        elif method == "push_route":
            page.run_task(push_detail_route)
        elif method == "append_view":
            page.views.append(detail_view("append_view", "/detail-append-view"))
            page.update()
        elif method == "set_route":
            page.route = "/detail-set-route"
            build_views(page.route)

    async def push_detail_route():
        await page.push_route("/detail-push-route")

    def go_deeper(e=None):
        method = state.get("method") or "go"
        print(f"[test-scene] go deeper method={method} route_before={page.route} views={len(page.views)}", flush=True)
        if method == "go":
            page.go("/detail-go/deeper")
        elif method == "navigate":
            page.navigate("/detail-navigate/deeper")
        elif method == "push_route":
            page.run_task(push_deeper_route)
        elif method == "append_view":
            page.views.append(nested_view("append_view", "/detail-append-view/deeper"))
            page.update()
        elif method == "set_route":
            page.route = "/detail-set-route/deeper"
            build_views(page.route)

    async def push_deeper_route():
        await page.push_route("/detail-push-route/deeper")

    def go_home(e=None):
        method = state.get("method") or "go"
        print(f"[test-scene] go home method={method} route_before={page.route} views={len(page.views)}", flush=True)
        if method == "go":
            page.go("/")
        elif method == "navigate":
            page.navigate("/")
        elif method == "push_route":
            page.run_task(push_home_route)
        elif method == "append_view":
            if len(page.views) > 1:
                page.views.pop()
            page.update()
        elif method == "set_route":
            page.route = "/"
            build_views(page.route)

    async def push_home_route():
        await page.push_route("/")

    def go_detail_default(e=None):
        page.go("/detail")

    def home_view() -> ft.View:
        return ft.View(
            route="/",
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.PHONE_ANDROID, size=56, color=ft.Colors.PRIMARY),
                            ft.Text("Flet Back Test", size=30, weight=ft.FontWeight.BOLD),
                            ft.Text("选择一种栈处理方式进入子界面，然后用 Android 返回手势测试预测式返回动画。", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Row(
                                [
                                    ft.Button("page.go", icon=ft.Icons.ROUTE, on_click=lambda e: go_detail("go")),
                                    ft.Button("navigate", icon=ft.Icons.NEAR_ME, on_click=lambda e: go_detail("navigate")),
                                    ft.Button("push_route", icon=ft.Icons.HISTORY, on_click=lambda e: go_detail("push_route")),
                                ],
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=12,
                                wrap=True,
                            ),
                            ft.Row(
                                [
                                    ft.Button("append View only", icon=ft.Icons.LAYERS, on_click=lambda e: go_detail("append_view")),
                                    ft.Button("set route + rebuild", icon=ft.Icons.SYNC_ALT, on_click=lambda e: go_detail("set_route")),
                                ],
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=12,
                                wrap=True,
                            ),
                        ],
                        spacing=16,
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                    padding=24,
                    alignment=ft.Alignment(0, 0),
                )
            ],
            padding=0,
        )

    def detail_view(method: str, route: str) -> ft.View:
        return ft.View(
            route=route,
            appbar=ft.AppBar(
                title=ft.Text(f"子界面 · {method}"),
                leading=ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回", on_click=go_home),
                automatically_imply_leading=False,
            ),
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.LAYERS, size=56, color=ft.Colors.PRIMARY),
                            ft.Text(f"Detail View: {method}", size=30, weight=ft.FontWeight.BOLD),
                            ft.Text(f"当前 route 是 {route}。现在从屏幕边缘执行 Android 返回手势。", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Button("进入二级子界面", icon=ft.Icons.DOUBLE_ARROW, on_click=go_deeper),
                            ft.Button("返回 root", icon=ft.Icons.ARROW_BACK, on_click=go_home),
                        ],
                        spacing=16,
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                    padding=24,
                    alignment=ft.Alignment(0, 0),
                )
            ],
            padding=0,
        )

    def nested_view(method: str, route: str) -> ft.View:
        return ft.View(
            route=route,
            appbar=ft.AppBar(
                title=ft.Text(f"二级子界面 · {method}"),
                leading=ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回上一级", on_click=lambda e: on_view_pop(None)),
                automatically_imply_leading=False,
            ),
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.STACKED_LINE_CHART, size=56, color=ft.Colors.PRIMARY),
                            ft.Text(f"Nested View: {method}", size=30, weight=ft.FontWeight.BOLD),
                            ft.Text(f"当前 route 是 {route}。测试 Android 返回是否逐层返回 detail，再返回 root。", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Button("返回上一级", icon=ft.Icons.ARROW_BACK, on_click=lambda e: on_view_pop(None)),
                            ft.Button("返回 root", icon=ft.Icons.HOME, on_click=go_home),
                        ],
                        spacing=16,
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                    padding=24,
                    alignment=ft.Alignment(0, 0),
                )
            ],
            padding=0,
        )

    def build_views(route: str):
        route = route or "/"
        page.views.clear()
        page.views.append(home_view())
        if route in {"/detail-go", "/detail-go/deeper"}:
            state["method"] = "go"
            page.views.append(detail_view("go", "/detail-go"))
            if route.endswith("/deeper"):
                page.views.append(nested_view("go", route))
        elif route in {"/detail-navigate", "/detail-navigate/deeper"}:
            state["method"] = "navigate"
            page.views.append(detail_view("navigate", "/detail-navigate"))
            if route.endswith("/deeper"):
                page.views.append(nested_view("navigate", route))
        elif route in {"/detail-push-route", "/detail-push-route/deeper"}:
            state["method"] = "push_route"
            page.views.append(detail_view("push_route", "/detail-push-route"))
            if route.endswith("/deeper"):
                page.views.append(nested_view("push_route", route))
        elif route in {"/detail-set-route", "/detail-set-route/deeper"}:
            state["method"] = "set_route"
            page.views.append(detail_view("set_route", "/detail-set-route"))
            if route.endswith("/deeper"):
                page.views.append(nested_view("set_route", route))
        elif route == "/detail":
            state["method"] = "go_legacy"
            page.views.append(detail_view("go_legacy", route))
        page.update()

    def on_route_change(e):
        print(f"[test-scene] route_change route={page.route} views_before={len(page.views)}", flush=True)
        build_views(page.route or "/")

    def on_view_pop(e):
        print(f"[test-scene] view_pop route={page.route} views_before={len(page.views)}", flush=True)
        if len(page.views) <= 1:
            return
        method = state.get("method") or "go"
        target_route = page.views[-2].route or "/"
        if method == "push_route":
            async def push_parent_route():
                await page.push_route(target_route)

            page.run_task(push_parent_route)
        elif method == "navigate":
            page.navigate(target_route)
        elif method == "append_view":
            page.views.pop()
            page.update()
        elif method == "set_route":
            page.route = target_route
            build_views(page.route)
        else:
            page.go(target_route)

    page.on_route_change = on_route_change
    page.on_view_pop = on_view_pop
    build_views(page.route or "/")


def run_server(host: str, port: int, strategy: str):
    app = flet_fastapi.FastAPI()
    app.mount(
        "/",
        flet_fastapi.app(
            main,
            upload_dir=None,
            assets_dir=str(Path(__file__).resolve().parent / "app" / "assets"),
            web_renderer=ft.WebRenderer.AUTO,
            route_url_strategy=ft.RouteUrlStrategy.HASH if strategy == "hash" else ft.RouteUrlStrategy.PATH,
            no_cdn=False,
        ),
    )
    print(f"[test-scene] serving http://{host}:{port}/ strategy={strategy}", flush=True)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a minimal Flet web scene for route/back testing.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--strategy", choices=["path", "hash"], default="path")
    args = parser.parse_args()
    run_server(args.host, args.port, args.strategy)
