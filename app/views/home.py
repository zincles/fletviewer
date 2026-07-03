import threading

import flet as ft

from app.image_proxy import public_src
from app.storage import load_eh_config
from lib.provider.ehgrabber import EHentaiClient, SearchResult, Comic


def _make_card(comic: Comic) -> ft.Control:
    return ft.Card(
        content=ft.Container(
            content=ft.Stack(
                controls=[
                    ft.Image(
                        src=public_src(comic.cover) if comic.cover else None,
                        fit=ft.BoxFit.COVER,
                        width=float("inf"),
                        height=180,
                    ),
                    ft.Container(
                        content=ft.Column(
                            controls=[
                                ft.Text(
                                    comic.title,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                    size=13,
                                    weight=ft.FontWeight.W_500,
                                    color=ft.Colors.WHITE,
                                ),
                                ft.Row(
                                    controls=[
                                        ft.Text(comic.type, size=11, color=ft.Colors.WHITE),
                                        ft.Text(f"{comic.max_page}P", size=11, color=ft.Colors.WHITE),
                                        ft.Text(f"★{comic.stars}", size=11, color=ft.Colors.WHITE),
                                    ],
                                    spacing=8,
                                ),
                            ],
                            spacing=4,
                        ),
                        padding=8,
                        bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
                        bottom=0, left=0, right=0,
                        expand=True,
                        alignment=ft.Alignment(-1, 1),
                    ),
                ],
                expand=True,
            ),
            border_radius=8,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            height=220,
        ),
    )


def create_view(page: ft.Page) -> ft.Control:
    grid = ft.GridView(
        expand=True,
        runs_count=5,
        spacing=10,
        run_spacing=10,
        child_aspect_ratio=0.65,
        padding=10,
    )
    status_text = ft.Text("加载中...", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
    prev_btn = ft.Button("上一页", icon=ft.Icons.ARROW_BACK, disabled=True)
    next_btn = ft.Button("下一页", icon=ft.Icons.ARROW_FORWARD, disabled=True)
    page_label = ft.Text("第 1 页", size=14)

    state = {"page_num": 1, "prev_url": None, "next_url": None}

    def load(url=None):
        prev_btn.disabled = True
        next_btn.disabled = True
        status_text.value = "加载中..."
        grid.controls.clear()
        page.update()

        def worker():
            try:
                cfg = load_eh_config()
                client = EHentaiClient(domain="e-hentai.org")
                if cfg.get("ipb_member_id") and cfg.get("ipb_pass_hash"):
                    client.login_with_cookies(**cfg)
                result = client.get_latest(page_url=url)

                grid.controls = [_make_card(c) for c in result.comics]
                for c in result.comics:
                    print(f"[卡片] {c.title}")
                state["prev_url"] = result.prev_url
                state["next_url"] = result.next_url

                prev_btn.disabled = result.prev_url is None
                next_btn.disabled = result.next_url is None
                status_text.value = f"共 {len(result.comics)} 个画廊"
                page.update()
            except Exception as ex:
                status_text.value = f"错误: {ex}"
                page.update()

        threading.Thread(target=worker, daemon=True).start()

    def on_prev(e):
        if state["prev_url"]:
            state["page_num"] -= 1
            page_label.value = f"第 {state['page_num']} 页"
            load(state["prev_url"])

    def on_next(e):
        if state["next_url"]:
            state["page_num"] += 1
            page_label.value = f"第 {state['page_num']} 页"
            load(state["next_url"])

    prev_btn.on_click = on_prev
    next_btn.on_click = on_next

    load()

    return ft.Column(
        controls=[
            ft.Row(
                [ft.Text("主页", size=32, weight=ft.FontWeight.BOLD), status_text],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Divider(),
            grid,
            ft.Divider(),
            ft.Row(
                [prev_btn, page_label, next_btn],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=20,
            ),
        ],
        spacing=12,
        expand=True,
    )
