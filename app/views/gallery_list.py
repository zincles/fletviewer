import dataclasses
import json

import flet as ft

from app.browser_session import browser_session
from app.debug_log import Timer, log_debug, log_exception
from app.storage import load_eh_config
from app.toast import show_error_toast, show_toast
from app.ui_update import request_update


def _comic_to_dict(c):
    """把 Comic dataclass 转为字典。"""
    return dataclasses.asdict(c)


def _result_to_json(result):
    """把 SearchResult 格式化为 JSON 调试文本。"""
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
                log_debug("画廊列表", f"开始加载 需要登录={needs_login}")
                cfg = load_eh_config()
                if needs_login:
                    if not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash"):
                        log_debug("画廊列表", "缺少登录凭据")
                        output.value = "请先在账户页填写凭据"
                        show_toast(page, "请先在账户页填写凭据")
                        return
                client = browser_session.get_eh_client(require_login=needs_login)
                with Timer("画廊列表", "调用加载函数"):
                    result = call_fn(client)
                log_debug("画廊列表", f"结果数量={len(result.comics)} 下一页={result.next_url}")
                output.value = _result_to_json(result)
            except Exception as ex:
                output.value = f"错误: {ex}"
                show_error_toast(page, "画廊列表加载失败", ex)
                log_exception("画廊列表", f"加载失败：{ex}")
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
        """创建通用 JSON 列表页面实例。"""
        output = ft.Text("加载中...", size=14, selectable=True)
        btn = ft.Button("刷新", icon=ft.Icons.REFRESH)
        loader = _make_loader(call_fn, needs_login)

        btn.on_click = lambda e: loader(output, btn, page)
        loader(output, btn, page)

        return ft.Column(
            controls=[
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
