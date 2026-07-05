import dataclasses
import json

import flet as ft

from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.grid_layout import runs_count_for_width
from app.storage import should_render_gallery_cards
from app.ui_update import request_update
from app.views.gallery_cards import make_gallery_card


def _comic_to_dict(comic):
    """把搜索结果中的 Comic dataclass 转为字典。"""
    return dataclasses.asdict(comic)


def _result_to_json(result) -> str:
    """把搜索结果格式化为 JSON 调试文本。"""
    data = {
        "count": len(result.comics),
        "prev_url": result.prev_url,
        "next_url": result.next_url,
        "comics": [_comic_to_dict(comic) for comic in result.comics],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def create_view(page: ft.Page) -> ft.Control:
    """创建搜索页，支持卡片结果和 JSON 调试输出。"""
    query = ft.TextField(
        label="搜索关键词",
        hint_text="例如: blue archive",
        width=500,
        autofocus=True,
    )
    btn = ft.Button("搜索", icon=ft.Icons.SEARCH)
    prev_btn = ft.Button("上一页", icon=ft.Icons.ARROW_BACK, disabled=True)
    next_btn = ft.Button("下一页", icon=ft.Icons.ARROW_FORWARD, disabled=True)
    page_label = ft.Text("第 1 页", size=14)
    status = ft.Text("输入关键词后搜索", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
    render_cards = should_render_gallery_cards()
    grid = ft.GridView(
        expand=True,
        runs_count=runs_count_for_width(page.width, min_columns=2, max_columns=10),
        spacing=10,
        run_spacing=10,
        child_aspect_ratio=0.65,
        padding=10,
    )
    output = ft.Text("输入关键词后搜索", size=14, selectable=True)
    state = {"keyword": "", "page_num": 1, "prev_url": None, "next_url": None}

    def update_grid_columns(e=None):
        new_count = runs_count_for_width(page.width, min_columns=2, max_columns=10)
        if grid.runs_count != new_count:
            grid.runs_count = new_count
            page.update()

    add_resize_handler = getattr(page, "fletviewer_add_resize_handler", None)
    if callable(add_resize_handler):
        add_resize_handler(update_grid_columns)

    def set_loading(text: str):
        btn.disabled = True
        prev_btn.disabled = True
        next_btn.disabled = True
        status.value = text
        if render_cards:
            grid.controls.clear()
        else:
            output.value = text
        page.update()

    def render_result(result):
        state["prev_url"] = result.prev_url
        state["next_url"] = result.next_url
        prev_btn.disabled = result.prev_url is None
        next_btn.disabled = result.next_url is None
        status.value = f"共 {len(result.comics)} 个画廊"
        if render_cards:
            grid.controls = [make_gallery_card(page, comic) for comic in result.comics]
        else:
            output.value = _result_to_json(result)

    def load(keyword: str | None = None, page_url: str | None = None):
        kw = (keyword if keyword is not None else state["keyword"]).strip()
        if not kw and not page_url:
            return
        if keyword is not None:
            state["keyword"] = kw
            state["page_num"] = 1
            page_label.value = "第 1 页"

        set_loading("搜索中...")

        def worker():
            try:
                log_debug("search", f"search start keyword={kw} page_url={page_url}")
                client = browser_session.get_eh_client(require_login=False)
                with Timer("search", f"search keyword={kw} page_url={page_url}"):
                    result = client.search(page_url=page_url) if page_url else client.search(keyword=kw)
                log_debug(
                    "search",
                    f"search result count={len(result.comics)} prev={result.prev_url} next={result.next_url}",
                )
                render_result(result)
            except Exception as ex:
                status.value = f"错误: {ex}"
                output.value = f"错误: {ex}"
                log_exception("search", f"search failed keyword={kw} page_url={page_url}: {ex}")
            finally:
                btn.disabled = False
                request_update(page)

        page.run_thread(worker)

    def on_search(e=None):
        load(keyword=query.value)

    def on_prev(e):
        if state["prev_url"]:
            state["page_num"] -= 1
            page_label.value = f"第 {state['page_num']} 页"
            load(page_url=state["prev_url"])

    def on_next(e):
        if state["next_url"]:
            state["page_num"] += 1
            page_label.value = f"第 {state['page_num']} 页"
            load(page_url=state["next_url"])

    query.on_submit = on_search
    btn.on_click = on_search
    prev_btn.on_click = on_prev
    next_btn.on_click = on_next

    result_content = grid if render_cards else ft.Container(
        content=ft.Column([output], scroll=ft.ScrollMode.AUTO),
        expand=True,
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        padding=16,
    )

    subtitle = "E-Hentai 画廊搜索" if render_cards else "E-Hentai 画廊搜索（JSON 调试模式）"
    return ft.Column(
        controls=[
            ft.Text("搜索", size=32, weight=ft.FontWeight.BOLD),
            ft.Text(subtitle, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Divider(),
            ft.Row([query, btn, status], spacing=12),
            result_content,
            ft.Divider(),
            ft.Row([prev_btn, page_label, next_btn], alignment=ft.MainAxisAlignment.CENTER, spacing=20),
        ],
        spacing=12,
        expand=True,
    )
