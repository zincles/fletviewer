import flet as ft

from app.storage import (
    APP_CONFIG_PATH,
    EH_CONFIG_PATH,
    get_image_viewer_mode,
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

GALLERY_VIEW_CACHE_KEYS = ["page:0", "page:1", "page:2", "page:3", "page:4", "search"]


def _invalidate_gallery_views(page: ft.Page, reason: str) -> None:
    invalidate = getattr(page, "fletviewer_invalidate_views", None)
    if callable(invalidate):
        invalidate(GALLERY_VIEW_CACHE_KEYS, reason=reason)


def create_view(page: ft.Page) -> ft.Control:
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
    linux_title_bar_switch = ft.Switch(
        label="在Linux端启用内置标题栏",
        value=bool(app_cfg.get("linux_builtin_title_bar", False)),
    )
    linux_wayland_backend_switch = ft.Switch(
        label="在Linux端优先使用Wayland绘制窗体",
        value=bool(app_cfg.get("linux_prefer_wayland_window_backend", False)),
    )

    def on_save(e):
        data = {key: fields[key].value.strip() for key, *_ in COOKIE_FIELDS}
        if not data["ipb_member_id"] or not data["ipb_pass_hash"]:
            status.value = "ipb_member_id 和 ipb_pass_hash 为必填项"
            status.color = ft.Colors.ERROR
            page.update()
            return
        save_eh_config(data)
        _invalidate_gallery_views(page, "eh_config_saved")
        status.value = f"已保存到 {EH_CONFIG_PATH}"
        status.color = ft.Colors.PRIMARY
        page.update()

    def on_save_app(e):
        save_app_config(
            {
                "load_images": load_images_switch.value,
                "render_gallery_cards": render_cards_switch.value,
                "image_viewer_mode": viewer_mode_dropdown.value or "paged",
                "linux_builtin_title_bar": linux_title_bar_switch.value,
                "linux_prefer_wayland_window_backend": linux_wayland_backend_switch.value,
            }
        )
        _invalidate_gallery_views(page, "app_debug_config_saved")
        message = f"已保存到 {APP_CONFIG_PATH}。Linux 窗口设置重启后生效。"
        for target in (display_status, linux_window_status):
            target.value = message
            target.color = ft.Colors.PRIMARY
        page.update()

    account_page = ft.Container(
        padding=ft.Padding(0, 16, 0, 0),
        content=ft.Column(
            controls=[
                ft.Text("E-Hentai 凭据", size=20, weight=ft.FontWeight.W_500),
                ft.Text("Cookie 凭据，用于登录和访问收藏/订阅等功能", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
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
                ft.Row(
                    [
                        ft.Button("保存应用设置", on_click=on_save_app),
                        display_status,
                    ],
                    spacing=16,
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
                ft.Text(f"配置目录: {EH_CONFIG_PATH.parent}", size=14, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ft.Text(f"应用配置: {APP_CONFIG_PATH}", size=14, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ft.Text(f"EH 凭据: {EH_CONFIG_PATH}", size=14, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
        ),
    )

    return ft.Column(
        controls=[
            ft.Text("设置", size=32, weight=ft.FontWeight.BOLD),
            ft.Tabs(
                content=ft.Column(
                    [
                        ft.TabBar(
                            tabs=[
                                ft.Tab(label="账户"),
                                ft.Tab(label="显示"),
                                ft.Tab(label="Linux 窗口"),
                                ft.Tab(label="存储"),
                            ],
                        ),
                        ft.TabBarView(
                            controls=[account_page, display_page, linux_window_page, storage_page],
                            expand=True,
                        ),
                    ],
                    expand=True,
                ),
                length=4,
                selected_index=0,
                expand=True,
            ),
        ],
        spacing=16,
        expand=True,
    )
