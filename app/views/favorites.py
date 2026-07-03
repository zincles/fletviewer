import dataclasses
import json
import threading

import flet as ft

from app.storage import load_eh_config
from lib.provider.ehgrabber import EHentaiClient


def _comic_to_dict(c):
    return dataclasses.asdict(c)


def create_view(page: ft.Page) -> ft.Control:
    output = ft.Text("加载中...", size=14, selectable=True)
    btn = ft.Button("刷新", icon=ft.Icons.REFRESH)

    def load():
        btn.disabled = True
        output.value = "加载中..."
        page.update()

        def worker():
            try:
                cfg = load_eh_config()
                if not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash"):
                    output.value = "请先在账户页填写凭据"
                    return

                client = EHentaiClient(domain="e-hentai.org")
                client.login_with_cookies(**cfg)
                result = client.get_favorites()

                comics = [_comic_to_dict(c) for c in result.comics]
                data = {
                    "count": len(comics),
                    "next_url": result.next_url,
                    "comics": comics,
                }
                output.value = json.dumps(data, ensure_ascii=False, indent=2)
            except Exception as ex:
                output.value = f"错误: {ex}"
            finally:
                btn.disabled = False
                page.update()

        threading.Thread(target=worker, daemon=True).start()

    btn.on_click = lambda e: load()
    load()

    return ft.Column(
        controls=[
            ft.Text("收藏", size=32, weight=ft.FontWeight.BOLD),
            ft.Text("E-Hentai 收藏列表", size=16, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Divider(),
            btn,
            ft.Container(
                content=ft.Column(
                    [output],
                    scroll=ft.ScrollMode.AUTO,
                ),
                expand=True,
                border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=8,
                padding=16,
            ),
        ],
        spacing=16,
        expand=True,
    )
