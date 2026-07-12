import dataclasses
import json

import flet as ft

from app.browser_session import browser_session
from app.controls.masonry_gallery import MasonryGallery, MasonryItem
from app.debug_log import Timer, log_debug, log_exception
from app.grid_layout import runs_count_for_width
from app.storage import get_gallery_view_mode, should_render_gallery_cards
from app.toast import show_error_toast
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
    if get_gallery_view_mode() == "masonry":
        next_btn.text = "加载下一页内容"
        next_btn.icon = ft.Icons.EXPAND_MORE
    page_label = ft.Text("第 1 页", size=14)
    status = ft.Text("输入关键词后搜索", size=14, color=ft.Colors.ON_SURFACE_VARIANT)
    render_cards = should_render_gallery_cards()
    view_mode = get_gallery_view_mode()
    grid_spacing = 0
    masonry_gallery: MasonryGallery | None = None
    if view_mode == "list":
        gallery_results = ft.ListView(expand=True, spacing=8, padding=10)
    elif view_mode == "masonry":
        masonry_gallery = MasonryGallery(
            column_count=runs_count_for_width(page.width, min_columns=2, max_columns=10),
            spacing=grid_spacing,
        )
        gallery_results = ft.ListView(expand=True, padding=10, controls=[masonry_gallery])
    else:
        gallery_results = ft.GridView(
            expand=True,
            runs_count=runs_count_for_width(page.width, min_columns=2, max_columns=10),
            spacing=grid_spacing,
            run_spacing=grid_spacing,
            child_aspect_ratio=0.72,
            padding=10,
        )
    output = ft.Text("输入关键词后搜索", size=14, selectable=True)
    state = {
        "keyword": "",
        "page_num": 1,
        "prev_url": None,
        "next_url": None,
        "comics": [],
        "cards": [],
        "comic_ids": set(),
        "requested_urls": set(),
        "loading": False,
    }

    def update_grid_columns(e=None):
        if masonry_gallery is not None:
            new_count = runs_count_for_width(page.width, min_columns=2, max_columns=10)
            if masonry_gallery.set_column_count(new_count):
                page.update()
            return
        if not isinstance(gallery_results, ft.GridView):
            return
        new_count = runs_count_for_width(page.width, min_columns=2, max_columns=10)
        if gallery_results.runs_count != new_count:
            gallery_results.runs_count = new_count
            page.update()

    add_resize_handler = getattr(page, "fletviewer_add_resize_handler", None)
    if callable(add_resize_handler):
        add_resize_handler(update_grid_columns)

    def set_loading(text: str, *, preserve_results: bool = False):
        btn.disabled = True
        prev_btn.disabled = True
        next_btn.disabled = True
        status.value = text
        if render_cards and not preserve_results:
            if masonry_gallery is not None:
                masonry_gallery.set_items([])
            else:
                gallery_results.controls.clear()
        else:
            output.value = text
        page.update()

    def render_result(result, *, append: bool = False):
        state["prev_url"] = result.prev_url
        state["next_url"] = result.next_url
        prev_btn.disabled = result.prev_url is None
        next_btn.disabled = result.next_url is None
        status.value = ""
        incoming = [comic for comic in result.comics if comic.id not in state["comic_ids"]]
        if append:
            state["comics"].extend(incoming)
            state["cards"].extend(make_gallery_card(page, comic, mode=view_mode) for comic in incoming)
            state["page_num"] += 1
        else:
            state["comics"] = incoming
            state["cards"] = [make_gallery_card(page, comic, mode=view_mode) for comic in incoming]
            state["page_num"] = 1
        state["comic_ids"].update(comic.id for comic in incoming)
        page_label.value = f"已加载 {state['page_num']} 页" if state["page_num"] > 1 else "第 1 页"
        if render_cards:
            if masonry_gallery is not None:
                items = [
                    MasonryItem(card, comic.cover_aspect_ratio, key=comic.id)
                    for comic, card in zip(
                        incoming if append else state["comics"],
                        state["cards"][-len(incoming):] if append and incoming else ([] if append else state["cards"]),
                    )
                ]
                if append:
                    masonry_gallery.append_batch(items, update=True)
                else:
                    masonry_gallery.set_items(items)
            else:
                if append:
                    gallery_results.controls.extend(state["cards"][-len(incoming):] if incoming else [])
                else:
                    gallery_results.controls = list(state["cards"])
        else:
            output.value = _result_to_json(result)

    def load(keyword: str | None = None, page_url: str | None = None, *, append: bool = False):
        kw = (keyword if keyword is not None else state["keyword"]).strip()
        if not kw and not page_url:
            return
        request_key = page_url or f"search:{kw}"
        if state["loading"] or (append and request_key in state["requested_urls"]):
            return
        state["loading"] = True
        state["requested_urls"].add(request_key)
        set_reading_loading = getattr(page, "fletviewer_set_reading_loading", None)
        if callable(set_reading_loading):
            set_reading_loading("search", True)
        if keyword is not None:
            state["keyword"] = kw
            state["page_num"] = 1
            page_label.value = "第 1 页"
        if not append:
            state["comics"] = []
            state["cards"] = []
            state["comic_ids"] = set()
            state["requested_urls"] = {request_key}

        set_loading("" if append else "搜索中...", preserve_results=append)
        if append and view_mode == "masonry":
            next_btn.text = "加载中..."
            next_btn.icon = ft.Icons.HOURGLASS_TOP

        def worker():
            try:
                log_debug("搜索", f"开始搜索 关键词={kw} 页面URL={page_url}")
                client = browser_session.get_eh_client(require_login=False)
                with Timer("搜索", f"执行搜索 关键词={kw} 页面URL={page_url}"):
                    result = client.search(page_url=page_url) if page_url else client.search(keyword=kw)
                log_debug(
                    "搜索",
                    f"搜索结果 数量={len(result.comics)} 上一页={result.prev_url} 下一页={result.next_url}",
                )
                render_result(result, append=append)
            except Exception as ex:
                state["requested_urls"].discard(request_key)
                status.value = f"错误: {ex}"
                output.value = f"错误: {ex}"
                show_error_toast(page, "搜索加载失败", ex)
                log_exception("搜索", f"搜索失败 关键词={kw} 页面URL={page_url}：{ex}")
            finally:
                state["loading"] = False
                if callable(set_reading_loading):
                    set_reading_loading("search", False)
                btn.disabled = False
                if view_mode == "masonry":
                    next_btn.text = "加载下一页内容"
                    next_btn.icon = ft.Icons.EXPAND_MORE
                if append and masonry_gallery is not None:
                    next_btn.update()
                    btn.update()
                else:
                    request_update(page)

        page.run_thread(worker)

    def on_search(e=None):
        load(keyword=query.value)

    def run_search(keyword: str) -> None:
        query.value = keyword
        load(keyword=keyword)

    page.fletviewer_run_search = run_search

    def on_prev(e):
        if state["prev_url"]:
            state["page_num"] -= 1
            page_label.value = f"第 {state['page_num']} 页"
            load(page_url=state["prev_url"])

    def on_next(e):
        if state["next_url"]:
            load(page_url=state["next_url"], append=True)

    query.on_submit = on_search
    btn.on_click = on_search
    prev_btn.on_click = on_prev
    next_btn.on_click = on_next

    result_content = gallery_results if render_cards else ft.Container(
        content=ft.Column([output], scroll=ft.ScrollMode.AUTO),
        expand=True,
        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        padding=16,
    )

    pagination_controls = (
        [next_btn]
        if view_mode == "masonry"
        else [prev_btn, page_label, next_btn]
    )

    return ft.Column(
        controls=[
            ft.Row([query, btn, status], spacing=12),
            result_content,
            ft.Divider(),
            ft.Row(pagination_controls, alignment=ft.MainAxisAlignment.CENTER, spacing=20),
        ],
        spacing=12,
        expand=True,
    )
