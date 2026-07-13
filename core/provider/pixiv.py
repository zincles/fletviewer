from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PixivUser:
    id: str
    name: str
    account: str = ""
    avatar_url: str = ""
    is_followed: bool = False


@dataclass(slots=True)
class PixivIllust:
    id: str
    title: str
    caption: str = ""
    type: str = "illust"  # illust | manga | ugoira
    page_count: int = 1
    width: int = 0
    height: int = 0
    restrict: int = 0
    x_restrict: int = 0  # 0=all, 1=r18, 2=r18g
    total_view: int = 0
    total_bookmarks: int = 0
    is_bookmarked: bool = False
    create_date: str = ""
    user: PixivUser | None = None
    tags: list[str] = field(default_factory=list)
    image_urls: dict[str, str] = field(default_factory=dict)
    meta_pages: list[dict[str, str]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def cover_url(self) -> str:
        return (
            self.image_urls.get("square_medium")
            or self.image_urls.get("medium")
            or self.image_urls.get("large")
            or ""
        )

    @property
    def is_r18(self) -> bool:
        return self.x_restrict >= 1


@dataclass(slots=True)
class PixivSearchResult:
    illusts: list[PixivIllust] = field(default_factory=list)
    next_url: str | None = None
    prev_url: str | None = None
    query: str = ""


@dataclass(slots=True)
class PixivRankingResult:
    mode: str
    date: str
    illusts: list[PixivIllust] = field(default_factory=list)
    next_url: str | None = None


class PixivProviderError(RuntimeError):
    """Pixiv Provider 通用错误。"""


class PixivNotImplementedError(PixivProviderError):
    """接口已预留但尚未实现。"""


class PixivClient:
    """缺省 Pixiv Provider。

    当前只提供稳定接口与数据模型，不实现真实网络协议。
    后续可替换为官方 API / 直连 transport，而不改 UI 调用面。
    """

    provider_id = "pixiv"
    display_name = "Pixiv"

    def __init__(self, *, access_token: str = "", refresh_token: str = "", log_debug=None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._log_debug = log_debug or (lambda _area, _message: None)

    def _not_ready(self, feature: str) -> None:
        self._log_debug("pixiv", f"{feature} 尚未实现")
        raise PixivNotImplementedError(
            f"Pixiv「{feature}」尚未实现。当前仅预留 Provider 与界面骨架。"
        )

    # --- auth ---
    def login(self, username: str = "", password: str = "") -> dict[str, Any]:
        self._not_ready("登录")

    def refresh_auth(self) -> dict[str, Any]:
        self._not_ready("刷新登录")

    def is_logged_in(self) -> bool:
        return bool(self.access_token or self.refresh_token)

    # --- feeds ---
    def get_recommended(self, *, next_url: str | None = None) -> PixivSearchResult:
        self._not_ready("推荐")

    def get_following(self, *, restrict: str = "public", next_url: str | None = None) -> PixivSearchResult:
        self._not_ready("关注动态")

    def get_ranking(self, *, mode: str = "day", date: str = "", next_url: str | None = None) -> PixivRankingResult:
        self._not_ready("排行榜")

    def get_bookmarks(self, *, user_id: str = "me", restrict: str = "public", next_url: str | None = None) -> PixivSearchResult:
        self._not_ready("收藏")

    def get_history_placeholder(self) -> PixivSearchResult:
        """本地历史接入前的占位接口。"""
        return PixivSearchResult(illusts=[], query="history")

    # --- search ---
    def search_illusts(self, word: str, *, sort: str = "date_desc", next_url: str | None = None) -> PixivSearchResult:
        self._not_ready("搜索作品")

    def search_users(self, word: str, *, next_url: str | None = None) -> list[PixivUser]:
        self._not_ready("搜索用户")

    # --- detail ---
    def get_illust_detail(self, illust_id: str) -> PixivIllust:
        self._not_ready("作品详情")

    def get_user_detail(self, user_id: str) -> PixivUser:
        self._not_ready("用户详情")

    def get_user_illusts(self, user_id: str, *, next_url: str | None = None) -> PixivSearchResult:
        self._not_ready("用户作品")

    # --- actions ---
    def bookmark_add(self, illust_id: str, *, restrict: str = "public") -> None:
        self._not_ready("收藏作品")

    def bookmark_delete(self, illust_id: str) -> None:
        self._not_ready("取消收藏")

    def follow_user(self, user_id: str, *, restrict: str = "public") -> None:
        self._not_ready("关注用户")

    def unfollow_user(self, user_id: str) -> None:
        self._not_ready("取消关注")
