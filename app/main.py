import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platform_storage import resolve_storage
from app.storage import configure_storage
from core.storage_migration import migrate_legacy_storage

_ACTIVE_STORAGE = resolve_storage()
configure_storage(_ACTIVE_STORAGE.layout)
# 必须在任何 DB / download / image cache service 初始化前完成迁移。
_STORAGE_MIGRATION = migrate_legacy_storage(
    _ACTIVE_STORAGE.layout,
    log=lambda message: print(f"[存储迁移] {message}"),
)
if _STORAGE_MIGRATION.performed:
    print(f"[存储迁移] 完成，移动 {_STORAGE_MIGRATION.moved and len(_STORAGE_MIGRATION.moved) or 0} 项")
elif _STORAGE_MIGRATION.notes:
    print(f"[存储迁移] 跳过：{'; '.join(_STORAGE_MIGRATION.notes)}")

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
from app.image_results import image_result_pump
from app.navigation import AppNavigator
from app.notifications import Notification, notifier
from app.storage import (
    load_app_config,
    save_app_config,
    should_enable_debug_panel,
    should_show_task_debug_overlay,
    should_use_linux_builtin_title_bar,
)
from app.theme import apply_app_theme, refresh_adaptive_theme_on_brightness_change
from app.ui_update import request_update
from app.views.downloads import create_view as downloads_view
from app.views.debug import create_view as debug_view
from app.views.file_manager import create_view as file_manager_view
from app.views.home import create_view as home_view
from app.views import booru_pages, pixiv_pages
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

BASE_PAGES = [
    ("主页", "最新画廊", ft.Icons.HOME, home_view),
    ("订阅", "关注的标签画廊（需登录）", ft.Icons.SUBSCRIPTIONS, subscriptions_view),
    ("热门", "近期热门画廊", ft.Icons.LOCAL_FIRE_DEPARTMENT, popular_view),
    ("排行榜", "EH 排行榜", ft.Icons.LEADERBOARD, leaderboard_view),
    ("收藏", "收藏夹画廊（需登录）", ft.Icons.BOOKMARK, favorites_view),
    ("本地画廊", "已下载 Archive", ft.Icons.FOLDER, local_galleries_view),
    ("历史", "浏览历史", ft.Icons.HISTORY, history_view),
    ("下载", "下载任务", ft.Icons.DOWNLOAD, downloads_view),
    ("设置", "应用设置", ft.Icons.SETTINGS, settings_view),
]
EXTRA_PAGE_DEFS = {
    "调试": ("调试", "小图任务", ft.Icons.BUG_REPORT, debug_view),
}


def _enabled_extra_sections() -> list[str]:
    enabled: list[str] = []
    if should_enable_debug_panel():
        enabled.append("调试")
    return enabled


def _build_pages(extra_sections: list[str], *, provider: str = "ehentai") -> list[tuple[str, str, object, object]]:
    if provider == "pixiv":
        pages = list(_pixiv_reading_pages())
        # Keep shared app sections.
        pages.extend([
            ("本地画廊", "已下载 Archive", ft.Icons.FOLDER, local_galleries_view),
            ("下载", "下载任务", ft.Icons.DOWNLOAD, downloads_view),
            ("设置", "应用设置", ft.Icons.SETTINGS, settings_view),
        ])
    elif provider == "booru":
        pages = list(_booru_reading_pages())
        pages.extend([
            ("本地画廊", "已下载 Archive", ft.Icons.FOLDER, local_galleries_view),
            ("下载", "下载任务", ft.Icons.DOWNLOAD, downloads_view),
            ("设置", "应用设置", ft.Icons.SETTINGS, settings_view),
        ])
    else:
        pages = list(BASE_PAGES)
    # Insert extras between 下载 and 设置.
    insert_at = next(i for i, item in enumerate(pages) if item[0] == "设置")
    for key in extra_sections:
        pages.insert(insert_at, EXTRA_PAGE_DEFS[key])
        insert_at += 1
    return pages


def _pixiv_reading_pages():
    return [
        ("推荐", "Pixiv 推荐", ft.Icons.HOME, pixiv_pages.create_home_view),
        ("关注", "关注画师更新", ft.Icons.FAVORITE, pixiv_pages.create_following_view),
        ("排行", "Pixiv 排行榜", ft.Icons.LEADERBOARD, pixiv_pages.create_ranking_view),
        ("搜索", "Pixiv 搜索", ft.Icons.SEARCH, pixiv_pages.create_search_view),
    ]


def _eh_reading_labels():
    return {"主页", "订阅", "热门", "排行榜", "收藏", "历史"}


def _pixiv_reading_labels():
    return {"推荐", "关注", "排行", "搜索"}


def _booru_reading_pages():
    return [
        ("Safebooru", "Safebooru 标签搜索", ft.Icons.IMAGE_SEARCH, booru_pages.create_safebooru_view),
        ("Gelbooru", "Gelbooru 标签搜索", ft.Icons.IMAGE_SEARCH, booru_pages.create_gelbooru_view),
        ("Danbooru", "Danbooru 标签搜索", ft.Icons.IMAGE_SEARCH, booru_pages.create_danbooru_view),
    ]


def _booru_reading_labels():
    return {"Safebooru", "Gelbooru", "Danbooru"}


def _default_reading_label(provider: str) -> str:
    if provider == "pixiv":
        return "推荐"
    if provider == "booru":
        return "Safebooru"
    return "主页"

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
    result_pump = image_result_pump(page)
    page.fletviewer_prioritize_navigation = result_pump.prioritize_navigation
    current_content: dict[str, ft.Control | None] = {"value": None}
    shell_host: dict[str, ft.Container | None] = {"value": None}
    resize_handlers = []
    header_actions = ft.Row(spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    header_action_cache: dict[str, list[ft.Control]] = {}
    reading_refresh_action_cache: dict[str, object] = {}
    reading_loading_sources: set[str] = set()
    reading_loading_indicator_ref: dict[str, ft.ProgressBar | None] = {"value": None}
    active_cache_key = {"value": ""}
    app_config = load_app_config()
    saved_provider = str(app_config.get("active_provider") or "ehentai")
    saved_booru_provider = str(app_config.get("active_booru_provider") or "gelbooru")
    if saved_provider not in {"ehentai", "pixiv", "booru"}:
        saved_provider = "ehentai"
    if saved_booru_provider not in {"safebooru", "gelbooru", "danbooru"}:
        saved_booru_provider = "gelbooru"
    active_page_label = {"value": _default_reading_label(saved_provider)}
    top_search_hint_ref: dict[str, ft.TextField | None] = {"value": None}
    page.fletviewer_booru_search_actions = {}
    nav_state = {
        "provider": saved_provider,
        "booru_provider": saved_booru_provider,
        "extra_sections": _enabled_extra_sections(),
        "pages": [],
        "reading_labels": set(_eh_reading_labels()),
        "reading_indexes": [],
        "root_section_order": [],
        "section_indexes": {},
        "bottom_nav_indexes": {},
    }

    def refresh_nav_maps() -> None:
        extras = list(nav_state["extra_sections"])
        provider = nav_state.get("provider") or "ehentai"
        pages = _build_pages(extras, provider=provider)
        if provider == "pixiv":
            labels = _pixiv_reading_labels()
        elif provider == "booru":
            labels = _booru_reading_labels()
        else:
            labels = _eh_reading_labels()
        order = ["阅读", "本地", "下载", *extras, "设置"]
        nav_state["pages"] = pages
        nav_state["reading_labels"] = set(labels)
        nav_state["reading_indexes"] = [
            idx for idx, (label, _subtitle, _icon, _view_fn) in enumerate(pages) if label in labels
        ]
        nav_state["root_section_order"] = order
        nav_state["section_indexes"] = {label: idx for idx, label in enumerate(order)}
        nav_state["bottom_nav_indexes"] = {label: idx for idx, label in enumerate(order)}

    refresh_nav_maps()
    # Compatibility aliases used by existing closures; rebound by rebuild.
    PAGES = nav_state["pages"]
    READING_PAGE_INDEXES = nav_state["reading_indexes"]
    root_section_order = nav_state["root_section_order"]
    section_indexes = nav_state["section_indexes"]
    bottom_nav_indexes = nav_state["bottom_nav_indexes"]
    bottom_nav_state = {"value": "阅读"}
    bottom_nav_visibility_action = {"value": None}
    bottom_nav_segments: dict[str, ft.Container] = {}
    bottom_nav_indicator_ref: dict[str, ft.Container | None] = {"value": None}
    root_tabs_ref: dict[str, ft.Tabs | None] = {"value": None}
    root_tabs_syncing = {"value": False}
    reading_tabs_ref: dict[str, ft.Tabs | None] = {"value": None}
    reading_tabs_syncing = {"value": False}
    reading_tab_pages: list[ft.Container] = []
    reading_content_host: ft.Container | None = None
    reading_speed_dial_state = {"open": False}
    bottom_nav_for_page = {
        "本地画廊": "本地",
        "下载": "下载",
        "文件": "本地",
        "调试": "调试",
        "设置": "设置",
    }
    bottom_nav_metrics = {"count": 4, "item_width": 68, "spacing": 3, "stride": 71}

    def bottom_nav_layout(count: int) -> tuple[int, int, int]:
        """按钮多时收缩宽度和间距，避免底栏溢出。"""
        count = max(1, int(count))
        if count <= 4:
            item_width, spacing = 68, 3
        elif count == 5:
            item_width, spacing = 58, 2
        else:
            item_width, spacing = 50, 1
        stride = item_width + spacing
        bottom_nav_metrics.update(count=count, item_width=item_width, spacing=spacing, stride=stride)
        return item_width, spacing, stride

    def set_bottom_nav(value: str):
        show_bottom_nav = bottom_nav_visibility_action.get("value")
        if callable(show_bottom_nav):
            show_bottom_nav(True, update=False)
        bottom_nav_state["value"] = value
        indicator = bottom_nav_indicator_ref.get("value")
        if indicator is not None:
            indicator.left = nav_state["bottom_nav_indexes"].get(value, 0) * bottom_nav_metrics["stride"]
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
            target_index = nav_state["section_indexes"].get(value, 0)
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
        pages = nav_state["pages"]
        reading_indexes = nav_state["reading_indexes"]
        try:
            target_index = [pages[idx][0] for idx in reading_indexes].index(label)
        except ValueError:
            return
        if tabs.selected_index != target_index:
            reading_tabs_syncing["value"] = True
            tabs.selected_index = target_index
            reading_tabs_syncing["value"] = False

    def set_reading_tab_content(label: str, control: ft.Control) -> None:
        """让阅读 Tab 持续持有自己的控件树，切换时不卸载和重绘。"""
        pages = nav_state["pages"]
        reading_indexes = nav_state["reading_indexes"]
        try:
            target_index = [pages[idx][0] for idx in reading_indexes].index(label)
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
        result_pump.prioritize_navigation()
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
                    reading_index = nav_state["reading_indexes"].index(page_index)
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
        pages = nav_state["pages"]
        if idx is None or idx < 0 or idx >= len(pages):
            log_debug("导航", f"忽略无效导航索引 索引={idx}")
            return
        started_at = time.perf_counter()
        result_pump.prioritize_navigation()
        label, subtitle, icon, view_fn = pages[idx]
        active_page_label["value"] = label
        search_field = top_search_hint_ref["value"]
        if search_field is not None:
            search_field.hint_text = {
                "收藏": "搜索收藏",
                "订阅": "搜索订阅",
                "Safebooru": "搜索 Safebooru 标签",
                "Gelbooru": "搜索 Gelbooru 标签",
                "Danbooru": "搜索 Danbooru 标签",
            }.get(label, "搜索 E-Hentai")
        if label == "本地画廊":
            set_header(label, subtitle)
            set_header_actions([])
            if local_tabs_ref.get("value") is not None:
                local_tabs_ref["value"].selected_index = 0
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
        if label == "文件":
            set_header("本地", "四域存储与本地画廊")
            set_header_actions([])
            if local_tabs_ref.get("value") is not None:
                local_tabs_ref["value"].selected_index = 1
            activate_root_section("本地")
            return
        if label == "调试" and label in nav_state["section_indexes"]:
            set_header(label, subtitle)
            set_header_actions([])
            activate_root_section(label)
            log_debug("导航", f"切换至附加主分区 {label} 耗时={format_duration_ms((time.perf_counter() - started_at) * 1000)}")
            return
        set_header(label, subtitle)
        set_bottom_nav(bottom_nav_for_page.get(label, "阅读"))
        if label in nav_state["reading_labels"]:
            sync_reading_tab(label)
        activate_root_section("阅读", update=False, sync_bottom_nav=False)
        cache_key = f"page:{idx}"
        active_cache_key["value"] = cache_key
        set_header_actions(header_action_cache.get(cache_key, []))
        if label in nav_state["reading_labels"]:
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
        if label == "文件":
            set_header("本地", "四域存储与本地画廊")
            set_header_actions([])
            if local_tabs_ref.get("value") is not None:
                local_tabs_ref["value"].selected_index = 1
            activate_root_section("本地")
            return
        for idx, (page_label, _subtitle, _icon, _view_fn) in enumerate(nav_state["pages"]):
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

    def submit_top_search(e=None):
        if nav_state.get("provider") == "booru":
            action = page.fletviewer_booru_search_actions.get(active_page_label["value"])
            if callable(action):
                action(top_search_field.value or "")
            return
        open_search_view(e)

    top_search_field = ft.TextField(
        hint_text="搜索画廊、标签、作者",
        prefix_icon=ft.Icons.SEARCH,
        suffix=ft.IconButton(ft.Icons.ARROW_FORWARD, tooltip="搜索", on_click=submit_top_search),
        expand=True,
        dense=True,
        border_radius=999,
        on_submit=submit_top_search,
    )
    top_search_hint_ref["value"] = top_search_field

    active_provider = {"value": "ehentai"}

    def provider_label(provider: str | None = None) -> str:
        key = provider or active_provider["value"]
        return {
            "ehentai": "E-Hentai",
            "pixiv": "Pixiv",
            "exhentai": "ExHentai",
            "booru": "Booru",
        }.get(key, key)

    def apply_provider(provider: str, *, update: bool = True) -> None:
        """切换阅读 Provider，并刷新阅读区页面骨架。"""
        if provider not in {"ehentai", "pixiv", "booru"}:
            return
        if nav_state.get("provider") == provider and active_provider["value"] == provider and update:
            try:
                page.pop_dialog()
            except Exception:
                pass
            return

        active_provider["value"] = provider
        nav_state["provider"] = provider
        refresh_nav_maps()

        # 清理旧阅读页缓存
        for key in list(view_cache.keys()):
            if key.startswith("page:"):
                view_cache.pop(key, None)

        # 重建阅读 Tab 标题与页面槽位
        reading_indexes = nav_state["reading_indexes"]
        pages = nav_state["pages"]
        reading_tab_pages[:] = [
            ft.Container(expand=True, padding=ft.Padding(0, 8, 0, 0)) for _idx in reading_indexes
        ]
        reading_tab_bar.tabs = [ft.Tab(label=pages[idx][0]) for idx in reading_indexes]
        tabs = reading_tabs_ref.get("value")
        if tabs is not None:
            tabs.length = len(reading_indexes)
            tabs.selected_index = 0
            # TabBarView 需要同步控件数量
            if isinstance(tabs.content, ft.Stack) and tabs.content.controls:
                for control in tabs.content.controls:
                    if isinstance(control, ft.TabBarView):
                        control.controls = reading_tab_pages
                        break

        if top_search_hint_ref.get("value") is not None:
            top_search_hint_ref["value"].hint_text = (
                "搜索 Pixiv（即将支持）"
                if provider == "pixiv"
                else "搜索 Booru 标签（即将支持）"
                if provider == "booru"
                else "搜索 E-Hentai"
            )
        account_avatar_button.tooltip = f"账户与平台 · 当前 {provider_label(provider)}"

        try:
            page.pop_dialog()
        except Exception:
            pass
        render_label(_default_reading_label(provider))
        if update:
            request_update(page)

    def show_account_summary(e=None) -> None:
        """账户摘要 + Provider 切换入口。"""
        logged_in = browser_session.login_status_level() in {"ok", "pending"}
        value = "待同步" if logged_in else "--"
        current = active_provider["value"]

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

        def provider_tile(key: str, title: str, subtitle: str, icon, *, enabled: bool = True) -> ft.Control:
            selected = current == key
            return ft.ListTile(
                leading=ft.Icon(icon, color=ft.Colors.PRIMARY if selected else None),
                title=ft.Text(title),
                subtitle=ft.Text(
                    "当前平台" if selected else subtitle,
                    color=ft.Colors.PRIMARY if selected else ft.Colors.ON_SURFACE_VARIANT,
                ),
                trailing=ft.Icon(ft.Icons.CHECK, color=ft.Colors.PRIMARY) if selected else None,
                selected=selected,
                disabled=not enabled,
                on_click=(lambda e, provider=key: apply_provider(provider)) if enabled else None,
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
                        ft.Text(f"当前平台：{provider_label(current)}", size=13, weight=ft.FontWeight.W_600),
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
                        ft.Divider(),
                        ft.Text("切换平台", size=14, weight=ft.FontWeight.W_600),
                        provider_tile("ehentai", "E-Hentai", "EH 画廊浏览", ft.Icons.PUBLIC, enabled=True),
                        provider_tile("pixiv", "Pixiv", "主页骨架已就绪", ft.Icons.BRUSH, enabled=True),
                        provider_tile("exhentai", "ExHentai", "尚未实现", ft.Icons.LOCK_OUTLINE, enabled=False),
                        provider_tile("booru", "Booru", "多站点 Provider 骨架", ft.Icons.IMAGE_SEARCH, enabled=True),
                    ],
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=500,
                height=560,
            ),
            content_padding=ft.Padding(8, 8, 8, 20),
        )
        dialog.open = True
        page.show_dialog(dialog)

    account_avatar_button = ft.IconButton(
        icon=ft.Icons.ACCOUNT_CIRCLE,
        tooltip="账户与平台 · 当前 E-Hentai",
        on_click=show_account_summary,
    )

    reading_top_row = ft.Container(
        content=ft.Row(
            [
                top_search_field,
                header_actions,
                account_avatar_button,
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
        item_width = bottom_nav_metrics["item_width"]
        segment = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, size=18 if item_width < 56 else 20, color=color),
                    ft.Text(
                        label,
                        size=10 if item_width < 56 else 11,
                        weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                        color=color,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=1,
            ),
            width=item_width,
            height=54,
            border_radius=999,
            bgcolor=ft.Colors.TRANSPARENT,
            ink=True,
            on_click=lambda e: render_label(
                _default_reading_label(str(nav_state.get("provider") or "ehentai"))
                if target == "阅读"
                else target
            ),
            on_long_press=None,
        )
        bottom_nav_segments[label] = segment
        return segment

    bottom_nav_indicator = ft.Container(
        width=bottom_nav_metrics["item_width"],
        height=54,
        left=0,
        top=0,
        bgcolor=ft.Colors.PRIMARY,
        border_radius=999,
        animate_position=ft.Animation(220, ft.AnimationCurve.EASE_OUT_CUBIC),
        ignore_interactions=True,
    )
    bottom_nav_indicator_ref["value"] = bottom_nav_indicator
    planned_count = 4 + len(nav_state["extra_sections"])
    item_width, spacing, stride = bottom_nav_layout(planned_count)
    bottom_nav_indicator.width = item_width
    bottom_nav_items = [
        bottom_nav_segment("阅读", ft.Icons.PUBLIC, "阅读"),
        bottom_nav_segment("本地", ft.Icons.FOLDER, "本地画廊"),
        bottom_nav_segment("下载", ft.Icons.DOWNLOAD, "下载"),
    ]
    if "调试" in nav_state["extra_sections"]:
        bottom_nav_items.append(bottom_nav_segment("调试", ft.Icons.BUG_REPORT, "调试"))
    bottom_nav_items.append(bottom_nav_segment("设置", ft.Icons.SETTINGS, "设置"))
    bottom_nav_width = max(1, len(bottom_nav_items)) * stride - spacing
    bottom_nav = ft.Container(
        content=ft.Stack(
            [
                bottom_nav_indicator,
                ft.Row(
                    bottom_nav_items,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=spacing,
                    tight=True,
                ),
            ],
            width=bottom_nav_width,
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
    bottom_nav_host = ft.Container(
        content=bottom_nav,
        left=0,
        right=0,
        bottom=12,
        alignment=ft.Alignment(0, 1),
        offset=ft.Offset(0, 0),
        opacity=1,
        animate_offset=ft.Animation(180, ft.AnimationCurve.EASE_OUT_CUBIC),
        animate_opacity=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
    )
    bottom_nav_visible = {"value": True}

    def set_bottom_nav_visible(visible: bool, *, update: bool = True) -> None:
        visible = bool(visible)
        if bottom_nav_visible["value"] == visible:
            return
        bottom_nav_visible["value"] = visible
        bottom_nav_host.offset = ft.Offset(0, 0) if visible else ft.Offset(0, 1.45)
        bottom_nav_host.opacity = 1 if visible else 0
        bottom_nav_host.ignore_interactions = not visible
        if update:
            request_update(page)

    bottom_nav_visibility_action["value"] = set_bottom_nav_visible
    page.fletviewer_set_bottom_nav_visible = set_bottom_nav_visible

    def on_root_tabs_change(e):
        if root_tabs_syncing["value"]:
            return
        selected_index = int(getattr(e.control, "selected_index", 0) or 0)
        order = nav_state["root_section_order"]
        if selected_index < 0 or selected_index >= len(order):
            render_label(_default_reading_label(str(nav_state.get("provider") or "ehentai")))
            return
        section = order[selected_index]
        if section == "本地":
            render_label("本地画廊")
        elif section == "下载":
            render_label("下载")
        elif section == "调试":
            render_label("调试")
        elif section == "设置":
            render_label("设置")
        else:
            render_label(_default_reading_label(str(nav_state.get("provider") or "ehentai")))

    def on_reading_tabs_change(e):
        if reading_tabs_syncing["value"]:
            return
        selected_index = int(getattr(e.control, "selected_index", 0) or 0)
        reading_indexes = nav_state["reading_indexes"]
        if selected_index < 0 or selected_index >= len(reading_indexes):
            return
        render(reading_indexes[selected_index])

    reading_tab_pages[:] = [ft.Container(expand=True, padding=ft.Padding(0, 8, 0, 0)) for _idx in nav_state["reading_indexes"]]

    reading_tab_bar = ft.TabBar(
        tabs=[ft.Tab(label=nav_state["pages"][idx][0]) for idx in nav_state["reading_indexes"]],
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
        length=len(nav_state["reading_indexes"]),
        selected_index=0,
        animation_duration=160,
        on_change=on_reading_tabs_change,
        expand=True,
    )
    reading_tabs_ref["value"] = reading_tabs
    reading_content_host = ft.Container(content=reading_tabs, expand=True)
    reading_section = reading_content_host
    local_tabs_ref = {"value": None}
    local_tabs = ft.Tabs(
        content=ft.Column(
            [
                ft.TabBar(tabs=[ft.Tab(label="画廊"), ft.Tab(label="文件")]),
                ft.TabBarView(
                    controls=[
                        ft.Container(content=local_galleries_view(page), expand=True, padding=ft.Padding(8, 8, 8, 86)),
                        ft.Container(content=file_manager_view(page), expand=True, padding=ft.Padding(8, 8, 8, 86)),
                    ],
                    expand=True,
                ),
            ],
            spacing=0,
            expand=True,
        ),
        length=2,
        selected_index=0,
        expand=True,
    )
    local_tabs_ref["value"] = local_tabs
    local_section = ft.Stack(
        controls=[
            ft.Container(content=local_tabs, expand=True, padding=ft.Padding(8, 50, 8, 0)),
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
    extra_sections_map = {
        "调试": ft.Stack(
            controls=[
                ft.Container(content=debug_view(page), expand=True, padding=ft.Padding(8, 50, 8, 86)),
                section_top_bar("调试"),
            ],
            expand=True,
        ),
    }
    settings_section = ft.Stack(
        controls=[
            ft.Container(content=settings_view(page), expand=True, padding=ft.Padding(8, 50, 8, 86)),
            section_top_bar("设置"),
        ],
        expand=True,
    )
    root_tab_controls = [reading_section, local_section, downloads_section]
    for key in nav_state["extra_sections"]:
        root_tab_controls.append(extra_sections_map[key])
    root_tab_controls.append(settings_section)
    root_tabs = ft.Tabs(
        content=ft.TabBarView(
            controls=root_tab_controls,
            expand=True,
        ),
        length=len(root_tab_controls),
        selected_index=0,
        animation_duration=180,
        on_change=on_root_tabs_change,
        expand=True,
    )
    root_tabs_ref["value"] = root_tabs
    root_tabs_row_ref = {"value": None}

    def rebuild_extra_sections(*, update: bool = True) -> None:
        """根据设置立即重建底栏附加面板和根分区。"""
        nonlocal PAGES, READING_PAGE_INDEXES, root_section_order, section_indexes, bottom_nav_indexes, root_tabs
        previous = bottom_nav_state.get("value") or "阅读"
        nav_state["extra_sections"] = _enabled_extra_sections()
        refresh_nav_maps()
        PAGES = nav_state["pages"]
        READING_PAGE_INDEXES = nav_state["reading_indexes"]
        root_section_order = nav_state["root_section_order"]
        section_indexes = nav_state["section_indexes"]
        bottom_nav_indexes = nav_state["bottom_nav_indexes"]

        bottom_nav_segments.clear()
        planned = 4 + len(nav_state["extra_sections"])
        item_width, spacing, stride = bottom_nav_layout(planned)
        bottom_nav_indicator.width = item_width
        items = [
            bottom_nav_segment("阅读", ft.Icons.PUBLIC, "阅读"),
            bottom_nav_segment("本地", ft.Icons.FOLDER, "本地画廊"),
            bottom_nav_segment("下载", ft.Icons.DOWNLOAD, "下载"),
        ]
        if "调试" in nav_state["extra_sections"]:
            items.append(bottom_nav_segment("调试", ft.Icons.BUG_REPORT, "调试"))
        items.append(bottom_nav_segment("设置", ft.Icons.SETTINGS, "设置"))
        width = max(1, len(items)) * stride - spacing
        bottom_nav.content = ft.Stack(
            [
                bottom_nav_indicator,
                ft.Row(items, alignment=ft.MainAxisAlignment.CENTER, spacing=spacing, tight=True),
            ],
            width=width,
            height=54,
        )

        controls = [reading_section, local_section, downloads_section]
        for key in nav_state["extra_sections"]:
            controls.append(extra_sections_map[key])
        controls.append(settings_section)
        selected = previous if previous in nav_state["section_indexes"] else "设置"
        root_tabs = ft.Tabs(
            content=ft.TabBarView(controls=controls, expand=True),
            length=len(controls),
            selected_index=nav_state["section_indexes"].get(selected, 0),
            animation_duration=180,
            on_change=on_root_tabs_change,
            expand=True,
        )
        root_tabs_ref["value"] = root_tabs
        row = root_tabs_row_ref.get("value")
        if row is not None:
            row.controls = [root_tabs]
        if previous not in nav_state["section_indexes"]:
            bottom_nav_state["value"] = "设置"
        set_bottom_nav(bottom_nav_state["value"])
        if update:
            request_update(page)

    page.fletviewer_rebuild_extra_sections = rebuild_extra_sections

    def open_task_debug_view():
        parent_route = navigator.current_route()
        navigator.push_view(
            ft.View(
                route=navigator.next_route("debug-tasks"),
                controls=[ft.Container(content=debug_view(page), padding=8, expand=True)],
                padding=0,
                appbar=ft.AppBar(
                    title=ft.Text("任务调试"),
                    leading=ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回", on_click=lambda e: navigator.pop_view()),
                    automatically_imply_leading=False,
                ),
            ),
            parent_route=parent_route,
        )

    page.fletviewer_open_task_debug = open_task_debug_view
    task_debug_overlay = TaskDebugOverlay(page)

    def set_task_debug_overlay_visible(visible: bool, *, update: bool = True) -> None:
        mounted = task_debug_overlay in page.overlay
        if visible and not mounted:
            page.overlay.append(task_debug_overlay)
        elif not visible and mounted:
            page.overlay.remove(task_debug_overlay)
        if update and visible != mounted:
            request_update(page)

    page.fletviewer_set_task_debug_overlay_visible = set_task_debug_overlay_visible
    set_task_debug_overlay_visible(should_show_task_debug_overlay(), update=False)

    root_tabs_row = ft.Row([root_tabs], expand=True)
    root_tabs_row_ref["value"] = root_tabs_row
    body = ft.Stack(
        controls=[
            root_tabs_row,
            bottom_nav_host,
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
    initial_label = (
        saved_booru_provider.capitalize()
        if saved_provider == "booru"
        else _default_reading_label(saved_provider)
    )
    render_label(initial_label)
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
