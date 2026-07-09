import flet as ft

from app.browser_session import browser_session
from app.gallery_cache import clear_gallery_cache
from app.image_cache import clear_image_cache
from app.storage import (
    CACHE_DB_PATH,
    CACHE_FILES_DIR,
    CONFIG_PATH,
    get_image_viewer_mode,
    get_image_grid_target_width,
    load_app_config,
    load_eh_config,
    save_app_config,
    save_eh_config,
)

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
    render_cards_switch = ft.Switch(
        label="是否使用卡片渲染画廊列表",
        value=bool(app_cfg.get("render_gallery_cards", True)),
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
    image_grid_width_field = ft.TextField(
        label="图片网格参考宽度",
        value=str(get_image_grid_target_width()),
        width=220,
        dense=True,
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
            grid_width = int(image_grid_width_field.value or "220")
        except ValueError:
            grid_width = 220
        grid_width = max(140, min(420, grid_width))
        image_grid_width_field.value = str(grid_width)
        return {
            "enable_login": enable_login_switch.value,
            "load_images": load_images_switch.value,
            "render_gallery_cards": render_cards_switch.value,
            "image_viewer_mode": viewer_mode_dropdown.value or "paged",
            "image_grid_target_width": grid_width,
            "linux_builtin_title_bar": linux_title_bar_switch.value,
            "linux_prefer_wayland_window_backend": linux_wayland_backend_switch.value,
        }

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

    def on_save_app(e):
        save_app_config(current_app_config())
        _invalidate_gallery_views(page, "app_debug_config_saved")
        message = f"已保存到 {CONFIG_PATH}。Linux 窗口设置重启后生效。"
        for target in (display_status, linux_window_status):
            target.value = message
            target.color = ft.Colors.PRIMARY
        apply_login_mode("login_mode_changed")
        page.update()

    def on_clear_image_cache(e):
        clear_image_cache()
        _invalidate_gallery_views(page, "image_cache_cleared")
        display_status.value = "已清除所有图像缓存"
        display_status.color = ft.Colors.PRIMARY
        page.update()

    def on_clear_gallery_cache(e):
        clear_gallery_cache()
        _invalidate_gallery_views(page, "gallery_cache_cleared")
        display_status.value = "已清除所有画廊缓存"
        display_status.color = ft.Colors.PRIMARY
        page.update()

    def open_page(label: str):
        render_label = getattr(page, "fletviewer_render_label", None)
        if callable(render_label):
            render_label(label)

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
                        ft.Button("保存凭据", on_click=on_save),
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
                ft.Text("显示与调试", size=20, weight=ft.FontWeight.W_500),
                ft.Text(
                    "关闭图像加载后，界面不会读取缓存图片，也不会向远端请求新图像资源。关闭卡片渲染后，画廊列表会回到 JSON 调试输出。",
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                    load_images_switch,
                    render_cards_switch,
                    viewer_mode_dropdown,
                    ft.Text(f"当前设备: {_platform_label(page)}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Row([image_grid_width_field, ft.Text("px", color=ft.Colors.ON_SURFACE_VARIANT)], spacing=8),
                    ft.Row(
                        [
                            ft.Button("保存应用设置", on_click=on_save_app),
                            display_status,
                        ],
                        spacing=16,
                    ),
                    ft.Divider(),
                    ft.Text("工具入口", size=16, weight=ft.FontWeight.W_500),
                    ft.Row(
                        [
                            ft.Button("历史", icon=ft.Icons.HISTORY, on_click=lambda e: open_page("历史")),
                            ft.Button("调试", icon=ft.Icons.BUG_REPORT, on_click=lambda e: open_page("调试")),
                        ],
                        spacing=12,
                        wrap=True,
                    ),
                    ft.Divider(),
                    ft.Text("调试操作", size=16, weight=ft.FontWeight.W_500),
                    ft.Row(
                        [
                            ft.Button("清除所有图像缓存", icon=ft.Icons.DELETE_SWEEP, on_click=on_clear_image_cache),
                            ft.Button("清除所有画廊缓存", icon=ft.Icons.DELETE_OUTLINE, on_click=on_clear_gallery_cache),
                        ],
                        spacing=12,
                        wrap=True,
                    ),
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
                ft.Row(
                    [
                        ft.Button("保存应用设置", on_click=on_save_app),
                        linux_window_status,
                    ],
                    spacing=16,
                ),
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
            ft.Text("按类别管理账户、显示、平台和存储设置。", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
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
                        "图像加载、卡片渲染、阅读器模式和网格尺寸。",
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
        ],
        spacing=18,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
