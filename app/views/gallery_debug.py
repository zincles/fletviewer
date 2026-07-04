import dataclasses
import json
from typing import Callable

import flet as ft

from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.storage import load_eh_config
from app.ui_update import request_update
from lib.provider.ehgrabber import EHentaiClient, SearchResult


def _comic_to_dict(comic):
    return dataclasses.asdict(comic)


def _result_to_json(result: SearchResult) -> str:
    data = {
        "count": len(result.comics),
        "prev_url": result.prev_url,
        "next_url": result.next_url,
        "comics": [_comic_to_dict(comic) for comic in result.comics],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def create_gallery_debug_view(
    *,
    title: str,
    subtitle: str,
    load_fn: Callable[[EHentaiClient, str | None], SearchResult],
    needs_login: bool = False,
) -> Callable[[ft.Page], ft.Control]:
    def factory(page: ft.Page) -> ft.Control:
        output = ft.Text("加载中...", size=14, selectable=True)
        refresh_btn = ft.Button("刷新", icon=ft.Icons.REFRESH)
        prev_btn = ft.Button("上一页", icon=ft.Icons.ARROW_BACK, disabled=True)
        next_btn = ft.Button("下一页", icon=ft.Icons.ARROW_FORWARD, disabled=True)
        page_label = ft.Text("第 1 页", size=14)
        state = {"page_num": 1, "prev_url": None, "next_url": None, "current_url": None}

        def load(page_url=None):
            log_debug("gallery_debug", f"{title} load requested page_url={page_url}")
            refresh_btn.disabled = True
            prev_btn.disabled = True
            next_btn.disabled = True
            output.value = "加载中..."
            page.update()

            def worker():
                try:
                    cfg = load_eh_config()
                    if needs_login and (not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash")):
                        output.value = "请先在账户页填写凭据"
                        return
                    client = browser_session.get_eh_client(require_login=needs_login)
                    with Timer("gallery_debug", f"{title} load_fn page_url={page_url}"):
                        result = load_fn(client, page_url)
                    state["prev_url"] = result.prev_url
                    state["next_url"] = result.next_url
                    state["current_url"] = page_url
                    prev_btn.disabled = result.prev_url is None
                    next_btn.disabled = result.next_url is None
                    output.value = _result_to_json(result)
                    log_debug("gallery_debug", f"{title} result count={len(result.comics)}")
                except Exception as ex:
                    output.value = f"错误: {ex}"
                    log_exception("gallery_debug", f"{title} worker failed: {ex}")
                finally:
                    refresh_btn.disabled = False
                    request_update(page)

            page.run_thread(worker)

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

        refresh_btn.on_click = lambda e: load(state["current_url"])
        prev_btn.on_click = on_prev
        next_btn.on_click = on_next
        load()

        return ft.Column(
            controls=[
                ft.Text(title, size=32, weight=ft.FontWeight.BOLD),
                ft.Text(f"{subtitle}（JSON 调试模式）", size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Divider(),
                ft.Row([refresh_btn, prev_btn, page_label, next_btn], spacing=12),
                ft.Container(
                    content=ft.Column([output], scroll=ft.ScrollMode.AUTO),
                    expand=True,
                    border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=8,
                    padding=16,
                ),
            ],
            spacing=16,
            expand=True,
        )

    return factory


def create_gallery_view(
    *,
    title: str,
    subtitle: str,
    load_fn: Callable[[EHentaiClient, str | None], SearchResult],
    needs_login: bool = False,
) -> Callable[[ft.Page], ft.Control]:
    from app.storage import should_render_gallery_cards
    from app.views.gallery_cards import create_gallery_cards_view

    if should_render_gallery_cards():
        return create_gallery_cards_view(
            title=title,
            subtitle=subtitle,
            load_fn=load_fn,
            needs_login=needs_login,
        )
    return create_gallery_debug_view(
        title=title,
        subtitle=subtitle,
        load_fn=load_fn,
        needs_login=needs_login,
    )
