import threading
from typing import Callable

import flet as ft

from app.controls.async_image import async_image
from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.storage import load_eh_config
from lib.provider.ehgrabber import EHentaiClient, Comic, SearchResult


def make_gallery_card(page: ft.Page, comic: Comic) -> ft.Control:
    return ft.Card(
        content=ft.Container(
            content=ft.Stack(
                controls=[
                    async_image(
                        page,
                        comic.cover,
                        fit=ft.BoxFit.COVER,
                        width=float("inf"),
                        height=180,
                        cache_width=360,
                        cache_height=360,
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
                        bottom=0,
                        left=0,
                        right=0,
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


def create_gallery_cards_view(
    *,
    title: str,
    subtitle: str,
    load_fn: Callable[[EHentaiClient, str | None], SearchResult],
    needs_login: bool = False,
) -> Callable[[ft.Page], ft.Control]:
    def factory(page: ft.Page) -> ft.Control:
        grid = ft.GridView(
            expand=True,
            runs_count=5,
            spacing=10,
            run_spacing=10,
            child_aspect_ratio=0.65,
            padding=10,
        )
        status_text = ft.Text("加载中...", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
        refresh_btn = ft.Button("刷新", icon=ft.Icons.REFRESH)
        prev_btn = ft.Button("上一页", icon=ft.Icons.ARROW_BACK, disabled=True)
        next_btn = ft.Button("下一页", icon=ft.Icons.ARROW_FORWARD, disabled=True)
        page_label = ft.Text("第 1 页", size=14)

        state = {"page_num": 1, "prev_url": None, "next_url": None, "current_url": None}

        def load(page_url=None):
            log_debug("gallery", f"{title} load requested page_url={page_url}")
            refresh_btn.disabled = True
            prev_btn.disabled = True
            next_btn.disabled = True
            status_text.value = "加载中..."
            grid.controls.clear()
            page.update()

            def worker():
                try:
                    log_debug("gallery", f"{title} worker start needs_login={needs_login}")
                    cfg = load_eh_config()
                    if needs_login and (not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash")):
                        log_debug("gallery", f"{title} missing credentials")
                        status_text.value = "请先在账户页填写凭据"
                        return

                    client = browser_session.get_eh_client(require_login=needs_login)

                    with Timer("gallery", f"{title} load_fn page_url={page_url}"):
                        result = load_fn(client, page_url)
                    log_debug(
                        "gallery",
                        f"{title} result count={len(result.comics)} prev={result.prev_url} next={result.next_url}",
                    )
                    grid.controls = [make_gallery_card(page, comic) for comic in result.comics]
                    state["prev_url"] = result.prev_url
                    state["next_url"] = result.next_url
                    state["current_url"] = page_url

                    prev_btn.disabled = result.prev_url is None
                    next_btn.disabled = result.next_url is None
                    status_text.value = f"共 {len(result.comics)} 个画廊"
                except Exception as ex:
                    status_text.value = f"错误: {ex}"
                    log_exception("gallery", f"{title} worker failed: {ex}")
                finally:
                    refresh_btn.disabled = False
                    page.update()

            threading.Thread(target=worker, daemon=True).start()

        def on_refresh(e):
            load(state["current_url"])

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

        refresh_btn.on_click = on_refresh
        prev_btn.on_click = on_prev
        next_btn.on_click = on_next

        load()

        return ft.Column(
            controls=[
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(title, size=32, weight=ft.FontWeight.BOLD),
                                ft.Text(subtitle, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                            ],
                            spacing=2,
                        ),
                        ft.Row([status_text, refresh_btn], spacing=12),
                    ],
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

    return factory
