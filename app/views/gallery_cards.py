from typing import Callable

import flet as ft

from app.controls.async_image import async_image
from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.grid_layout import runs_count_for_width
from app.storage import load_eh_config
from app.ui_update import request_update
from lib.provider.ehgrabber import EHentaiClient, Comic, SearchResult


def make_gallery_card(page: ft.Page, comic: Comic) -> ft.Control:
    """创建在线画廊卡片，包含封面、标题、页数徽章和基础信息。"""
    card = ft.Card(
        content=ft.Container(
            content=ft.Stack(
                controls=[
                    async_image(
                        page,
                        comic.cover,
                        fit=ft.BoxFit.COVER,
                        width=float("inf"),
                        height=float("inf"),
                        cache_width=360,
                        cache_height=360,
                    ),
                    ft.Container(
                        content=ft.Text(str(comic.max_page or "?"), size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_PRIMARY),
                        width=34,
                        height=34,
                        bgcolor=ft.Colors.PRIMARY,
                        border_radius=999,
                        alignment=ft.Alignment(0, 0),
                        top=8,
                        right=8,
                        tooltip="页数",
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
                        alignment=ft.Alignment(-1, 1),
                    ),
                ],
                expand=True,
            ),
            border_radius=8,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            expand=True,
        ),
    )
    open_detail = getattr(page, "fletviewer_open_gallery_detail", None)
    if callable(open_detail):
        return ft.GestureDetector(
            content=card,
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda e: open_detail(comic),
        )
    return card


def create_gallery_cards_view(
    *,
    title: str,
    subtitle: str,
    load_fn: Callable[[EHentaiClient, str | None], SearchResult],
    needs_login: bool = False,
) -> Callable[[ft.Page], ft.Control]:
    """创建可复用的在线画廊卡片列表页面工厂。"""
    def factory(page: ft.Page) -> ft.Control:
        """创建具体页面实例，并注册自适应列数 resize handler。"""
        grid = ft.GridView(
            expand=True,
            runs_count=runs_count_for_width(page.width, min_columns=2, max_columns=10),
            spacing=10,
            run_spacing=10,
            child_aspect_ratio=0.72,
            padding=ft.Padding(10, 10, 10, 86),
        )
        status_text = ft.Text("加载中...", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
        refresh_btn = ft.Button("刷新", icon=ft.Icons.REFRESH)

        state = {"current_url": None}
        set_header_actions = getattr(page, "fletviewer_set_header_actions", None)
        if callable(set_header_actions):
            set_header_actions([status_text, refresh_btn])

        def update_grid_columns(e=None):
            new_count = runs_count_for_width(page.width, min_columns=2, max_columns=10)
            if grid.runs_count != new_count:
                grid.runs_count = new_count
                page.update()

        add_resize_handler = getattr(page, "fletviewer_add_resize_handler", None)
        if callable(add_resize_handler):
            add_resize_handler(update_grid_columns)

        def load(page_url=None):
            log_debug("画廊列表", f"{title} 开始加载 page_url={page_url}")
            refresh_btn.disabled = True
            status_text.value = "加载中..."
            grid.controls.clear()
            page.update()

            def worker():
                try:
                    log_debug("画廊列表", f"{title} worker 启动 needs_login={needs_login}")
                    cfg = load_eh_config()
                    if needs_login and (not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash")):
                        log_debug("画廊列表", f"{title} 缺少登录凭据")
                        status_text.value = "请先在账户页填写凭据"
                        return

                    client = browser_session.get_eh_client(require_login=needs_login)

                    with Timer("gallery", f"{title} load_fn page_url={page_url}"):
                        result = load_fn(client, page_url)
                    log_debug("画廊列表", f"{title} 加载完成 count={len(result.comics)} prev={bool(result.prev_url)} next={bool(result.next_url)}")
                    grid.controls = [make_gallery_card(page, comic) for comic in result.comics]
                    state["current_url"] = page_url

                    status_text.value = f"共 {len(result.comics)} 个画廊"
                except Exception as ex:
                    status_text.value = f"错误: {ex}"
                    log_exception("画廊列表", f"{title} 加载失败: {ex}")
                finally:
                    refresh_btn.disabled = False
                    request_update(page)

            page.run_thread(worker)

        def on_refresh(e):
            load(state["current_url"])

        refresh_btn.on_click = on_refresh

        load()
        return grid

    return factory
