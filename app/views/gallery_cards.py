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
        list_view = ft.ListView(
            expand=True,
            spacing=10,
            padding=ft.Padding(10, 108, 10, 86),
            scroll_interval=16,
        )
        status_text = ft.Text("加载中...", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
        refresh_btn = ft.Button("刷新", icon=ft.Icons.REFRESH)
        prev_btn = ft.IconButton(ft.Icons.ARROW_BACK, tooltip="上一页", disabled=True)
        next_btn = ft.IconButton(ft.Icons.ARROW_FORWARD, tooltip="下一页", disabled=True)
        page_label = ft.Text("第 1 页", size=14, weight=ft.FontWeight.W_500)

        state = {"current_url": None, "prev_url": None, "next_url": None, "page_num": 1, "comics": []}
        column_state = {"value": runs_count_for_width(page.width, min_columns=2, max_columns=10)}
        set_header_actions = getattr(page, "fletviewer_set_header_actions", None)
        if callable(set_header_actions):
            set_header_actions([status_text, refresh_btn])

        pagination_bar = ft.Container(
            content=ft.Row(
                [prev_btn, page_label, next_btn],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=6,
                tight=True,
            ),
            padding=ft.Padding(6, 6, 6, 6),
            bgcolor=ft.Colors.with_opacity(0.88, ft.Colors.SURFACE_CONTAINER_HIGH),
            border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=999,
            shadow=ft.BoxShadow(
                blur_radius=16,
                spread_radius=0,
                color=ft.Colors.with_opacity(0.18, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
        )

        def rebuild_gallery_rows() -> None:
            columns = max(1, int(column_state["value"] or 1))
            cards = [make_gallery_card(page, comic) for comic in state["comics"]]
            controls: list[ft.Control] = []
            for start in range(0, len(cards), columns):
                chunk = cards[start:start + columns]
                cells = [ft.Container(content=card, expand=1, aspect_ratio=0.72) for card in chunk]
                if len(cells) < columns:
                    cells.extend(ft.Container(expand=1) for _ in range(columns - len(cells)))
                controls.append(ft.Row(cells, spacing=10, vertical_alignment=ft.CrossAxisAlignment.START))
            controls.append(ft.Container(content=pagination_bar, alignment=ft.Alignment(0, 0), padding=ft.Padding(0, 8, 0, 0)))
            list_view.controls = controls

        def update_grid_columns(e=None):
            new_count = runs_count_for_width(page.width, min_columns=2, max_columns=10)
            if column_state["value"] != new_count:
                column_state["value"] = new_count
                rebuild_gallery_rows()
                page.update()

        add_resize_handler = getattr(page, "fletviewer_add_resize_handler", None)
        if callable(add_resize_handler):
            add_resize_handler(update_grid_columns)

        def on_grid_scroll(e):
            on_content_scroll = getattr(page, "fletviewer_on_content_scroll", None)
            if callable(on_content_scroll):
                on_content_scroll(getattr(e, "scroll_delta", None), getattr(e, "pixels", None))

        list_view.on_scroll = on_grid_scroll

        def load(page_url=None):
            log_debug("画廊列表", f"{title} 开始加载 page_url={page_url}")
            refresh_btn.disabled = True
            prev_btn.disabled = True
            next_btn.disabled = True
            status_text.value = "加载中..."
            state["comics"] = []
            rebuild_gallery_rows()
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
                    state["comics"] = list(result.comics)
                    state["current_url"] = page_url
                    state["prev_url"] = result.prev_url
                    state["next_url"] = result.next_url
                    prev_btn.disabled = result.prev_url is None
                    next_btn.disabled = result.next_url is None
                    rebuild_gallery_rows()

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

        def on_prev(e):
            if state["prev_url"]:
                state["page_num"] = max(1, int(state["page_num"] or 1) - 1)
                page_label.value = f"第 {state['page_num']} 页"
                load(state["prev_url"])

        def on_next(e):
            if state["next_url"]:
                state["page_num"] = int(state["page_num"] or 1) + 1
                page_label.value = f"第 {state['page_num']} 页"
                load(state["next_url"])

        refresh_btn.on_click = on_refresh
        prev_btn.on_click = on_prev
        next_btn.on_click = on_next

        load()
        return list_view

    return factory
