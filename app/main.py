import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platform_storage import resolve_storage
from app.storage import configure_storage

_ACTIVE_STORAGE = resolve_storage()
configure_storage(_ACTIVE_STORAGE.layout)

if sys.platform.startswith("linux") and "--web" not in sys.argv and "--server" not in sys.argv:
    from app.storage import should_prefer_linux_wayland_window_backend

    backend = "wayland" if should_prefer_linux_wayland_window_backend() else "x11"
    os.environ.setdefault("GDK_BACKEND", backend)
    os.environ.setdefault("GTK_CSD", "0")

import flet as ft

from app.browser_session import browser_session
from app.controls.task_debug_overlay import TaskDebugOverlay
from app.debug_log import configure_logging, format_duration_ms, log_debug, log_exception
from app.local_gallery_manager import local_gallery_manager
from app.navigation import AppNavigator
from app.notifications import Notification, notifier
from app.storage import should_use_linux_builtin_title_bar
from app.theme import apply_app_theme, refresh_adaptive_theme_on_brightness_change
from app.ui_update import request_update
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
from app.views.search import SearchContext, create_view as search_view
from core.provider.ehgrabber import SearchResult
from app.views.settings import create_view as settings_view
from app.views.history import create_view as history_view
from app.history import record_gallery_history

PAGES = [
    ("主页", "最新画廊", ft.Icons.HOME, home_view),
    ("订阅", "关注的标签画廊（需登录）", ft.Icons.SUBSCRIPTIONS, subscriptions_view),
    ("热门", "近期热门画廊", ft.Icons.LOCAL_FIRE_DEPARTMENT, popular_view),
    ("排行榜", "EH 排行榜", ft.Icons.LEADERBOARD, leaderboard_view),
    ("收藏", "收藏夹画廊（需登录）", ft.Icons.BOOKMARK, favorites_view),
    ("本地画廊", "已下载 Archive", ft.Icons.FOLDER, local_galleries_view),
    ("历史", "浏览历史", ft.Icons.HISTORY, history_view),
    ("下载", "下载任务", ft.Icons.DOWNLOAD, downloads_view),
    ("调试", "小图任务", ft.Icons.BUG_REPORT, debug_view),
    ("设置", "应用设置", ft.Icons.SETTINGS, settings_view),
]
READING_PAGE_LABELS = {"主页", "订阅", "热门", "排行榜", "收藏", "历史"}
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
    log_debug("导航", "已请求使用 Linux 内置标题栏，但 title_bar_hidden 不可用")
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
    active_storage = _ACTIVE_STORAGE
    configure_logging(active_storage.layout.debug_log_file)
    print("[存储] 平台：", page.platform)
    print("[存储] FLET_APP_STORAGE_DATA：", os.environ.get("FLET_APP_STORAGE_DATA") or "<未设置>")
    print("[存储] FLET_APP_STORAGE_TEMP：", os.environ.get("FLET_APP_STORAGE_TEMP") or "<未设置>")
    for domain in ("data", "cache", "downloads", "temp"):
        print(
            f"[存储] {domain}：",
            getattr(active_storage.paths, domain),
            f"（来源={active_storage.sources[domain]}）",
        )
    page.title = "FletViewer"
    apply_app_theme(page)
    page.fletviewer_apply_theme = lambda update=True: apply_app_theme(page, update=update)
    page.on_platform_brightness_change = lambda e: refresh_adaptive_theme_on_brightness_change(page)
    if page.web:
        os.environ["FLETVIEWER_WEB"] = "1"
    page.fletviewer_storage_error = None
    try:
        local_gallery_manager.initialize()
    except Exception as ex:
        page.fletviewer_storage_error = str(ex)
        log_exception("存储", f"数据存储不可用，将以受限模式启动：{ex}")
        notifier.send(Notification("存储不可用", str(ex), "storage.unavailable"))
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
    reading_loading_sources: set[str] = set()
    reading_loading_indicator_ref: dict[str, ft.ProgressBar | None] = {"value": None}
    active_cache_key = {"value": ""}
    active_page_label = {"value": "主页"}
    top_search_hint_ref: dict[str, ft.Text | None] = {"value": None}
    bottom_nav_state = {"value": "阅读"}
    bottom_nav_segments: dict[str, ft.Container] = {}
    bottom_nav_indicator_ref: dict[str, ft.Container | None] = {"value": None}
    bottom_nav_indexes = {"阅读": 0, "本地": 1, "下载": 2, "设置": 3}
    root_tabs_ref: dict[str, ft.Tabs | None] = {"value": None}
    root_tabs_syncing = {"value": False}
    reading_tabs_ref: dict[str, ft.Tabs | None] = {"value": None}
    reading_tabs_syncing = {"value": False}
    reading_tab_pages: list[ft.Container] = []
    reading_content_host: ft.Container | None = None
    reading_speed_dial_state = {"open": False}
    section_indexes = {"阅读": 0, "本地": 1, "下载": 2, "设置": 3}
    bottom_nav_for_page = {"本地画廊": "本地", "下载": "下载", "设置": "设置"}

    def set_bottom_nav(value: str):
        bottom_nav_state["value"] = value
        indicator = bottom_nav_indicator_ref.get("value")
        if indicator is not None:
            indicator.left = bottom_nav_indexes.get(value, 0) * 71
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
        if tabs.selected_index != target_index:
            reading_tabs_syncing["value"] = True
            tabs.selected_index = target_index
            reading_tabs_syncing["value"] = False

    def set_reading_tab_content(label: str, control: ft.Control) -> None:
        """让阅读 Tab 持续持有自己的控件树，切换时不卸载和重绘。"""
        try:
            target_index = [PAGES[idx][0] for idx in READING_PAGE_INDEXES].index(label)
        except ValueError:
            return
        holder = reading_tab_pages[target_index]
        if holder.content is not control:
            holder.content = control

    def show_shared_reading_content() -> None:
        """让非持久阅读入口使用当前阅读 Tab 的共享内容宿主。"""
        tabs = reading_tabs_ref.get("value")
        selected_index = int(getattr(tabs, "selected_index", 0) or 0)
        if 0 <= selected_index < len(reading_tab_pages):
            reading_tab_pages[selected_index].content = content

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

    def set_reading_loading(source: str, loading: bool) -> None:
        """按请求来源维护阅读顶栏加载状态，避免并发请求提前关闭进度条。"""
        if loading:
            reading_loading_sources.add(source)
        else:
            reading_loading_sources.discard(source)
        indicator = reading_loading_indicator_ref.get("value")
        if indicator is not None:
            indicator.visible = bool(reading_loading_sources)
            request_update(page)

    page.fletviewer_set_reading_loading = set_reading_loading

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
                try:
                    for idx, item in enumerate(reversed(reading_speed_dial_items)):
                        time.sleep(0.03)
                        item.opacity = 1.0
                        item.offset = ft.Offset(0, 0)
                        request_update(page)
                except Exception as ex:
                    log_exception("界面动画", f"展开阅读工具失败：{ex}")

            page.run_thread(worker)
            return

        for idx, item in enumerate(reading_speed_dial_items):
            item.opacity = 0.0
            item.offset = ft.Offset(0, 0.24 + idx * 0.04)
        if update:
            page.update()

        def hide_worker():
            try:
                time.sleep(0.18)
                for item in reading_speed_dial_items:
                    item.visible = False
                request_update(page)
            except Exception as ex:
                log_exception("界面动画", f"收起阅读工具失败：{ex}")

        page.run_thread(hide_worker)

    def toggle_reading_speed_dial(e=None) -> None:
        set_reading_speed_dial_open(not reading_speed_dial_state["open"])

    def add_resize_handler(handler):
        if handler not in resize_handlers:
            resize_handlers.append(handler)

        def remove_handler():
            if handler in resize_handlers:
                resize_handlers.remove(handler)

        return remove_handler

    def on_page_resized(e):
        log_debug("导航", f"窗口尺寸变化 宽度={page.width} 高度={page.height} 处理器数={len(resize_handlers)}")
        for handler in list(resize_handlers):
            try:
                handler(e)
            except Exception as ex:
                handler_name = getattr(handler, "__qualname__", type(handler).__name__)
                log_exception("导航", f"窗口尺寸变化处理器执行失败 处理器={handler_name}：{ex}")

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
            try:
                time.sleep(0.02)
                container.opacity = 1
                container.scale = 1
                request_update(page)
            except Exception as ex:
                log_exception("界面动画", f"进入动画执行失败：{ex}")

        page.run_thread(worker)

    def play_exit_animation(container: ft.Container, after):
        container.opacity = 0
        container.scale = 0.96
        page.update()

        def worker():
            try:
                time.sleep(0.18)
                after()
            except Exception as ex:
                log_exception("界面动画", f"退出动画执行失败：{ex}")

        page.run_thread(worker)

    navigator = AppNavigator(page)
    navigator.install()
    page.fletviewer_navigator = navigator
    page.fletviewer_push_view = navigator.push_view
    page.fletviewer_pop_view = navigator.pop_view

    def invalidate_views(keys: list[str] | None = None, reason: str = ""):
        targets = keys or list(view_cache.keys())
        for key in targets:
            if key in view_cache:
                view_cache.pop(key, None)
                log_debug("导航", f"使缓存失效 键={key} 原因={reason}")
            if key.startswith("page:"):
                try:
                    page_index = int(key.split(":", 1)[1])
                    reading_index = READING_PAGE_INDEXES.index(page_index)
                except (ValueError, IndexError):
                    continue
                if reading_index < len(reading_tab_pages):
                    reading_tab_pages[reading_index].content = None

    page.fletviewer_invalidate_views = invalidate_views

    def open_gallery_detail(comic):
        log_debug("导航", f"打开画廊详情 {comic.id}")
        try:
            record_gallery_history(comic)
            view_cache.pop("page:6", None)
        except Exception as ex:
            log_exception("历史记录", f"记录画廊失败 {comic.id}：{ex}")
        detail_container = animated_scale_container(ft.Container(expand=True))
        route = navigator.next_route("gallery")
        parent_route = navigator.current_route()
        detail_actions: dict[str, object] = {}

        def go_back():
            log_debug("导航", f"关闭画廊详情 {comic.id}")
            navigator.navigate(parent_route)

        def register_refresh(action):
            detail_actions["refresh"] = action

        def refresh_detail(e=None):
            action = detail_actions.get("refresh")
            if callable(action):
                action()

        # TODO: 使用平台 URL launcher，在其他应用中打开 comic.id。
        def open_gallery_externally(e=None):
            return

        detail_container.content = gallery_detail_view(page, comic, go_back, register_refresh=register_refresh)
        navigator.push_view(
            ft.View(
                route=route,
                controls=[detail_container],
                padding=8,
                appbar=ft.AppBar(
                    title=ft.Text(""),
                    leading=ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回", on_click=lambda e: go_back()),
                    automatically_imply_leading=False,
                    actions=[
                        ft.PopupMenuButton(
                            icon=ft.Icons.MORE_VERT,
                            tooltip="更多",
                            items=[
                                ft.PopupMenuItem(content="刷新", icon=ft.Icons.REFRESH, on_click=refresh_detail),
                                ft.PopupMenuItem(content="在其他应用中打开", icon=ft.Icons.OPEN_IN_NEW, on_click=open_gallery_externally),
                            ],
                        )
                    ],
                ),
            ),
            parent_route=parent_route,
        )
        play_enter_animation(detail_container)

    page.fletviewer_open_gallery_detail = open_gallery_detail

    def open_image_viewer(items, initial_index=0, resolve_image_url=None):
        log_debug("导航", f"打开图像查看器 索引={initial_index} 数量={len(items)}")
        viewer_container: ft.Container | None = None
        route = navigator.next_route("viewer")
        parent_route = navigator.current_route()

        def go_back():
            log_debug("导航", "关闭图像查看器")
            navigator.navigate(parent_route)

        viewer_container = animated_scale_container(
            image_viewer_view(
                page,
                items,
                initial_index,
                go_back,
                resolve_image_url=resolve_image_url,
            ),
        )
        navigator.push_view(ft.View(route=route, controls=[viewer_container], padding=0), parent_route=parent_route)
        play_enter_animation(viewer_container)

    page.fletviewer_open_image_viewer = open_image_viewer

    def render(idx):
        if idx is None or idx < 0 or idx >= len(PAGES):
            log_debug("导航", f"忽略无效导航索引 索引={idx}")
            return
        started_at = time.perf_counter()
        label, subtitle, icon, view_fn = PAGES[idx]
        active_page_label["value"] = label
        search_hint = top_search_hint_ref["value"]
        if search_hint is not None:
            search_hint.value = {
                "收藏": "搜索收藏",
                "订阅": "搜索订阅",
            }.get(label, "搜索 E-Hentai")
        if label == "本地画廊":
            set_header(label, subtitle)
            set_header_actions([])
            activate_root_section("本地")
            log_debug("导航", f"切换至本地主分区 耗时={format_duration_ms((time.perf_counter() - started_at) * 1000)}")
            return
        if label == "设置":
            set_header(label, subtitle)
            set_header_actions([])
            activate_root_section("设置")
            log_debug("导航", f"切换至设置主分区 耗时={format_duration_ms((time.perf_counter() - started_at) * 1000)}")
            return
        if label == "下载":
            set_header(label, subtitle)
            set_header_actions([])
            activate_root_section("下载")
            log_debug("导航", f"切换至下载主分区 耗时={format_duration_ms((time.perf_counter() - started_at) * 1000)}")
            return
        set_header(label, subtitle)
        set_bottom_nav(bottom_nav_for_page.get(label, "阅读"))
        if label in READING_PAGE_LABELS:
            sync_reading_tab(label)
        activate_root_section("阅读", update=False, sync_bottom_nav=False)
        cache_key = f"page:{idx}"
        active_cache_key["value"] = cache_key
        set_header_actions(header_action_cache.get(cache_key, []))
        if label in READING_PAGE_LABELS:
            if cache_key not in view_cache:
                log_debug("导航", f"创建持久阅读视图 {label}")
                view_cache[cache_key] = view_fn(page) if view_fn is not None else ft.Container(expand=True)
            else:
                log_debug("导航", f"复用持久阅读视图 {label}")
            set_reading_tab_content(label, view_cache[cache_key])
            page.update()
            log_debug("导航", f"切换阅读视图 {label} 耗时={format_duration_ms((time.perf_counter() - started_at) * 1000)} 缓存键={cache_key}")
            return
        detach_content_for_navigation()
        show_shared_reading_content()
        if view_fn is None:
            if cache_key not in view_cache:
                log_debug("导航", f"创建占位视图 {label}")
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
                log_debug("导航", f"复用占位视图 {label}")
            set_content(view_cache[cache_key])
        else:
            if cache_key not in view_cache:
                log_debug("导航", f"创建视图 {label}")
                view_cache[cache_key] = view_fn(page)
            else:
                log_debug("导航", f"复用视图 {label}")
            set_content(view_cache[cache_key])
        page.update()
        log_debug("导航", f"切换视图 {label} 耗时={format_duration_ms((time.perf_counter() - started_at) * 1000)} 缓存键={cache_key}")

    def render_label(label: str):
        for idx, (page_label, _subtitle, _icon, _view_fn) in enumerate(PAGES):
            if page_label == label:
                render(idx)
                return
        log_debug("导航", f"忽略无效导航标签 标签={label}")

    page.fletviewer_render_label = render_label

    def global_search(client, keyword: str, page_url: str | None):
        return client.search(page_url=page_url) if page_url else client.search(keyword=keyword)

    def favorite_search(client, keyword: str, page_url: str | None):
        return client.get_favorites(page_url=page_url, keyword=keyword)

    def watched_search(client, keyword: str, page_url: str | None):
        result = client.get_watched(page_url=page_url)
        needle = keyword.casefold()
        return SearchResult(
            comics=[comic for comic in result.comics if needle in (comic.title or "").casefold()],
            next_url=result.next_url,
            prev_url=result.prev_url,
        )

    def current_search_context() -> SearchContext:
        label = active_page_label["value"]
        if label == "收藏":
            return SearchContext(
                key="favorites",
                title="搜索收藏",
                hint="标题、标签或作者",
                load=favorite_search,
                needs_login=True,
            )
        if label == "订阅":
            return SearchContext(
                key="subscriptions",
                title="搜索订阅",
                hint="过滤当前订阅页的标题",
                load=watched_search,
                needs_login=True,
                scope_note="订阅暂不支持服务端关键词搜索，将按服务端分页逐页过滤标题。",
            )
        return SearchContext(
            key="global",
            title="搜索 E-Hentai",
            hint="画廊、标签或作者",
            load=global_search,
        )

    def open_search_view(e=None):
        context = current_search_context()
        parent_route = navigator.current_route()
        navigator.push_view(
            ft.View(
                route=navigator.next_route(f"search-{context.key}"),
                controls=[ft.Container(content=search_view(page, context), padding=8, expand=True)],
                padding=0,
                appbar=ft.AppBar(
                    title=ft.Text(context.title),
                    leading=ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回", on_click=lambda event: navigator.pop_view()),
                    automatically_imply_leading=False,
                ),
            ),
            parent_route=parent_route,
        )

    top_search_hint = ft.Text("搜索画廊、标签、作者", color=ft.Colors.ON_SURFACE_VARIANT, expand=True)
    top_search_hint_ref["value"] = top_search_hint
    top_search_field = ft.Container(
        content=ft.Row([ft.Icon(ft.Icons.SEARCH), top_search_hint], spacing=12),
        height=44,
        expand=True,
        padding=ft.Padding(16, 0, 16, 0),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=999,
        ink=True,
        on_click=open_search_view,
    )

    def show_account_summary(e=None) -> None:
        """显示当前 EH 账户摘要；资产数据接口接入前使用占位值。"""
        logged_in = browser_session.login_status_level() in {"ok", "pending"}
        value = "待同步" if logged_in else "--"

        def metric(label: str, icon) -> ft.Control:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(icon, size=20, color=ft.Colors.PRIMARY),
                        ft.Text(value, size=16, weight=ft.FontWeight.BOLD),
                        ft.Text(label, size=11, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                width=112,
                padding=10,
                border_radius=14,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            )

        # TODO: 在 core provider 增加账户资产接口，填充 GP、Credit、HatH 和每周免费归档配额。
        dialog = ft.AlertDialog(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [ft.IconButton(ft.Icons.CLOSE, tooltip="关闭", on_click=lambda event: page.pop_dialog())],
                            alignment=ft.MainAxisAlignment.START,
                        ),
                        ft.Container(
                            content=ft.Icon(ft.Icons.PERSON, size=54, color=ft.Colors.ON_PRIMARY_CONTAINER),
                            width=96,
                            height=96,
                            border_radius=999,
                            bgcolor=ft.Colors.PRIMARY_CONTAINER,
                            alignment=ft.Alignment(0, 0),
                        ),
                        ft.Text(
                            browser_session.login_status_text(),
                            size=14,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Row(
                            [
                                metric("GP", ft.Icons.PAID),
                                metric("Credit", ft.Icons.ACCOUNT_BALANCE_WALLET),
                                metric("HatH", ft.Icons.DNS),
                                metric("每周免费归档", ft.Icons.INVENTORY_2),
                            ],
                            spacing=8,
                            run_spacing=8,
                            wrap=True,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        ft.Text(
                            "登录后可查看账户资产。" if not logged_in else "账户资产接口尚未接入。",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    spacing=14,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
                width=500,
            ),
            content_padding=ft.Padding(8, 8, 8, 20),
        )
        dialog.open = True
        page.show_dialog(dialog)

    def show_provider_selector(e=None) -> None:
        """显示阅读来源选择；未实现的来源暂时禁用。"""
        dialog = ft.AlertDialog(
            title=ft.Text("切换平台"),
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.ListTile(
                            leading=ft.Icon(ft.Icons.PUBLIC, color=ft.Colors.PRIMARY),
                            title=ft.Text("E-Hentai"),
                            subtitle=ft.Text("当前平台", color=ft.Colors.PRIMARY),
                            trailing=ft.Icon(ft.Icons.CHECK, color=ft.Colors.PRIMARY),
                            selected=True,
                        ),
                        ft.ListTile(leading=ft.Icon(ft.Icons.LOCK_OUTLINE), title=ft.Text("ExHentai"), subtitle=ft.Text("尚未实现"), disabled=True),
                        ft.ListTile(leading=ft.Icon(ft.Icons.IMAGE_SEARCH), title=ft.Text("Booru"), subtitle=ft.Text("尚未实现"), disabled=True),
                        ft.ListTile(leading=ft.Icon(ft.Icons.BRUSH), title=ft.Text("Pixiv"), subtitle=ft.Text("尚未实现"), disabled=True),
                    ],
                    spacing=0,
                    tight=True,
                ),
                width=320,
            ),
            actions=[ft.TextButton("关闭", on_click=lambda event: page.pop_dialog())],
        )
        dialog.open = True
        page.show_dialog(dialog)

    account_avatar_button = ft.IconButton(
        icon=ft.Icons.ACCOUNT_CIRCLE,
        tooltip="账户",
        on_click=show_account_summary,
    )
    reading_source_button = ft.IconButton(
        icon=ft.Icons.SWAP_HORIZ,
        tooltip="切换阅读来源",
        on_click=show_provider_selector,
    )

    reading_top_row = ft.Container(
        content=ft.Row(
            [
                top_search_field,
                header_actions,
                account_avatar_button,
                reading_source_button,
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
        opacity=1,
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
                    ft.Text(
                        label,
                        size=11,
                        weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                        color=color,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=1,
            ),
            width=68,
            height=54,
            border_radius=999,
            bgcolor=ft.Colors.TRANSPARENT,
            ink=True,
            on_click=lambda e: render_label(target),
            on_long_press=show_provider_selector if label == "设置" else None,
        )
        bottom_nav_segments[label] = segment
        return segment

    bottom_nav_indicator = ft.Container(
        width=68,
        height=54,
        left=0,
        top=0,
        bgcolor=ft.Colors.PRIMARY,
        border_radius=999,
        animate_position=ft.Animation(220, ft.AnimationCurve.EASE_OUT_CUBIC),
        ignore_interactions=True,
    )
    bottom_nav_indicator_ref["value"] = bottom_nav_indicator
    bottom_nav = ft.Container(
        content=ft.Stack(
            [
                bottom_nav_indicator,
                ft.Row(
                    [
                        bottom_nav_segment("阅读", ft.Icons.PUBLIC, "主页"),
                        bottom_nav_segment("本地", ft.Icons.FOLDER, "本地画廊"),
                        bottom_nav_segment("下载", ft.Icons.DOWNLOAD, "下载"),
                        bottom_nav_segment("设置", ft.Icons.SETTINGS, "设置"),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=3,
                    tight=True,
                ),
            ],
            width=281,
            height=54,
        ),
        padding=ft.Padding(4, 5, 4, 5),
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=999,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
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
            render_label("下载")
        elif selected_index == 3:
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

    reading_tab_pages[:] = [ft.Container(expand=True, padding=ft.Padding(0, 8, 0, 0)) for _idx in READING_PAGE_INDEXES]

    reading_tab_bar = ft.TabBar(
        tabs=[ft.Tab(label=PAGES[idx][0]) for idx in READING_PAGE_INDEXES],
        divider_height=0,
        divider_color=ft.Colors.TRANSPARENT,
        indicator_thickness=3,
        label_padding=ft.Padding(14, 0, 14, 0),
    )
    reading_loading_indicator = ft.ProgressBar(
        value=None,
        height=3,
        color=ft.Colors.PRIMARY,
        bgcolor=ft.Colors.TRANSPARENT,
        visible=False,
    )
    reading_loading_indicator_ref["value"] = reading_loading_indicator

    top_bar.content = ft.Stack(
        [
            ft.Column(
                [
                    reading_top_row,
                    reading_tab_bar,
                ],
                spacing=0,
                expand=True,
            ),
            ft.Container(
                content=reading_loading_indicator,
                left=0,
                right=0,
                bottom=0,
            ),
        ],
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
    downloads_section = ft.Stack(
        controls=[
            ft.Container(content=downloads_view(page), expand=True, padding=ft.Padding(8, 50, 8, 86)),
            section_top_bar("下载"),
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
            controls=[reading_section, local_section, downloads_section, settings_section],
            expand=True,
        ),
        length=4,
        selected_index=0,
        animation_duration=180,
        on_change=on_root_tabs_change,
        expand=True,
    )
    root_tabs_ref["value"] = root_tabs
    task_debug_overlay = TaskDebugOverlay(page)
    page.overlay.append(task_debug_overlay)

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

    navigator.set_root_view(ft.View(route="/", controls=[root], padding=0))
    render(0)
    navigator.rebuild(page.route or "/")

    def initialize_browser_session():
        try:
            browser_session.set_login_enabled(browser_session.login_enabled(), verify=True)
        except Exception as ex:
            log_exception("浏览器会话", f"初始化网络会话失败：{ex}")

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
