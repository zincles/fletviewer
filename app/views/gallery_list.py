import dataclasses
import json

import flet as ft

from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.storage import load_eh_config
from app.ui_update import request_update


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


def _make_loader(call_fn, needs_login=False):
    """返回一个 (load, output, btn) 元组，供 create_view 使用。"""

    def load(output, btn, page):
        btn.disabled = True
        output.value = "加载中..."
        page.update()

        def worker():
            try:
                log_debug("gallery_list", f"load start needs_login={needs_login}")
                cfg = load_eh_config()
                if needs_login:
                    if not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash"):
                        log_debug("gallery_list", "missing credentials")
                        output.value = "请先在账户页填写凭据"
                        return
                client = browser_session.get_eh_client(require_login=needs_login)
                with Timer("gallery_list", "call_fn"):
                    result = call_fn(client)
                log_debug("gallery_list", f"result count={len(result.comics)} next={result.next_url}")
                output.value = _result_to_json(result)
            except Exception as ex:
                output.value = f"错误: {ex}"
                log_exception("gallery_list", f"load failed: {ex}")
            finally:
                btn.disabled = False
                request_update(page)

        page.run_thread(worker)

    return load


def create_view(title, subtitle, call_fn, needs_login=False):
    """通用列表页工厂。

    Args:
        title: 页面标题
        subtitle: 副标题
        call_fn: 接收 EHentaiClient、返回 SearchResult 的函数
        needs_login: 是否需要登录
    """
    def factory(page: ft.Page) -> ft.Control:
        output = ft.Text("加载中...", size=14, selectable=True)
        btn = ft.Button("刷新", icon=ft.Icons.REFRESH)
        loader = _make_loader(call_fn, needs_login)

        btn.on_click = lambda e: loader(output, btn, page)
        loader(output, btn, page)

        return ft.Column(
            controls=[
                ft.Text(title, size=32, weight=ft.FontWeight.BOLD),
                ft.Text(subtitle, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Divider(),
                btn,
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
