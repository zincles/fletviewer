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
from app.theme import apply_app_theme, refresh_adaptive_theme_on_brightness_change
from app.views.downloads import create_view as downloads_view
from app.views.debug import create_view as debug_view
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
    ("设置", "应用设置", ft.Icons.SETTINGS, settings_view),
]
READING_PAGE_LABELS = {"主页", "订阅", "热门", "排行榜", "收藏"}
READING_PAGE_INDEXES = [idx for idx, (label, _subtitle, _icon, _view_fn) in enumerate(PAGES) if label in READING_PAGE_LABELS]

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
    apply_app_theme(page)
    page.fletviewer_apply_theme = lambda update=True: apply_app_theme(page, update=update)
    page.on_platform_brightness_change = lambda e: refresh_adaptive_theme_on_brightness_change(page)
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
    content = ft.Container(content=content_switcher, expand=True, padding=ft.Padding(0, 8, 0, 0))
    view_cache: dict[str, ft.Control] = {}
    content_generation = {"value": 0}
    current_content: dict[str, ft.Control | None] = {"value": None}
    shell_host: dict[str, ft.Container | None] = {"value": None}
    resize_handlers = []
    header_actions = ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    header_action_cache: dict[str, list[ft.Control]] = {}
    reading_refresh_action_cache: dict[str, object] = {}
    active_cache_key = {"value": ""}
    bottom_nav_state = {"value": "阅读"}
    bottom_nav_segments: dict[str, ft.Container] = {}
    root_tabs_ref: dict[str, ft.Tabs | None] = {"value": None}
    root_tabs_syncing = {"value": False}
    reading_tabs_ref: dict[str, ft.Tabs | None] = {"value": None}
    reading_tabs_syncing = {"value": False}
    reading_tab_pages: list[ft.Container] = []
    top_bar_state = {"offset": 0.0}
    reading_content_host: ft.Container | None = None
    reading_speed_dial_state = {"open": False}
    section_indexes = {"阅读": 0, "本地": 1, "设置": 2}
    bottom_nav_for_page = {"本地画廊": "本地", "设置": "设置"}

    def set_bottom_nav(value: str):
        bottom_nav_state["value"] = value
        for label, segment in bottom_nav_segments.items():
            selected = label == value
            segment.bgcolor = ft.Colors.PRIMARY if selected else ft.Colors.TRANSPARENT
            content = segment.content
            if isinstance(content, (ft.Row, ft.Column)):
                for control in content.controls:
                    if isinstance(control, ft.Icon):
                        control.color = ft.Colors.ON_PRIMARY if selected else ft.Colors.ON_SURFACE_VARIANT
                    elif isinstance(control, ft.Text):
                        control.color = ft.Colors.ON_PRIMARY if selected else ft.Colors.ON_SURFACE_VARIANT
                        control.weight = ft.FontWeight.W_600 if selected else ft.FontWeight.W_500

    def activate_root_section(value: str, update: bool = True, sync_bottom_nav: bool = True):
        if sync_bottom_nav:
            set_bottom_nav(value)
        tabs = root_tabs_ref.get("value")
        if tabs is not None:
            target_index = section_indexes.get(value, 0)
            if tabs.selected_index != target_index:
                root_tabs_syncing["value"] = True
                tabs.selected_index = target_index
                root_tabs_syncing["value"] = False
        if update:
            page.update()

    def sync_reading_tab(label: str) -> None:
        tabs = reading_tabs_ref.get("value")
        if tabs is None:
            return
        try:
            target_index = [PAGES[idx][0] for idx in READING_PAGE_INDEXES].index(label)
        except ValueError:
            return
        for idx, holder in enumerate(reading_tab_pages):
            holder.content = content if idx == target_index else None
        if tabs.selected_index != target_index:
            reading_tabs_syncing["value"] = True
            tabs.selected_index = target_index
            reading_tabs_syncing["value"] = False

    def set_header(title: str, subtitle: str = "") -> None:
        return

    def set_header_actions(controls: list[ft.Control] | None = None) -> None:
        actions = list(controls or [])
        header_actions.controls = actions
        key = active_cache_key.get("value")
        if key:
            header_action_cache[key] = actions

    page.fletviewer_set_header_actions = set_header_actions

    def set_reading_refresh_action(action=None) -> None:
        key = active_cache_key.get("value")
        if not key:
            return
        if callable(action):
            reading_refresh_action_cache[key] = action
        else:
            reading_refresh_action_cache.pop(key, None)

    page.fletviewer_set_reading_refresh_action = set_reading_refresh_action

    def show_reading_action_hint(message: str) -> None:
        dialog = ft.AlertDialog(
            title=ft.Text("阅读工具"),
            content=ft.Text(message),
            actions=[ft.TextButton("知道了", on_click=lambda e: page.pop_dialog())],
        )
        dialog.open = True
        page.show_dialog(dialog)

    def set_reading_speed_dial_open(opened: bool, update: bool = True) -> None:
        reading_speed_dial_state["open"] = opened
        reading_speed_dial_fab.icon = ft.Icons.CLOSE if opened else ft.Icons.ADD

        if opened:
            for idx, item in enumerate(reading_speed_dial_items):
                item.visible = True
                item.opacity = 0.0
                item.offset = ft.Offset(0, 0.24 + idx * 0.04)
            page.update()

            def worker():
                for idx, item in enumerate(reversed(reading_speed_dial_items)):
                    time.sleep(0.03)
                    item.opacity = 1.0
                    item.offset = ft.Offset(0, 0)
                    page.update()

            page.run_thread(worker)
            return

        for idx, item in enumerate(reading_speed_dial_items):
            item.opacity = 0.0
            item.offset = ft.Offset(0, 0.24 + idx * 0.04)
        if update:
            page.update()

        def hide_worker():
            time.sleep(0.18)
            for item in reading_speed_dial_items:
                item.visible = False
            page.update()

        page.run_thread(hide_worker)

    def toggle_reading_speed_dial(e=None) -> None:
        set_reading_speed_dial_open(not reading_speed_dial_state["open"])

    def set_top_bar_scroll_offset(offset: float, update: bool = True) -> None:
        clamped = max(0.0, min(88.0, offset))
        if abs(clamped - top_bar_state["offset"]) < 0.5:
            return
        top_bar_state["offset"] = clamped
        top_bar.top = -clamped
        top_bar.opacity = max(0.18, 1.0 - clamped / 70.0)
        if update:
            page.update()

    def on_content_scroll(delta: float | None = None, pixels: float | None = None) -> None:
        if pixels is not None and pixels <= 2:
            set_top_bar_scroll_offset(0.0)
            return
        if delta is None or abs(delta) < 0.5:
            return
        set_top_bar_scroll_offset(top_bar_state["offset"] + delta)

    page.fletviewer_on_content_scroll = on_content_scroll

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

    route_view_cache: dict[str, ft.View] = {}
    route_parent_cache: dict[str, str] = {}
    root_view_ref: dict[str, ft.View | None] = {"value": None}

    def push_route(route: str) -> None:
        page.navigate(route)

    def rebuild_views_for_route(route: str | None = None):
        target_route = route or page.route or "/"
        root_view = root_view_ref.get("value")
        if root_view is None:
            return

        chain: list[str] = []
        cursor = target_route
        seen: set[str] = set()
        while cursor and cursor != "/" and cursor not in seen:
            seen.add(cursor)
            if cursor not in route_view_cache:
                break
            chain.append(cursor)
            cursor = route_parent_cache.get(cursor, "/")
        chain.reverse()

        page.views.clear()
        page.views.append(root_view)
        for child_route in chain:
            view = route_view_cache.get(child_route)
            if view is not None:
                page.views.append(view)
        page.route = page.views[-1].route or "/"
        page.update()

    def pop_top_view():
        if len(page.views) > 1:
            push_route(page.views[-2].route or "/")

    def push_app_view(view: ft.View, parent_route: str | None = None):
        route = view.route or f"/view/{len(route_view_cache) + 1}"
        view.route = route
        route_view_cache[route] = view
        route_parent_cache[route] = parent_route or (page.views[-1].route if page.views else "/") or "/"
        push_route(route)

    def handle_route_change(e=None):
        log_debug("nav", f"route change route={page.route} cached_views={len(route_view_cache)}")
        rebuild_views_for_route(page.route)

    async def handle_view_pop(e):
        if len(page.views) <= 1:
            return
        view = getattr(e, "view", None)
        if view in page.views and page.views.index(view) > 0:
            target_index = page.views.index(view) - 1
            target_route = page.views[target_index].route or "/"
        else:
            target_route = page.views[-2].route or "/"
        await page.push_route(target_route)

    page.on_route_change = handle_route_change
    page.on_view_pop = handle_view_pop
    page.fletviewer_push_view = push_app_view
    page.fletviewer_pop_view = pop_top_view

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
        route = f"/gallery/{len(page.views)}"

        def go_back():
            log_debug("nav", f"close gallery detail {comic.id}")
            pop_top_view()

        detail_container.content = gallery_detail_view(page, comic, go_back)
        push_app_view(
            ft.View(
                route=route,
                controls=[detail_container],
                padding=8,
                appbar=ft.AppBar(
                    title=ft.Text(""),
                    leading=ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回", on_click=lambda e: go_back()),
                    automatically_imply_leading=False,
                ),
            )
        )
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
        route = f"/viewer/{len(page.views)}-{initial_index}"
        push_app_view(ft.View(route=route, controls=[viewer_container], padding=0))
        play_enter_animation(viewer_container)

    page.fletviewer_open_image_viewer = open_image_viewer

    def render_search(keyword: str | None = None):
        detach_content_for_navigation()
        active_cache_key["value"] = "search"
        started_at = time.perf_counter()
        set_header("搜索", "E-Hentai 画廊搜索")
        set_bottom_nav("阅读")
        set_header_actions(header_action_cache.get("search", []))
        if "search" not in view_cache:
            log_debug("nav", "create view search")
            view_cache["search"] = search_view(page)
        else:
            log_debug("nav", "reuse view search")
        set_content(view_cache["search"])
        if keyword is not None:
            run_search = getattr(page, "fletviewer_run_search", None)
            if callable(run_search):
                run_search(keyword)
        page.update()
        log_debug("nav", f"切换视图 搜索 用时={format_duration_ms((time.perf_counter() - started_at) * 1000)}")

    def render(idx):
        if idx is None or idx < 0 or idx >= len(PAGES):
            log_debug("nav", f"忽略无效导航索引 idx={idx}")
            return
        started_at = time.perf_counter()
        label, subtitle, icon, view_fn = PAGES[idx]
        if label == "本地画廊":
            set_header(label, subtitle)
            set_header_actions([])
            activate_root_section("本地")
            log_debug("nav", f"切换主分区 本地 用时={format_duration_ms((time.perf_counter() - started_at) * 1000)}")
            return
        if label == "设置":
            set_header(label, subtitle)
            set_header_actions([])
            activate_root_section("设置")
            log_debug("nav", f"切换主分区 设置 用时={format_duration_ms((time.perf_counter() - started_at) * 1000)}")
            return
        detach_content_for_navigation()
        set_header(label, subtitle)
        set_bottom_nav(bottom_nav_for_page.get(label, "阅读"))
        if label in READING_PAGE_LABELS:
            sync_reading_tab(label)
        activate_root_section("阅读", update=False, sync_bottom_nav=False)
        cache_key = f"page:{idx}"
        active_cache_key["value"] = cache_key
        set_header_actions(header_action_cache.get(cache_key, []))
        if view_fn is None:
            if cache_key not in view_cache:
                log_debug("nav", f"create placeholder {label}")
                view_cache[cache_key] = ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(icon, size=42, color=ft.Colors.PRIMARY),
                            ft.Text(label, size=28, weight=ft.FontWeight.BOLD),
                            ft.Text(subtitle, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text("入口已预留，功能稍后接入。", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=10,
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=18,
                    padding=24,
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

    def render_label(label: str):
        for idx, (page_label, _subtitle, _icon, _view_fn) in enumerate(PAGES):
            if page_label == label:
                render(idx)
                return
        log_debug("nav", f"忽略无效导航标签 label={label}")

    page.fletviewer_render_label = render_label

    def close_right_drawer():
        async def worker():
            await page.close_end_drawer()

        page.run_task(worker)

    def open_right_drawer(e=None):
        async def worker():
            await page.show_end_drawer()

        page.run_task(worker)

    def create_right_drawer() -> ft.NavigationDrawer:
        return ft.NavigationDrawer(
            controls=[
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text("平台", size=20, weight=ft.FontWeight.BOLD),
                            ft.Text("选择当前 provider", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=2,
                    ),
                    padding=ft.Padding(16, 18, 16, 12),
                ),
                ft.NavigationDrawerDestination(label="E-Hentai", icon=ft.Icons.PUBLIC),
                ft.NavigationDrawerDestination(label="ExHentai（未实现）", icon=ft.Icons.LOCK_OUTLINE),
                ft.NavigationDrawerDestination(label="Booru（未实现）", icon=ft.Icons.IMAGE_SEARCH),
                ft.NavigationDrawerDestination(label="Pixiv（未实现）", icon=ft.Icons.BRUSH),
            ],
            selected_index=0,
            on_change=lambda e: close_right_drawer(),
        )

    root_right_drawer = create_right_drawer()
    top_search_field = ft.SearchBar(
        bar_hint_text="搜索画廊、标签、作者",
        bar_leading=ft.Icon(ft.Icons.SEARCH),
        bar_bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        bar_elevation=0,
        bar_shape=ft.StadiumBorder(),
        bar_border_side=ft.BorderSide(0, ft.Colors.TRANSPARENT),
        bar_padding=ft.Padding(12, 0, 12, 0),
        view_hint_text="搜索画廊、标签、作者",
        view_leading=ft.Icon(ft.Icons.SEARCH),
        view_elevation=2,
        view_shape=ft.RoundedRectangleBorder(radius=28),
        full_screen=False,
        shrink_wrap=True,
        height=44,
        expand=True,
    )

    def submit_top_search(e=None):
        keyword = (top_search_field.value or "").strip()
        render_search(keyword if keyword else None)

    top_search_field.on_submit = submit_top_search

    reading_top_row = ft.Container(
        content=ft.Row(
            [
                top_search_field,
                header_actions,
                ft.IconButton(ft.Icons.TUNE, tooltip="平台", on_click=open_right_drawer),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=50,
        padding=ft.Padding(8, 4, 8, 4),
        bgcolor=ft.Colors.SURFACE,
    )

    top_bar = ft.Container(
        visible=True,
        height=98,
        left=0,
        right=0,
        top=0,
        bgcolor=ft.Colors.SURFACE,
        border=ft.border.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
    )

    def section_top_bar(title: str, actions: list[ft.Control] | None = None) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(title, size=18, weight=ft.FontWeight.W_600, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                    *(actions or []),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=True,
            height=50,
            left=0,
            right=0,
            top=0,
            padding=ft.Padding(8, 4, 8, 4),
            bgcolor=ft.Colors.SURFACE,
            border=ft.border.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

    def bottom_nav_segment(label: str, icon, target: str) -> ft.Container:
        selected = label == bottom_nav_state["value"]
        color = ft.Colors.ON_PRIMARY if selected else ft.Colors.ON_SURFACE_VARIANT
        segment = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, size=20, color=color),
                    ft.Text(label, size=11, weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500, color=color),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=1,
            ),
            height=54,
            expand=1,
            border_radius=999,
            bgcolor=ft.Colors.PRIMARY if selected else ft.Colors.TRANSPARENT,
            ink=True,
            on_click=lambda e: render_label(target),
        )
        bottom_nav_segments[label] = segment
        return segment

    bottom_nav = ft.Container(
        content=ft.Row(
            [
                bottom_nav_segment("阅读", ft.Icons.PUBLIC, "主页"),
                bottom_nav_segment("本地", ft.Icons.FOLDER, "本地画廊"),
                bottom_nav_segment("设置", ft.Icons.SETTINGS, "设置"),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=3,
        ),
        width=360,
        padding=ft.Padding(4, 5, 4, 5),
        bgcolor=ft.Colors.with_opacity(0.78, ft.Colors.SURFACE_CONTAINER_HIGH),
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=999,
        shadow=ft.BoxShadow(
            blur_radius=18,
            spread_radius=0,
            color=ft.Colors.with_opacity(0.24, ft.Colors.BLACK),
            offset=ft.Offset(0, 6),
        ),
    )

    def on_root_tabs_change(e):
        if root_tabs_syncing["value"]:
            return
        selected_index = int(getattr(e.control, "selected_index", 0) or 0)
        if selected_index == 1:
            render_label("本地画廊")
        elif selected_index == 2:
            render_label("设置")
        else:
            render_label("主页")

    def on_reading_tabs_change(e):
        if reading_tabs_syncing["value"]:
            return
        selected_index = int(getattr(e.control, "selected_index", 0) or 0)
        if selected_index < 0 or selected_index >= len(READING_PAGE_INDEXES):
            return
        render(READING_PAGE_INDEXES[selected_index])

    reading_tab_pages[:] = [ft.Container(expand=True) for _idx in READING_PAGE_INDEXES]
    reading_tab_pages[0].content = content

    reading_tab_bar = ft.TabBar(
        tabs=[ft.Tab(label=PAGES[idx][0]) for idx in READING_PAGE_INDEXES],
        divider_height=0,
        divider_color=ft.Colors.TRANSPARENT,
        indicator_thickness=3,
        label_padding=ft.Padding(14, 0, 14, 0),
    )

    top_bar.content = ft.Column(
        [
            reading_top_row,
            reading_tab_bar,
        ],
        spacing=0,
        expand=True,
    )

    def reading_speed_dial_item(icon, label: str, on_click) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Text(label, size=12, color=ft.Colors.ON_SURFACE),
                        padding=ft.Padding(10, 6, 10, 6),
                        bgcolor=ft.Colors.SURFACE,
                        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                        border_radius=999,
                    ),
                    ft.FloatingActionButton(icon=icon, mini=True, on_click=on_click),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.END,
            ),
            visible=False,
            opacity=0.0,
            offset=ft.Offset(0, 0.2),
            animate_opacity=160,
            animate_offset=160,
            animate_scale=160,
        )

    def refresh_current_reading_page(e=None):
        action = reading_refresh_action_cache.get(active_cache_key.get("value", ""))
        set_reading_speed_dial_open(False)
        if callable(action):
            action()
        else:
            show_reading_action_hint("当前页面没有可刷新的内容。")

    reading_speed_dial_items = [
        reading_speed_dial_item(ft.Icons.REFRESH, "刷新", refresh_current_reading_page),
        reading_speed_dial_item(ft.Icons.PIN, "跳转页数", lambda e: show_reading_action_hint("这里后续接“跳转到页数”功能。")),
        reading_speed_dial_item(ft.Icons.BOOKMARK_ADD, "收藏操作", lambda e: show_reading_action_hint("这里后续接收藏/批量操作。")),
        reading_speed_dial_item(ft.Icons.TUNE, "更多筛选", lambda e: show_reading_action_hint("这里后续接筛选/排序工具。")),
    ]
    reading_speed_dial_fab = ft.FloatingActionButton(icon=ft.Icons.ADD, tooltip="阅读工具", on_click=toggle_reading_speed_dial)
    reading_speed_dial = ft.Container(
        content=ft.Column(
            [*reading_speed_dial_items, reading_speed_dial_fab],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.END,
        ),
        right=16,
        bottom=92,
    )

    reading_tabs = ft.Tabs(
        content=ft.Stack(
            controls=[
                ft.TabBarView(
                    controls=reading_tab_pages,
                    expand=True,
                ),
                top_bar,
                reading_speed_dial,
            ],
            expand=True,
        ),
        length=len(READING_PAGE_INDEXES),
        selected_index=0,
        animation_duration=160,
        on_change=on_reading_tabs_change,
        expand=True,
    )
    reading_tabs_ref["value"] = reading_tabs
    reading_content_host = ft.Container(content=reading_tabs, expand=True)
    reading_section = reading_content_host
    local_section = ft.Stack(
        controls=[
            ft.Container(content=local_galleries_view(page), expand=True, padding=ft.Padding(8, 0, 8, 0)),
            section_top_bar("本地", [ft.IconButton(ft.Icons.DOWNLOAD, tooltip="下载", on_click=lambda e: render_label("下载"))]),
        ],
        expand=True,
    )
    settings_section = ft.Stack(
        controls=[
            ft.Container(content=settings_view(page), expand=True, padding=ft.Padding(8, 0, 8, 0)),
            section_top_bar("设置"),
        ],
        expand=True,
    )
    root_tabs = ft.Tabs(
        content=ft.TabBarView(
            controls=[reading_section, local_section, settings_section],
            expand=True,
        ),
        length=3,
        selected_index=0,
        animation_duration=180,
        on_change=on_root_tabs_change,
        expand=True,
    )
    root_tabs_ref["value"] = root_tabs

    body = ft.Stack(
        controls=[
            ft.Row(
                [
                    root_tabs,
                ],
                expand=True,
            ),
            ft.Container(
                content=bottom_nav,
                left=0,
                right=0,
                bottom=12,
                alignment=ft.Alignment(0, 1),
            ),
        ],
        expand=True,
    )

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
    root_view_ref["value"] = ft.View(route="/", controls=[root], padding=0, end_drawer=root_right_drawer)
    page.views.append(root_view_ref["value"])
    page.update()
    render(0)
    rebuild_views_for_route(page.route or "/")

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
