import flet as ft

from app.storage import load_eh_config, save_eh_config, EH_CONFIG_PATH

COOKIE_FIELDS = [
    ("ipb_member_id", "ipb_member_id", "EH 会员 ID", True),
    ("ipb_pass_hash", "ipb_pass_hash", "ipb_pass_hash", True),
    ("igneous", "igneous", "igneous（exhentai 可选）", False),
    ("star", "star", "star（可选）", False),
]


def create_view(page: ft.Page) -> ft.Control:
    cfg = load_eh_config()

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

    def on_save(e):
        data = {key: fields[key].value.strip() for key, *_ in COOKIE_FIELDS}
        if not data["ipb_member_id"] or not data["ipb_pass_hash"]:
            status.value = "ipb_member_id 和 ipb_pass_hash 为必填项"
            status.color = ft.Colors.ERROR
            page.update()
            return
        save_eh_config(data)
        status.value = f"已保存到 {EH_CONFIG_PATH}"
        status.color = ft.Colors.PRIMARY
        page.update()

    return ft.Column(
        controls=[
            ft.Text("设置", size=32, weight=ft.FontWeight.BOLD),

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

            ft.Divider(),
            ft.Text("存储", size=20, weight=ft.FontWeight.W_500),
            ft.Text(f"配置目录: {EH_CONFIG_PATH.parent}", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
        ],
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
