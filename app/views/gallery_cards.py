import math
from typing import Callable

import flet as ft

from app.controls.async_image import async_image
from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.gallery_type_colors import gallery_type_color, gallery_type_foreground
from app.grid_layout import runs_count_for_width
from app.storage import get_gallery_view_mode, load_eh_config, should_show_gallery_info, should_show_gallery_page_count
from app.toast import show_error_toast, show_toast
from app.ui_update import request_update
from core.provider.ehgrabber import EHentaiClient, Comic, SearchResult


LANGUAGE_CODES = {
    "chinese": "ZH",
    "english": "EN",
    "japanese": "JA",
    "korean": "KO",
    "spanish": "ES",
    "french": "FR",
    "german": "DE",
    "italian": "IT",
    "portuguese": "PT",
    "russian": "RU",
    "thai": "TH",
    "vietnamese": "VI",
}


def _language_code(language: str | None) -> str:
    """把 provider 语言名转换为卡片角标使用的两字母代码。"""
    normalized = (language or "").strip().lower()
    if not normalized:
        return "--"
    return LANGUAGE_CODES.get(normalized, normalized[:2].upper())


def _gallery_cover(page: ft.Page, comic: Comic) -> ft.Control:
    """创建纯封面和语言角标。"""
    return ft.Container(
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
                    width=40,
                    height=40,
                    top=-20,
                    right=-20,
                    rotate=ft.Rotate(angle=math.pi / 4),
                    bgcolor=gallery_type_color(comic.type),
                ),
                ft.Container(
                    content=ft.Text(
                        _language_code(comic.language),
                        size=9,
                        weight=ft.FontWeight.BOLD,
                        color=gallery_type_foreground(comic.type),
                    ),
                    width=24,
                    height=20,
                    top=-2,
                    right=-2,
                    alignment=ft.Alignment(0, 0),
                    tooltip=comic.language or "未知语言",
                ),
                # 封面状态约定：右下胶囊依次表示已收藏/已下载，上方圆标表示本地画廊有新版本。
                # 当前全部显示用于验证布局；接入真实状态后只切换 visible，不改变这组位置和语义。
                ft.Container(
                    content=ft.Icon(ft.Icons.UPGRADE, size=14, color=ft.Colors.ON_PRIMARY),
                    width=26,
                    height=26,
                    right=6,
                    bottom=36,
                    alignment=ft.Alignment(0, 0),
                    bgcolor=ft.Colors.PRIMARY,
                    border=ft.border.Border.all(2, ft.Colors.SURFACE),
                    border_radius=999,
                    tooltip="有新版本可用",
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.FAVORITE, size=14, color=ft.Colors.ON_PRIMARY),
                            ft.Icon(ft.Icons.DOWNLOAD_DONE, size=14, color=ft.Colors.ON_PRIMARY),
                        ],
                        spacing=5,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    right=6,
                    bottom=6,
                    padding=ft.Padding(7, 5, 7, 5),
                    bgcolor=ft.Colors.with_opacity(0.86, ft.Colors.PRIMARY),
                    border=ft.border.Border.all(1, ft.Colors.with_opacity(0.72, ft.Colors.SURFACE)),
                    border_radius=999,
                    tooltip="已收藏 · 已下载",
                ),
            ],
            expand=True,
        ),
        border_radius=8,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        expand=True,
    )


def _openable_card(page: ft.Page, comic: Comic, card: ft.Control) -> ft.Control:
    """让画廊卡片可进入详情页。"""
    open_detail = getattr(page, "fletviewer_open_gallery_detail", None)
    if not callable(open_detail):
        return card
    return ft.GestureDetector(
        content=card,
        mouse_cursor=ft.MouseCursor.CLICK,
        on_tap=lambda e: open_detail(comic),
    )


def make_gallery_card(page: ft.Page, comic: Comic, *, mode: str | None = None) -> ft.Control:
    """按浏览模式创建纯封面瀑布流卡片或详细列表卡片。"""
    view_mode = mode or get_gallery_view_mode()
    if view_mode == "waterfall":
        return _openable_card(page, comic, ft.Card(content=_gallery_cover(page, comic)))

    show_page_count = should_show_gallery_page_count()
    show_gallery_info = should_show_gallery_info()
    details: list[ft.Control] = []
    if show_gallery_info:
        details.extend(
            [
                ft.Text(comic.type or "未知类型", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(f"评分 {comic.stars:.1f}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(comic.sub_title or comic.uploader or "", size=12, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ]
        )
    if show_page_count:
        details.append(ft.Text(f"{comic.max_page or '?'} 页", size=12, color=ft.Colors.ON_SURFACE_VARIANT))
    card = ft.Card(
        content=ft.Container(
            content=ft.Row(
                [
                    ft.Container(content=_gallery_cover(page, comic), width=104, height=140),
                    ft.Column(
                        [
                            ft.Text(comic.title or "未命名画廊", size=15, weight=ft.FontWeight.W_600, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS),
                            *details,
                        ],
                        spacing=6,
                        expand=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(0, 0, 14, 0),
            height=140,
        ),
    )
    return _openable_card(page, comic, card)


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
        grid_spacing = 0
        list_view = ft.ListView(
            expand=True,
            spacing=grid_spacing,
            padding=ft.Padding(10, 108, 10, 86),
            scroll_interval=16,
        )
        status_text = ft.Text("加载中...", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
        refresh_btn = ft.Button("刷新", icon=ft.Icons.REFRESH)
        prev_btn = ft.IconButton(ft.Icons.ARROW_BACK, tooltip="上一页", disabled=True)
        next_btn = ft.IconButton(ft.Icons.ARROW_FORWARD, tooltip="下一页", disabled=True)
        page_label = ft.Text("第 1 页", size=14, weight=ft.FontWeight.W_500)

        state = {"current_url": None, "prev_url": None, "next_url": None, "page_num": 1, "comics": []}
        view_mode = get_gallery_view_mode()
        column_state = {"value": runs_count_for_width(page.width, min_columns=2, max_columns=10)}

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
            controls: list[ft.Control] = []
            if status_text.value:
                controls.append(ft.Container(content=status_text, padding=ft.Padding(4, 2, 4, 2)))
            if view_mode == "list":
                controls.extend(make_gallery_card(page, comic, mode="list") for comic in state["comics"])
            else:
                columns = max(1, int(column_state["value"] or 1))
                cards = [make_gallery_card(page, comic, mode="waterfall") for comic in state["comics"]]
                for start in range(0, len(cards), columns):
                    chunk = cards[start:start + columns]
                    cells = [ft.Container(content=card, expand=1, aspect_ratio=0.72) for card in chunk]
                    if len(cells) < columns:
                        cells.extend(ft.Container(expand=1) for _ in range(columns - len(cells)))
                    controls.append(ft.Row(cells, spacing=grid_spacing, vertical_alignment=ft.CrossAxisAlignment.START))
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
                        show_toast(page, f"{title}: 请先在账户页填写凭据")
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
                    status_text.value = ""
                    rebuild_gallery_rows()
                except Exception as ex:
                    status_text.value = f"错误: {ex}"
                    show_error_toast(page, f"{title}加载失败", ex)
                    log_exception("画廊列表", f"{title} 加载失败: {ex}")
                finally:
                    refresh_btn.disabled = False
                    request_update(page)

            page.run_thread(worker)

        def on_refresh(e):
            load(state["current_url"])

        set_refresh_action = getattr(page, "fletviewer_set_reading_refresh_action", None)
        if callable(set_refresh_action):
            set_refresh_action(lambda: on_refresh(None))

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
