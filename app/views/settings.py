import json

import flet as ft

from app.browser_session import browser_session
from app.gallery_cache import clear_gallery_cache
from app.gallery_type_colors import GALLERY_TYPE_COLORS, GALLERY_TYPE_LABELS, gallery_type_foreground
from app.image_cache import clear_image_cache
from app.storage import (
    CACHE_DB_PATH,
    CACHE_FILES_DIR,
    CONFIG_PATH,
    get_image_viewer_mode,
    get_gallery_grid_columns,
    get_gallery_view_mode,
    get_theme_color,
    get_theme_mode,
    load_app_config,
    load_eh_config,
    save_app_config,
    save_eh_config,
)
from app.toast import show_toast

COOKIE_FIELDS = [
    ("ipb_member_id", "ipb_member_id", "EH 会员 ID", True),
    ("ipb_pass_hash", "ipb_pass_hash", "ipb_pass_hash", True),
    ("igneous", "igneous", "igneous（exhentai 可选）", False),
    ("star", "star", "star（可选）", False),
]

GALLERY_VIEW_CACHE_KEYS = ["page:0", "page:1", "page:2", "page:3", "page:4", "page:5", "search"]


def _platform_label(page: ft.Page) -> str:
    """返回设置页展示的当前运行平台名称。"""
    if page.web:
        return "Web"
    value = str(getattr(page, "platform", "") or "").lower()
    if "windows" in value:
        return "Windows"
    if "linux" in value:
        return "Linux"
    if "android" in value:
        return "Android"
    if "mac" in value or "darwin" in value:
        return "macOS"
    return value or "未知"


def _invalidate_gallery_views(page: ft.Page, reason: str) -> None:
    """让受设置影响的页面缓存失效。"""
    invalidate = getattr(page, "fletviewer_invalidate_views", None)
    if callable(invalidate):
        invalidate(GALLERY_VIEW_CACHE_KEYS, reason=reason)


def create_view(page: ft.Page) -> ft.Control:
    """创建设置页，包含账户、显示、Linux 窗口和存储选项卡。"""
    cfg = load_eh_config()
    app_cfg = load_app_config()

    fields = {}
    for key, _name, label, required in COOKIE_FIELDS:
        fields[key] = ft.TextField(
            label=label,
            value=cfg.get(key, ""),
            width=450,
            password=(key in ("ipb_pass_hash", "igneous")),
            can_reveal_password=(key in ("ipb_pass_hash", "igneous")),
            dense=True,
        )

    status = ft.Text("", size=14)
    display_status = ft.Text("", size=14)
    debug_status = ft.Text("", size=14)
    linux_window_status = ft.Text("", size=14)
    login_status = ft.Text(browser_session.login_status_text(), size=14, color=ft.Colors.ON_SURFACE_VARIANT)
    login_status_lamp = ft.Container(width=10, height=10, border_radius=999)
    enable_login_switch = ft.Switch(
        label="启用自动登录",
        value=bool(app_cfg.get("enable_login", True)),
    )
    load_images_switch = ft.Switch(
        label="是否加载图像",
        value=bool(app_cfg.get("load_images", True)),
    )
    show_error_toasts_switch = ft.Switch(
        label="显示错误提示",
        value=bool(app_cfg.get("show_error_toasts", True)),
    )
    render_cards_switch = ft.Switch(
        label="使用JSON而非解析画廊",
        value=not bool(app_cfg.get("render_gallery_cards", True)),
    )
    debug_cover_dimensions_switch = ft.Switch(
        label="在封面左上角显示尺寸",
        value=bool(app_cfg.get("debug_show_cover_dimensions", False)),
    )
    debug_force_favorite_switch = ft.Switch(
        label="始终显示已收藏",
        value=bool(app_cfg.get("debug_force_gallery_favorite", False)),
    )
    debug_force_downloaded_switch = ft.Switch(
        label="始终显示已下载",
        value=bool(app_cfg.get("debug_force_gallery_downloaded", False)),
    )
    debug_force_update_switch = ft.Switch(
        label="始终显示可更新",
        value=bool(app_cfg.get("debug_force_gallery_update", False)),
    )
    theme_mode_segments = ft.SegmentedButton(
        segments=[
            ft.Segment(value="system", label="跟随系统", icon=ft.Icons.BRIGHTNESS_AUTO),
            ft.Segment(value="light", label="浅色", icon=ft.Icons.LIGHT_MODE),
            ft.Segment(value="dark", label="深色", icon=ft.Icons.DARK_MODE),
        ],
        selected=[get_theme_mode()],
        show_selected_icon=False,
        allow_empty_selection=False,
    )
    theme_color_dropdown = ft.Dropdown(
        label="Material 3 色彩",
        value=get_theme_color(),
        options=[
            ft.DropdownOption(key="adaptive", text="自适应"),
            ft.DropdownOption(key="teal", text="青绿"),
            ft.DropdownOption(key="blue", text="蓝色"),
            ft.DropdownOption(key="green", text="绿色"),
            ft.DropdownOption(key="rose", text="玫红"),
            ft.DropdownOption(key="amber", text="琥珀"),
            ft.DropdownOption(key="violet", text="紫色"),
        ],
        width=220,
        dense=True,
    )
    viewer_mode_dropdown = ft.Dropdown(
        label="默认图像查看器",
        value=get_image_viewer_mode(),
        options=[
            ft.DropdownOption(key="paged", text="单页左右切换"),
            ft.DropdownOption(key="vertical", text="垂直连续浏览"),
        ],
        width=260,
        dense=True,
    )
    gallery_columns_value = ft.Text(f"{get_gallery_grid_columns()} 列", size=14, weight=ft.FontWeight.W_500)
    gallery_view_mode_segments = ft.SegmentedButton(
        segments=[
            ft.Segment(value="card", label="卡片", icon=ft.Icons.GRID_VIEW),
            ft.Segment(value="list", label="列表", icon=ft.Icons.VIEW_LIST),
            ft.Segment(value="masonry", label="瀑布流", icon=ft.Icons.VIEW_QUILT),
        ],
        selected=[get_gallery_view_mode()],
        show_selected_icon=False,
        allow_empty_selection=False,
    )
    gallery_columns_slider = ft.Slider(
        value=get_gallery_grid_columns(),
        min=2,
        max=10,
        divisions=8,
        label="{value} 列",
        width=320,
    )
    show_gallery_page_count_switch = ft.Switch(
        label="列表模式显示页数",
        value=bool(app_cfg.get("show_gallery_page_count", True)),
    )
    show_gallery_info_switch = ft.Switch(
        label="列表模式显示详细信息",
        value=bool(app_cfg.get("show_gallery_info", True)),
    )
    linux_title_bar_switch = ft.Switch(
        label="在Linux端启用内置标题栏",
        value=bool(app_cfg.get("linux_builtin_title_bar", False)),
    )
    linux_wayland_backend_switch = ft.Switch(
        label="在Linux端优先使用Wayland绘制窗体",
        value=bool(app_cfg.get("linux_prefer_wayland_window_backend", False)),
    )

    def current_app_config() -> dict:
        try:
            grid_columns = int(round(float(gallery_columns_slider.value or 5)))
        except (TypeError, ValueError):
            grid_columns = 5
        grid_columns = max(2, min(10, grid_columns))
        gallery_columns_slider.value = grid_columns
        gallery_columns_value.value = f"{grid_columns} 列"
        return {
            "enable_login": enable_login_switch.value,
            "load_images": load_images_switch.value,
            "show_error_toasts": show_error_toasts_switch.value,
            "render_gallery_cards": not render_cards_switch.value,
            "theme_mode": (theme_mode_segments.selected or ["system"])[0],
            "theme_color": theme_color_dropdown.value or "adaptive",
            "image_viewer_mode": viewer_mode_dropdown.value or "paged",
            "gallery_grid_columns": grid_columns,
            "gallery_view_mode": (gallery_view_mode_segments.selected or ["card"])[0],
            "show_gallery_page_count": show_gallery_page_count_switch.value,
            "show_gallery_info": show_gallery_info_switch.value,
            "debug_show_cover_dimensions": debug_cover_dimensions_switch.value,
            "debug_force_gallery_favorite": debug_force_favorite_switch.value,
            "debug_force_gallery_downloaded": debug_force_downloaded_switch.value,
            "debug_force_gallery_update": debug_force_update_switch.value,
            "linux_builtin_title_bar": linux_title_bar_switch.value,
            "linux_prefer_wayland_window_backend": linux_wayland_backend_switch.value,
        }

    def _selected_segment_value(event_data, fallback: str) -> str:
        if isinstance(event_data, list) and event_data:
            return str(event_data[0])
        if isinstance(event_data, str) and event_data:
            try:
                data = json.loads(event_data)
                if isinstance(data, list) and data:
                    return str(data[0])
                if isinstance(data, str) and data:
                    return data
            except json.JSONDecodeError:
                return event_data.strip("[]\"' ") or fallback
        return fallback

    def apply_app_settings(
        *,
        reason: str,
        target: ft.Text | None = None,
        message: str = "设置已更新",
        apply_theme: bool = False,
        invalidate_gallery: bool = False,
        update: bool = True,
    ) -> None:
        save_app_config(current_app_config())
        if apply_theme:
            apply_theme_fn = getattr(page, "fletviewer_apply_theme", None)
            if callable(apply_theme_fn):
                apply_theme_fn(False)
        if invalidate_gallery:
            _invalidate_gallery_views(page, reason)
        if target is not None:
            target.value = message
            target.color = ft.Colors.PRIMARY
        if update:
            page.update()

    def on_theme_mode_change(e):
        event_data = getattr(e, "data", None) or getattr(getattr(e, "control", None), "selected", None)
        mode = _selected_segment_value(event_data, "system")
        if mode not in {"system", "light", "dark"}:
            mode = "system"
        theme_mode_segments.selected = [mode]
        apply_app_settings(
            reason="theme_mode_changed",
            target=display_status,
            message="外观模式已更新",
            apply_theme=True,
        )

    theme_mode_segments.on_change = on_theme_mode_change
    theme_color_dropdown.on_select = lambda e: apply_app_settings(
        reason="theme_color_changed",
        target=display_status,
        message="主题色已更新",
        apply_theme=True,
    )
    viewer_mode_dropdown.on_select = lambda e: apply_app_settings(
        reason="viewer_mode_changed",
        target=display_status,
        message="默认阅读器已更新",
    )

    def update_gallery_columns_label() -> int:
        columns = max(2, min(10, int(round(float(gallery_columns_slider.value or 5)))))
        gallery_columns_slider.value = columns
        gallery_columns_value.value = f"{columns} 列"
        return columns

    def on_gallery_columns_change(e):
        update_gallery_columns_label()
        page.update()

    def on_gallery_columns_change_end(e):
        columns = update_gallery_columns_label()
        apply_app_settings(
            reason="gallery_grid_columns_changed",
            target=display_status,
            message=f"画廊列数已更新为 {columns} 列",
            invalidate_gallery=True,
        )

    gallery_columns_slider.on_change = on_gallery_columns_change
    gallery_columns_slider.on_change_end = on_gallery_columns_change_end

    def on_gallery_view_mode_change(e):
        event_data = getattr(e, "data", None) or getattr(getattr(e, "control", None), "selected", None)
        mode = _selected_segment_value(event_data, "card")
        gallery_view_mode_segments.selected = [mode if mode in {"card", "list", "masonry"} else "card"]
        apply_app_settings(
            reason="gallery_view_mode_changed",
            target=display_status,
            message="画廊浏览模式已更新",
            invalidate_gallery=True,
        )

    gallery_view_mode_segments.on_change = on_gallery_view_mode_change
    show_gallery_page_count_switch.on_change = lambda e: apply_app_settings(
        reason="gallery_page_count_visibility_changed",
        target=display_status,
        message="画廊页数显示设置已更新",
        invalidate_gallery=True,
    )
    show_gallery_info_switch.on_change = lambda e: apply_app_settings(
        reason="gallery_info_visibility_changed",
        target=display_status,
        message="画廊信息显示设置已更新",
        invalidate_gallery=True,
    )

    linux_title_bar_switch.on_change = lambda e: apply_app_settings(
        reason="linux_window_setting_changed",
        target=linux_window_status,
        message="Linux 窗口设置已保存，重启后生效",
    )
    linux_wayland_backend_switch.on_change = lambda e: apply_app_settings(
        reason="linux_window_setting_changed",
        target=linux_window_status,
        message="Linux 窗口设置已保存，重启后生效",
    )
    load_images_switch.on_change = lambda e: apply_app_settings(
        reason="debug_display_setting_changed",
        target=debug_status,
        message="调试显示设置已更新",
        invalidate_gallery=True,
    )
    show_error_toasts_switch.on_change = lambda e: apply_app_settings(
        reason="debug_error_toast_setting_changed",
        target=debug_status,
        message="错误提示设置已更新",
    )
    render_cards_switch.on_change = lambda e: apply_app_settings(
        reason="debug_display_setting_changed",
        target=debug_status,
        message="调试显示设置已更新",
        invalidate_gallery=True,
    )
    for debug_switch in (
        debug_cover_dimensions_switch,
        debug_force_favorite_switch,
        debug_force_downloaded_switch,
        debug_force_update_switch,
    ):
        debug_switch.on_change = lambda e: apply_app_settings(
            reason="gallery_cover_debug_setting_changed",
            target=debug_status,
            message="画廊封面调试设置已更新",
            invalidate_gallery=True,
        )

    def apply_login_mode(reason: str) -> None:
        save_app_config(current_app_config())
        browser_session.set_login_enabled(bool(enable_login_switch.value))
        login_status.value = browser_session.login_status_text()
        update_login_status_lamp()
        _invalidate_gallery_views(page, reason)

    def update_login_status_lamp() -> None:
        level = browser_session.login_status_level()
        if level == "ok":
            login_status_lamp.bgcolor = ft.Colors.GREEN
            login_status_lamp.tooltip = "已验证登录"
        elif level == "pending":
            login_status_lamp.bgcolor = ft.Colors.AMBER
            login_status_lamp.tooltip = "Cookie 已载入，尚未验证"
        elif level == "warning":
            login_status_lamp.bgcolor = ft.Colors.ORANGE
            login_status_lamp.tooltip = "登录配置不完整或未载入"
        else:
            login_status_lamp.bgcolor = ft.Colors.GREY
            login_status_lamp.tooltip = "游客模式"

    def on_login_toggle(e):
        apply_login_mode("login_mode_toggled")
        status.value = "登录模式已切换"
        status.color = ft.Colors.PRIMARY
        page.update()

    enable_login_switch.on_change = on_login_toggle
    update_login_status_lamp()

    def on_save(e):
        data = {key: fields[key].value.strip() for key, *_ in COOKIE_FIELDS}
        if enable_login_switch.value and (not data["ipb_member_id"] or not data["ipb_pass_hash"]):
            status.value = "ipb_member_id 和 ipb_pass_hash 为必填项"
            status.color = ft.Colors.ERROR
            page.update()
            return
        save_eh_config(data)
        apply_login_mode("eh_config_saved")
        status.value = f"已保存到 {CONFIG_PATH}"
        status.color = ft.Colors.PRIMARY
        page.update()

    def on_clear_image_cache(e):
        clear_image_cache()
        _invalidate_gallery_views(page, "image_cache_cleared")
        debug_status.value = "已清除所有图像缓存"
        debug_status.color = ft.Colors.PRIMARY
        page.update()

    def on_clear_gallery_cache(e):
        clear_gallery_cache()
        _invalidate_gallery_views(page, "gallery_cache_cleared")
        debug_status.value = "已清除所有画廊缓存"
        debug_status.color = ft.Colors.PRIMARY
        page.update()

    def open_page(label: str):
        render_label = getattr(page, "fletviewer_render_label", None)
        if callable(render_label):
            render_label(label)

    def on_test_toast(e):
        show_toast(page, "这是一条测试用小提示")

    account_page = ft.Container(
        padding=ft.Padding(0, 16, 0, 0),
        content=ft.Column(
            controls=[
                ft.Text("E-Hentai 凭据", size=20, weight=ft.FontWeight.W_500),
                ft.Text("Cookie 凭据，用于自动登录和访问收藏/订阅等功能。关闭自动登录后，公开页面会以游客状态访问。", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                enable_login_switch,
                ft.Row([login_status_lamp, login_status], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                *fields.values(),
                ft.Row(
                    [
                        ft.FilledButton("保存凭据", icon=ft.Icons.SAVE, on_click=on_save),
                        status,
                    ],
                    spacing=16,
                ),
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    display_page = ft.Container(
        padding=ft.Padding(0, 16, 0, 0),
        content=ft.Column(
            controls=[
                ft.Text("显示与阅读", size=20, weight=ft.FontWeight.W_500),
                ft.Text(
                    "外观使用 Material 3。自适应色彩会按平台和系统明暗模式选择色种。",
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Row([theme_mode_segments, theme_color_dropdown], spacing=12, wrap=True),
                viewer_mode_dropdown,
                ft.Text(f"当前设备: {_platform_label(page)}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text("画廊浏览模式", size=14, weight=ft.FontWeight.W_500),
                gallery_view_mode_segments,
                ft.Text("卡片/瀑布流列数", size=14, weight=ft.FontWeight.W_500),
                ft.Row([gallery_columns_slider, gallery_columns_value], spacing=12, wrap=True),
                show_gallery_page_count_switch,
                show_gallery_info_switch,
                display_status,
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    linux_window_page = ft.Container(
        padding=ft.Padding(0, 16, 0, 0),
        content=ft.Column(
            controls=[
                ft.Text("Linux 窗口", size=20, weight=ft.FontWeight.W_500),
                ft.Text(
                    "这些选项只在 Linux 桌面端生效，其他平台可以保存但不会应用。窗口后端和标题栏设置需要重启 App。",
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                linux_wayland_backend_switch,
                linux_title_bar_switch,
                linux_window_status,
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    storage_page = ft.Container(
        padding=ft.Padding(0, 16, 0, 0),
        content=ft.Column(
            controls=[
                ft.Text("存储", size=20, weight=ft.FontWeight.W_500),
                ft.Text(f"配置文件: {CONFIG_PATH}", size=14, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ft.Text(f"缓存 DB: {CACHE_DB_PATH}", size=14, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ft.Text(f"缓存文件目录: {CACHE_FILES_DIR}", size=14, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    debug_page = ft.Container(
        padding=ft.Padding(0, 16, 0, 0),
        content=ft.Column(
            controls=[
                ft.Text("调试", size=20, weight=ft.FontWeight.W_500),
                ft.Text(
                    "开发和排障入口集中放在这里，避免混进日常使用路径。",
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Text("调试开关", size=16, weight=ft.FontWeight.W_500),
                ft.Text(
                    "关闭图像加载可验证无图/缓存路径；关闭卡片渲染会把画廊列表切回 JSON 输出，用于排查 provider 返回数据。",
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                load_images_switch,
                show_error_toasts_switch,
                render_cards_switch,
                ft.Text("封面调试覆盖", size=16, weight=ft.FontWeight.W_500),
                ft.Text(
                    "这些开关仅用于检查封面尺寸和状态标签布局，默认全部关闭。",
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                debug_cover_dimensions_switch,
                debug_force_favorite_switch,
                debug_force_downloaded_switch,
                debug_force_update_switch,
                debug_status,
                ft.Divider(),
                ft.Text("画廊类型颜色", size=16, weight=ft.FontWeight.W_500),
                ft.Text(
                    "这些颜色与画廊封面右上角的语言角标一致，用于快速检查类型辨识度。",
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Text(
                                GALLERY_TYPE_LABELS[key],
                                size=11,
                                weight=ft.FontWeight.BOLD,
                                color=gallery_type_foreground(key),
                            ),
                            bgcolor=color,
                            padding=ft.Padding(10, 7, 10, 7),
                            border_radius=8,
                            alignment=ft.Alignment(0, 0),
                        )
                        for key, color in GALLERY_TYPE_COLORS.items()
                    ],
                    spacing=8,
                    run_spacing=8,
                    wrap=True,
                ),
                ft.Divider(),
                ft.Text("提示测试", size=16, weight=ft.FontWeight.W_500),
                ft.Row(
                    [
                        ft.OutlinedButton("弹出测试提示", icon=ft.Icons.NOTIFICATIONS, on_click=on_test_toast),
                    ],
                    spacing=12,
                    wrap=True,
                ),
                ft.Divider(),
                ft.Text("工具入口", size=16, weight=ft.FontWeight.W_500),
                ft.Row(
                    [
                        ft.OutlinedButton("历史", icon=ft.Icons.HISTORY, on_click=lambda e: open_page("历史")),
                        ft.OutlinedButton("调试", icon=ft.Icons.BUG_REPORT, on_click=lambda e: open_page("调试")),
                    ],
                    spacing=12,
                    wrap=True,
                ),
                ft.Divider(),
                ft.Text("缓存操作", size=16, weight=ft.FontWeight.W_500),
                ft.Row(
                    [
                        ft.OutlinedButton("清除所有图像缓存", icon=ft.Icons.DELETE_SWEEP, on_click=on_clear_image_cache),
                        ft.OutlinedButton("清除所有画廊缓存", icon=ft.Icons.DELETE_OUTLINE, on_click=on_clear_gallery_cache),
                    ],
                    spacing=12,
                    wrap=True,
                ),
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    def open_settings_page(route_key: str, title: str, icon, content: ft.Control):
        push_view = getattr(page, "fletviewer_push_view", None)
        pop_view = getattr(page, "fletviewer_pop_view", None)
        if not callable(push_view):
            return
        push_view(
            ft.View(
                route=f"/settings/{route_key}",
                controls=[ft.Container(content=content, padding=8, expand=True)],
                padding=0,
                appbar=ft.AppBar(
                    title=ft.Row(
                        [
                            ft.Icon(icon, size=22, color=ft.Colors.PRIMARY),
                            ft.Text(title, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    leading=ft.IconButton(ft.Icons.ARROW_BACK, tooltip="返回设置", on_click=lambda e: pop_view() if callable(pop_view) else None),
                    automatically_imply_leading=False,
                ),
            )
        )

    def settings_tile(route_key: str, title: str, subtitle: str, icon, content: ft.Control) -> ft.Control:
        return ft.ListTile(
            leading=ft.Container(
                content=ft.Icon(icon, size=22, color=ft.Colors.PRIMARY),
                width=40,
                height=40,
                border_radius=999,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                alignment=ft.Alignment(0, 0),
            ),
            title=ft.Text(title, size=16, weight=ft.FontWeight.W_500),
            subtitle=ft.Text(subtitle, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT, color=ft.Colors.ON_SURFACE_VARIANT),
            on_click=lambda e: open_settings_page(route_key, title, icon, content),
        )

    def settings_group(title: str, tiles: list[ft.Control]) -> ft.Control:
        controls: list[ft.Control] = []
        for idx, tile in enumerate(tiles):
            if idx:
                controls.append(ft.Divider(height=1, thickness=1, color=ft.Colors.OUTLINE_VARIANT))
            controls.append(tile)
        return ft.Column(
            [
                ft.Text(title, size=13, weight=ft.FontWeight.W_600, color=ft.Colors.PRIMARY),
                ft.Container(
                    content=ft.Column(controls, spacing=0),
                    bgcolor=ft.Colors.SURFACE,
                    border=ft.border.Border(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
                ),
            ],
            spacing=6,
        )

    return ft.Column(
        [
            ft.Text("设置", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("按类别管理账户、显示、平台、存储和调试入口。", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
            settings_group(
                "常规",
                [
                    settings_tile(
                        "account",
                        "账户",
                        "E-Hentai Cookie、自动登录和当前登录状态。",
                        ft.Icons.ACCOUNT_CIRCLE,
                        account_page,
                    ),
                    settings_tile(
                        "display",
                        "显示与阅读",
                        "外观、阅读器模式和画廊卡片显示。",
                        ft.Icons.PALETTE,
                        display_page,
                    ),
                ],
            ),
            settings_group(
                "系统",
                [
                    settings_tile(
                        "linux-window",
                        "Linux 窗口",
                        "Linux 桌面端标题栏和窗口后端设置。",
                        ft.Icons.DESKTOP_WINDOWS,
                        linux_window_page,
                    ),
                    settings_tile(
                        "storage",
                        "存储",
                        "配置文件、缓存数据库和缓存目录位置。",
                        ft.Icons.STORAGE,
                        storage_page,
                    ),
                ],
            ),
            settings_group(
                "调试",
                [
                    settings_tile(
                        "debug-tools",
                        "调试工具",
                        "历史、调试面板和缓存清理操作。",
                        ft.Icons.BUG_REPORT,
                        debug_page,
                    ),
                ],
            ),
        ],
        spacing=18,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
