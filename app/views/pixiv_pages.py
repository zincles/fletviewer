from __future__ import annotations

import flet as ft

from app.pixiv_session import get_pixiv_client
from app.toast import show_toast
from core.provider.pixiv import PixivNotImplementedError


def _placeholder_page(
    page: ft.Page,
    *,
    title: str,
    subtitle: str,
    icon,
    bullets: list[str],
    action_label: str,
    action_feature: str,
) -> ft.Control:
    status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)

    def try_call(_e=None):
        client = get_pixiv_client()
        try:
            if action_feature == "recommended":
                client.get_recommended()
            elif action_feature == "following":
                client.get_following()
            elif action_feature == "ranking":
                client.get_ranking()
            elif action_feature == "bookmarks":
                client.get_bookmarks()
            elif action_feature == "search":
                client.search_illusts("test")
            elif action_feature == "history":
                result = client.get_history_placeholder()
                status.value = f"历史占位可用，当前 {len(result.illusts)} 条。"
                status.color = ft.Colors.PRIMARY
                page.update()
                return
            else:
                raise PixivNotImplementedError(action_feature)
        except PixivNotImplementedError as ex:
            status.value = str(ex)
            status.color = ft.Colors.ON_SURFACE_VARIANT
            show_toast(page, "Pixiv 接口尚未实现")
            page.update()

    return ft.Container(
        expand=True,
        padding=ft.Padding(16, 16, 16, 96),
        content=ft.Column(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(icon, size=40, color=ft.Colors.PRIMARY),
                            ft.Text(title, size=26, weight=ft.FontWeight.BOLD),
                            ft.Text(subtitle, size=14, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
                        ],
                        spacing=8,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=22,
                    border_radius=18,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                    border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                ),
                ft.Text("预留能力", size=16, weight=ft.FontWeight.W_600),
                *[
                    ft.Container(
                        content=ft.ListTile(
                            leading=ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color=ft.Colors.PRIMARY),
                            title=ft.Text(item),
                            dense=True,
                        ),
                        border=ft.border.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                        border_radius=12,
                    )
                    for item in bullets
                ],
                ft.Row(
                    [ft.FilledButton(action_label, icon=ft.Icons.PLAY_ARROW, on_click=try_call)],
                    alignment=ft.MainAxisAlignment.START,
                ),
                status,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )


def create_home_view(page: ft.Page) -> ft.Control:
    return _placeholder_page(
        page,
        title="Pixiv 推荐",
        subtitle="推荐流入口。当前为 Provider 缺省骨架，不发起真实网络请求。",
        icon=ft.Icons.HOME,
        bullets=["推荐插画瀑布流", "限制模式过滤", "下拉刷新 / 分页"],
        action_label="尝试加载推荐",
        action_feature="recommended",
    )


def create_following_view(page: ft.Page) -> ft.Control:
    return _placeholder_page(
        page,
        title="Pixiv 关注",
        subtitle="关注画师更新流。后续接入 following illust feed。",
        icon=ft.Icons.FAVORITE,
        bullets=["公开/私人关注", "最新作品流", "未读更新提示"],
        action_label="尝试加载关注",
        action_feature="following",
    )


def create_ranking_view(page: ft.Page) -> ft.Control:
    return _placeholder_page(
        page,
        title="Pixiv 排行榜",
        subtitle="日榜 / 周榜 / 月榜等排行入口。",
        icon=ft.Icons.LEADERBOARD,
        bullets=["日/周/月模式", "日期选择", "R18 排行开关"],
        action_label="尝试加载排行",
        action_feature="ranking",
    )


def create_bookmarks_view(page: ft.Page) -> ft.Control:
    return _placeholder_page(
        page,
        title="Pixiv 收藏",
        subtitle="用户收藏作品列表。",
        icon=ft.Icons.BOOKMARK,
        bullets=["公开/私人收藏", "标签筛选", "取消收藏"],
        action_label="尝试加载收藏",
        action_feature="bookmarks",
    )


def create_search_view(page: ft.Page) -> ft.Control:
    return _placeholder_page(
        page,
        title="Pixiv 搜索",
        subtitle="作品、用户、标签搜索入口。",
        icon=ft.Icons.SEARCH,
        bullets=["作品搜索", "用户搜索", "标签补全"],
        action_label="尝试搜索",
        action_feature="search",
    )


def create_history_view(page: ft.Page) -> ft.Control:
    return _placeholder_page(
        page,
        title="Pixiv 历史",
        subtitle="后续复用应用历史仓库，按 provider=pixiv 过滤。",
        icon=ft.Icons.HISTORY,
        bullets=["本地浏览历史", "按用户/作品跳转", "清空历史"],
        action_label="检查历史占位",
        action_feature="history",
    )
