import dataclasses
import json
import threading

import flet as ft

from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception


def _comic_to_dict(c):
    return dataclasses.asdict(c)


def _result_to_json(result):
    comics = [_comic_to_dict(c) for c in result.comics]
    data = {
        "count": len(comics),
        "next_url": result.next_url,
        "comics": comics,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def create_view(page: ft.Page) -> ft.Control:
    query = ft.TextField(
        label="搜索关键词",
        hint_text="例如: blue archive",
        width=500,
        autofocus=True,
        on_submit=lambda e: do_search(),
    )
    btn = ft.Button("搜索", icon=ft.Icons.SEARCH, on_click=lambda e: do_search())
    output = ft.Text("输入关键词后搜索", size=14, selectable=True)

    def do_search():
        kw = query.value.strip()
        if not kw:
            return
        btn.disabled = True
        output.value = "搜索中..."
        page.update()

        def worker():
            try:
                log_debug("search", f"search start keyword={kw}")
                client = browser_session.get_eh_client(require_login=False)
                with Timer("search", f"search keyword={kw}"):
                    result = client.search(keyword=kw)
                log_debug("search", f"search result count={len(result.comics)} next={result.next_url}")
                output.value = _result_to_json(result)
            except Exception as ex:
                output.value = f"错误: {ex}"
                log_exception("search", f"search failed keyword={kw}: {ex}")
            finally:
                btn.disabled = False
                page.update()

        threading.Thread(target=worker, daemon=True).start()

    return ft.Column(
        controls=[
            ft.Text("搜索", size=32, weight=ft.FontWeight.BOLD),
            ft.Text("E-Hentai 画廊搜索", size=16, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Divider(),
            ft.Row([query, btn], spacing=12),
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
