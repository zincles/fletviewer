import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform.startswith("linux") and "--web" not in sys.argv and "--server" not in sys.argv:
    from app.storage import should_prefer_linux_wayland_window_backend

    backend = "wayland" if should_prefer_linux_wayland_window_backend() else "x11"
    os.environ.setdefault("GDK_BACKEND", backend)
    os.environ.setdefault("GTK_CSD", "0")

import flet as ft

from app.browser_session import browser_session
from app.debug_log import format_duration_ms, log_debug
from app.local_gallery_manager import local_gallery_manager
from app.storage import should_use_linux_builtin_title_bar
from app.views.downloads import create_view as downloads_view
from app.views.debug import create_view as debug_view
from app.views.input_test import create_view as input_test_view
from app.views.home import create_view as home_view
from app.views.subscriptions import create_view as subscriptions_view
from app.views.popular import create_view as popular_view
from app.views.leaderboard import create_view as leaderboard_view
from app.views.favorites import create_view as favorites_view
from app.views.local_galleries import create_view as local_galleries_view
from app.views.gallery_detail import create_view as gallery_detail_view
from app.views.image_viewer import create_view as image_viewer_view
from app.views.search import create_view as search_view
from app.views.settings import create_view as settings_view

PAGES = [
    ("主页", "最新画廊", ft.Icons.HOME, home_view),
    ("订阅", "关注的标签画廊（需登录）", ft.Icons.SUBSCRIPTIONS, subscriptions_view),
    ("热门", "近期热门画廊", ft.Icons.LOCAL_FIRE_DEPARTMENT, popular_view),
    ("排行榜", "EH 排行榜", ft.Icons.LEADERBOARD, leaderboard_view),
    ("收藏", "收藏夹画廊（需登录）", ft.Icons.BOOKMARK, favorites_view),
    ("本地画廊", "已下载 Archive", ft.Icons.FOLDER, local_galleries_view),
    ("历史", "浏览历史", ft.Icons.HISTORY, None),
    ("下载", "下载任务", ft.Icons.DOWNLOAD, downloads_view),
    ("调试", "小图任务", ft.Icons.BUG_REPORT, debug_view),
    ("输入测试", "用户输入事件", ft.Icons.TOUCH_APP, input_test_view),
    ("设置", "应用设置", ft.Icons.SETTINGS, settings_view),
]


def _is_linux_desktop(page: ft.Page) -> bool:
    """判断当前是否为 Linux 桌面端。"""
    return sys.platform.startswith("linux") and not page.web


def _use_builtin_title_bar(page: ft.Page) -> bool:
    """判断是否启用 Linux 内置标题栏。"""
    return _is_linux_desktop(page) and should_use_linux_builtin_title_bar()


def _enable_builtin_title_bar(page: ft.Page) -> bool:
    """尝试隐藏系统标题栏但保留窗口边框，成功返回 True。"""
    window = page.window
    if hasattr(window, "title_bar_hidden"):
        window.title_bar_hidden = True
        if hasattr(window, "title_bar_buttons_hidden"):
            window.title_bar_buttons_hidden = True
        return True
    log_debug("nav", "linux builtin title bar requested but title_bar_hidden is unavailable")
    return False


def _create_title_bar(page: ft.Page) -> ft.Control:
    """创建 Linux 内置标题栏控件。"""
    def minimize(e):
        page.window.minimized = True
        page.update()

    def toggle_maximize(e):
        page.window.maximized = not page.window.maximized
        page.update()

    def close(e):
        page.window.close()

    return ft.Container(
        height=38,
        bgcolor=ft.Colors.SURFACE,
        border=ft.border.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        content=ft.Row(
            [
                ft.WindowDragArea(
                    content=ft.Container(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.IMAGE_SEARCH, size=18),
                                ft.Text("FletViewer", size=13, weight=ft.FontWeight.W_500),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding(12, 0, 0, 0),
                        alignment=ft.Alignment(-1, 0),
                    ),
                    expand=True,
                ),
                ft.IconButton(ft.Icons.REMOVE, tooltip="最小化", on_click=minimize),
                ft.IconButton(ft.Icons.CROP_SQUARE, tooltip="最大化/还原", on_click=toggle_maximize),
                ft.IconButton(ft.Icons.CLOSE, tooltip="关闭", on_click=close),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )


def _should_use_safe_area(page: ft.Page) -> bool:
    """判断是否应包裹 SafeArea 以适配移动端状态栏和异形屏。"""
    platform = str(getattr(page, "platform", "") or "").lower()
    return page.web or "android" in platform or "ios" in platform


def main(page: ft.Page):
    """Flet 应用主入口，负责全局导航、页面缓存和二级页面切换。"""
    page.title = "FletViewer"
    if page.web:
        os.environ["FLETVIEWER_WEB"] = "1"
    local_gallery_manager.initialize()
    use_builtin_title_bar = _use_builtin_title_bar(page) and _enable_builtin_title_bar(page)

    content_switcher = ft.AnimatedSwitcher(
        content=ft.Container(expand=True),
        duration=180,
        reverse_duration=120,
        switch_in_curve=ft.AnimationCurve.EASE_OUT,
        switch_out_curve=ft.AnimationCurve.EASE_IN,
        transition=ft.AnimatedSwitcherTransition.FADE,
        expand=True,
    )
    content = ft.Container(content=content_switcher, expand=True, padding=ft.Padding(8, 72, 8, 8))
    view_cache: dict[str, ft.Control] = {}
    content_generation = {"value": 0}
    current_content: dict[str, ft.Control | None] = {"value": None}
    shell_host: dict[str, ft.Container | None] = {"value": None}
    resize_handlers = []
    header_title = ft.Text("FletViewer", size=18, weight=ft.FontWeight.W_600, overflow=ft.TextOverflow.ELLIPSIS)
    header_subtitle = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT, overflow=ft.TextOverflow.ELLIPSIS)
    header_actions = ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    header_action_cache: dict[str, list[ft.Control]] = {}
    active_cache_key = {"value": ""}

    def set_header(title: str, subtitle: str = "") -> None:
        header_title.value = title
        header_subtitle.value = subtitle

    def set_header_actions(controls: list[ft.Control] | None = None) -> None:
        actions = list(controls or [])
        header_actions.controls = actions
        key = active_cache_key.get("value")
        if key:
            header_action_cache[key] = actions

    page.fletviewer_set_header_actions = set_header_actions

    def add_resize_handler(handler):
        if handler not in resize_handlers:
            resize_handlers.append(handler)

        def remove_handler():
            if handler in resize_handlers:
                resize_handlers.remove(handler)

        return remove_handler

    def on_page_resized(e):
        log_debug("nav", f"resize width={page.width} height={page.height} handlers={len(resize_handlers)}")
        for handler in list(resize_handlers):
            try:
                handler(e)
            except Exception as ex:
                log_debug("nav", f"resize handler failed: {ex}")

    page.fletviewer_add_resize_handler = add_resize_handler
    page.on_resize = on_page_resized

    def begin_content_transition():
        """导航开始时立即让旧页面后台图片任务失效。"""
        content_generation["value"] += 1
        page.fletviewer_content_generation = content_generation["value"]

    def detach_content_for_navigation():
        """先卸载旧内容，避免旧页面图片控件继续阻塞新页面切换。"""
        begin_content_transition()
        content_switcher.content = ft.Container(key=f"content:detached:{content_generation['value']}", expand=True)
        current_content["value"] = None
        page.update()

    def set_content(control: ft.Control):
        current_content["value"] = control
        content_generation["value"] += 1
        page.fletviewer_content_generation = content_generation["value"]
        content_switcher.content = ft.Container(
            content=control,
            key=f"content:{content_generation['value']}",
            expand=True,
        )

    def animated_scale_container(control: ft.Control) -> ft.Container:
        """创建二级页面放大淡入容器。"""
        return ft.Container(
            content=control,
            expand=True,
            opacity=0,
            scale=0.96,
            animate_opacity=180,
            animate_scale=180,
            alignment=ft.Alignment(0, 0),
        )

    def play_enter_animation(container: ft.Container):
        def worker():
            time.sleep(0.02)
            container.opacity = 1
            container.scale = 1
            page.update()

        page.run_thread(worker)

    def play_exit_animation(container: ft.Container, after):
        container.opacity = 0
        container.scale = 0.96
        page.update()

        def worker():
            time.sleep(0.18)
            after()

        page.run_thread(worker)

    def pop_top_view():
        if len(page.views) > 1:
            page.views.pop()
            page.route = page.views[-1].route or "/"
            page.update()

    def handle_view_pop(e):
        pop_top_view()

    page.on_view_pop = handle_view_pop

    def invalidate_views(keys: list[str] | None = None, reason: str = ""):
        targets = keys or list(view_cache.keys())
        for key in targets:
            if key in view_cache:
                view_cache.pop(key, None)
                log_debug("nav", f"invalidate {key} reason={reason}")

    page.fletviewer_invalidate_views = invalidate_views

    def open_gallery_detail(comic):
        log_debug("nav", f"open gallery detail {comic.id}")
        detail_container = animated_scale_container(ft.Container(expand=True))

        def go_back():
            log_debug("nav", f"close gallery detail {comic.id}")
            pop_top_view()

        detail_container.content = gallery_detail_view(page, comic, go_back)
        page.views.append(
            ft.View(
                route=f"/gallery/{len(page.views)}",
                controls=[detail_container],
                padding=8,
                appbar=ft.AppBar(
                    title=ft.Text(comic.title or "画廊详情", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    leading=ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回", on_click=lambda e: go_back()),
                    automatically_imply_leading=False,
                ),
            )
        )
        page.route = page.views[-1].route
        page.update()
        play_enter_animation(detail_container)

    page.fletviewer_open_gallery_detail = open_gallery_detail

    def open_image_viewer(items, initial_index=0, resolve_image_url=None):
        log_debug("nav", f"open image viewer index={initial_index} count={len(items)}")
        viewer_container: ft.Container | None = None

        def go_back():
            log_debug("nav", "close image viewer")
            pop_top_view()

        viewer_container = animated_scale_container(
            image_viewer_view(
                page,
                items,
                initial_index,
                go_back,
                resolve_image_url=resolve_image_url,
            ),
        )
        page.views.append(ft.View(route=f"/viewer/{initial_index}", controls=[viewer_container], padding=0))
        page.route = page.views[-1].route
        page.update()
        play_enter_animation(viewer_container)

    page.fletviewer_open_image_viewer = open_image_viewer

    def open_input_test_view():
        log_debug("nav", "open input test view")
        page.views.append(
            ft.View(
                route="/input-test",
                controls=[input_test_view(page)],
                padding=8,
                appbar=ft.AppBar(
                    title=ft.Text("输入测试"),
                    leading=ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回", on_click=lambda e: pop_top_view()),
                    automatically_imply_leading=False,
                ),
            )
        )
        page.route = page.views[-1].route
        page.update()

    def render_search():
        detach_content_for_navigation()
        active_cache_key["value"] = "search"
        started_at = time.perf_counter()
        set_header("搜索", "E-Hentai 画廊搜索")
        set_header_actions(header_action_cache.get("search", []))
        if "search" not in view_cache:
            log_debug("nav", "create view search")
            view_cache["search"] = search_view(page)
        else:
            log_debug("nav", "reuse view search")
        set_content(view_cache["search"])
        page.update()
        log_debug("nav", f"切换视图 搜索 用时={format_duration_ms((time.perf_counter() - started_at) * 1000)}")

    def render(idx):
        if idx is None or idx < 0 or idx >= len(PAGES):
            log_debug("nav", f"忽略无效导航索引 idx={idx}")
            return
        started_at = time.perf_counter()
        label, subtitle, _icon, view_fn = PAGES[idx]
        if view_fn is input_test_view:
            open_input_test_view()
            return
        detach_content_for_navigation()
        set_header(label, subtitle)
        cache_key = f"page:{idx}"
        active_cache_key["value"] = cache_key
        set_header_actions(header_action_cache.get(cache_key, []))
        if view_fn is None:
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
            set_content(view_cache[cache_key])
        else:
            if cache_key not in view_cache:
                log_debug("nav", f"create view {label}")
                view_cache[cache_key] = view_fn(page)
            else:
                log_debug("nav", f"reuse view {label}")
            set_content(view_cache[cache_key])
        page.update()
        log_debug("nav", f"切换视图 {label} 用时={format_duration_ms((time.perf_counter() - started_at) * 1000)} cache_key={cache_key}")

    def close_left_drawer():
        async def worker():
            await page.close_drawer()

        page.run_task(worker)

    def close_right_drawer():
        async def worker():
            await page.close_end_drawer()

        page.run_task(worker)

    def open_left_drawer(e=None):
        async def worker():
            await page.show_drawer()

        page.run_task(worker)

    def open_right_drawer(e=None):
        async def worker():
            await page.show_end_drawer()

        page.run_task(worker)

    def toggle_primary_nav(e=None):
        open_left_drawer(e)

    def create_left_drawer() -> ft.NavigationDrawer:
        return ft.NavigationDrawer(
            controls=[
                ft.Container(
                    content=ft.Text("FletViewer", size=20, weight=ft.FontWeight.BOLD),
                    padding=ft.Padding(16, 18, 16, 10),
                ),
                ft.NavigationDrawerDestination(label="搜索", icon=ft.Icons.SEARCH),
                *[
                    ft.NavigationDrawerDestination(label=label, icon=icon, selected_icon=icon)
                    for label, _subtitle, icon, _ in PAGES
                ],
            ],
            selected_index=1,
            on_change=lambda e: None if e.control.selected_index is None else render_search() if e.control.selected_index == 0 else (close_left_drawer(), render(e.control.selected_index - 1)),
        )

    def create_right_drawer() -> ft.NavigationDrawer:
        return ft.NavigationDrawer(
            controls=[
                ft.Container(
                    content=ft.Text("平台", size=20, weight=ft.FontWeight.BOLD),
                    padding=ft.Padding(16, 18, 16, 10),
                ),
                ft.NavigationDrawerDestination(label="E-Hentai", icon=ft.Icons.PUBLIC),
                ft.NavigationDrawerDestination(label="ExHentai（未实现）", icon=ft.Icons.LOCK_OUTLINE),
                ft.NavigationDrawerDestination(label="Booru（未实现）", icon=ft.Icons.IMAGE_SEARCH),
                ft.NavigationDrawerDestination(label="Pixiv（未实现）", icon=ft.Icons.BRUSH),
            ],
            selected_index=0,
            on_change=lambda e: close_right_drawer(),
        )

    root_left_drawer = create_left_drawer()
    root_right_drawer = create_right_drawer()

    top_bar = ft.Container(
        content=ft.Row(
            [
                ft.IconButton(ft.Icons.MENU, tooltip="导航", on_click=toggle_primary_nav),
                ft.Column([header_title, header_subtitle], spacing=0, expand=True),
                header_actions,
                ft.IconButton(ft.Icons.TUNE, tooltip="平台", on_click=open_right_drawer),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        visible=True,
        left=12,
        right=12,
        top=12,
        padding=ft.Padding(8, 6, 8, 6),
        bgcolor=ft.Colors.with_opacity(0.82, ft.Colors.SURFACE_CONTAINER_HIGH),
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=999,
        shadow=ft.BoxShadow(
            blur_radius=20,
            spread_radius=0,
            color=ft.Colors.with_opacity(0.22, ft.Colors.BLACK),
            offset=ft.Offset(0, 6),
        ),
    )

    def update_top_bar_width(e=None):
        width = float(page.width or 0)
        if width >= 900:
            bar_width = min(width * 0.7, 1120)
            top_bar.width = bar_width
            top_bar.left = max(12, (width - bar_width) / 2)
            top_bar.right = None
            top_bar.align = None
        else:
            top_bar.width = None
            top_bar.left = 12
            top_bar.right = 12
            top_bar.align = None

    body = ft.Stack(
        controls=[
            ft.Row(
                [
                    content,
                ],
                expand=True,
            ),
            top_bar,
        ],
        expand=True,
    )
    update_top_bar_width()
    add_resize_handler(lambda e=None: (update_top_bar_width(e), page.update()))

    app_body_host = ft.Container(content=body, expand=True)
    shell_host["value"] = app_body_host

    if use_builtin_title_bar:
        root = ft.Column(
            [
                _create_title_bar(page),
                app_body_host,
            ],
            spacing=0,
            expand=True,
        )
    else:
        root = app_body_host

    if _should_use_safe_area(page):
        root = ft.SafeArea(content=root, expand=True)

    page.views.clear()
    page.views.append(ft.View(route="/", controls=[root], padding=0, drawer=root_left_drawer, end_drawer=root_right_drawer))
    page.route = "/"
    page.update()
    render(0)

    def initialize_browser_session():
        try:
            browser_session.set_login_enabled(browser_session.login_enabled(), verify=True)
        except Exception as ex:
            log_debug("nav", f"初始化网络会话失败: {ex}")

    page.run_thread(initialize_browser_session)


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
