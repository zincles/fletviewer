from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse


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


class PixivWebClient(PixivClient):
    """Pixiv 网页 AJAX client backed by a user-imported browser Cookie."""

    base_url = "https://www.pixiv.net"

    def __init__(self, *, transport, cookie: str = "", user_id: str = "", log_debug=None):
        super().__init__(log_debug=log_debug)
        self.transport = transport
        self.cookie = self._normalize_cookie(cookie)
        self.user_id = user_id.strip() or self._user_id_from_cookie(self.cookie)

    @staticmethod
    def _normalize_cookie(cookie: str) -> str:
        value = cookie.strip()
        if value.lower().startswith("cookie:"):
            value = value.split(":", 1)[1].strip()
        return value

    @staticmethod
    def _user_id_from_cookie(cookie: str) -> str:
        match = re.search(r"(?:^|;\s*)PHPSESSID=(\d+)(?:_|%5F)", cookie, flags=re.IGNORECASE)
        return match.group(1) if match else ""

    def is_logged_in(self) -> bool:
        return bool(self.cookie)

    def _headers(self, *, referer: str = "") -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer or f"{self.base_url}/",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.user_id:
            headers["X-User-Id"] = self.user_id
        return headers

    def _get_json(self, url: str, *, params: dict[str, Any] | None = None, referer: str = "") -> dict[str, Any]:
        try:
            response = self.transport.get(url, params=params, headers=self._headers(referer=referer), timeout=30)
            if response.status_code in {401, 403}:
                raise PixivProviderError("Pixiv 拒绝请求。请在设置中重新导入已登录浏览器的 Cookie。")
            response.raise_for_status()
            raw = response.json()
        except PixivProviderError:
            raise
        except Exception as ex:
            raise PixivProviderError(f"Pixiv 请求失败: {ex}") from ex
        if not isinstance(raw, dict):
            raise PixivProviderError("Pixiv 返回了无法识别的 JSON 响应。")
        if raw.get("error"):
            raise PixivProviderError(str(raw.get("message") or "Pixiv 网页 API 返回错误。"))
        return raw

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "")

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _illust(self, item: dict[str, Any]) -> PixivIllust:
        user_raw = item.get("user") if isinstance(item.get("user"), dict) else {}
        user_id = item.get("userId") or item.get("user_id") or user_raw.get("id")
        tags_raw = item.get("tags")
        if isinstance(tags_raw, dict):
            tags_raw = tags_raw.get("tags", [])
        tags = [self._text(tag.get("tag") or tag.get("name")) if isinstance(tag, dict) else self._text(tag) for tag in tags_raw or []]
        image_urls = item.get("urls") if isinstance(item.get("urls"), dict) else item.get("image_urls", {})
        image_urls = {str(key): self._text(value) for key, value in image_urls.items()}
        if item.get("url") and "square_medium" not in image_urls:
            image_urls["square_medium"] = self._text(item.get("url"))
        for camel_key, snake_key in (("squareMedium", "square_medium"), ("regular", "medium"), ("original", "large")):
            if camel_key in image_urls and snake_key not in image_urls:
                image_urls[snake_key] = image_urls[camel_key]
        return PixivIllust(
            id=self._text(item.get("id") or item.get("illustId")),
            title=self._text(item.get("title")),
            caption=self._text(item.get("description") or item.get("caption")),
            type=self._text(item.get("illustType") or item.get("type") or "illust"),
            page_count=self._int(item.get("pageCount") or item.get("page_count") or 1),
            width=self._int(item.get("width")), height=self._int(item.get("height")),
            restrict=self._int(item.get("restrict")), x_restrict=self._int(item.get("xRestrict") or item.get("x_restrict")),
            total_view=self._int(item.get("viewCount") or item.get("total_view")),
            total_bookmarks=self._int(item.get("bookmarkCount") or item.get("total_bookmarks")),
            is_bookmarked=bool(item.get("bookmarkData") or item.get("is_bookmarked")),
            create_date=self._text(item.get("createDate") or item.get("create_date")),
            user=PixivUser(self._text(user_id), self._text(item.get("userName") or user_raw.get("name")), self._text(user_raw.get("account")), self._text(item.get("profileImageUrl") or user_raw.get("profile_image_urls", {}).get("medium") if isinstance(user_raw.get("profile_image_urls"), dict) else "")),
            tags=[tag for tag in tags if tag], image_urls=image_urls, raw=item,
        )

    def search_illusts(self, word: str, *, sort: str = "date_desc", next_url: str | None = None) -> PixivSearchResult:
        page = 1
        if next_url:
            url = next_url
            params = None
        else:
            url = f"{self.base_url}/ajax/search/artworks/{word}"
            params = {"word": word, "order": "date_d" if sort == "date_desc" else sort, "mode": "all", "p": page, "s_mode": "s_tag_full", "type": "all", "lang": "zh"}
        raw = self._get_json(url, params=params, referer=f"{self.base_url}/tags/{word}/artworks")
        body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
        feed = body.get("illustManga") if isinstance(body.get("illustManga"), dict) else {}
        items = feed.get("data") if isinstance(feed.get("data"), list) else []
        return PixivSearchResult([self._illust(item) for item in items if isinstance(item, dict)], self._text(body.get("next") or "") or None, query=word)

    def get_recommended(self, *, next_url: str | None = None) -> PixivSearchResult:
        if next_url:
            raise PixivProviderError("Pixiv 网页发现流当前未提供可复用的下一页游标。")
        raw = self._get_json(
            f"{self.base_url}/ajax/illust/discovery",
            params={"mode": "all", "limit": 100},
            referer=f"{self.base_url}/",
        )
        body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
        items = body.get("illusts") if isinstance(body.get("illusts"), list) else []
        return PixivSearchResult([self._illust(item) for item in items if isinstance(item, dict)], query="discovery")

    def get_bookmarks(self, *, user_id: str = "me", restrict: str = "public", next_url: str | None = None) -> PixivSearchResult:
        if not self.cookie:
            raise PixivProviderError("Pixiv 收藏需要已登录浏览器的 Cookie。")
        target_user_id = self.user_id if user_id == "me" else user_id.strip()
        if not target_user_id:
            raise PixivProviderError("无法从 Pixiv Cookie 识别 User ID，请在设置中手动填写。")
        limit = 48
        if next_url:
            url = next_url
            params = None
            offset = self._int(parse_qs(urlparse(next_url).query).get("offset", [0])[0])
        else:
            url = f"{self.base_url}/ajax/user/{target_user_id}/illusts/bookmarks"
            params = {"tag": "", "offset": 0, "limit": limit, "rest": "hide" if restrict == "private" else "show", "lang": "zh"}
            offset = 0
        raw = self._get_json(url, params=params, referer=f"{self.base_url}/users/{target_user_id}/bookmarks/artworks")
        body = raw.get("body") if isinstance(raw.get("body"), dict) else {}
        items = body.get("works") if isinstance(body.get("works"), list) else []
        total = self._int(body.get("total"))
        next_offset = offset + limit
        next_bookmarks_url = None
        if items and next_offset < total:
            query = urlencode({"tag": "", "offset": next_offset, "limit": limit, "rest": "hide" if restrict == "private" else "show", "lang": "zh"})
            next_bookmarks_url = f"{self.base_url}/ajax/user/{target_user_id}/illusts/bookmarks?{query}"
        return PixivSearchResult(
            [self._illust(item) for item in items if isinstance(item, dict)],
            next_bookmarks_url,
            query="bookmarks",
        )

    def get_ranking(self, *, mode: str = "day", date: str = "", next_url: str | None = None) -> PixivRankingResult:
        if next_url:
            raw = self._get_json(next_url, referer=f"{self.base_url}/ranking.php")
        else:
            web_mode = {"day": "daily", "week": "weekly", "month": "monthly"}.get(mode, mode)
            params = {"mode": web_mode, "content": "all", "p": 1, "format": "json"}
            if date:
                params["date"] = date.replace("-", "")
            raw = self._get_json(f"{self.base_url}/ranking.php", params=params, referer=f"{self.base_url}/ranking.php")
        items = raw.get("contents") if isinstance(raw.get("contents"), list) else []
        return PixivRankingResult(mode, date, [self._illust(item) for item in items if isinstance(item, dict)])

    def get_illust_detail(self, illust_id: str) -> PixivIllust:
        raw = self._get_json(f"{self.base_url}/ajax/illust/{illust_id}", referer=f"{self.base_url}/artworks/{illust_id}")
        body = raw.get("body")
        if not isinstance(body, dict):
            raise PixivProviderError(f"Pixiv 作品不存在或不可访问: {illust_id}")
        return self._illust(body)

    def get_illust_pages(self, illust_id: str) -> list[dict[str, str]]:
        raw = self._get_json(f"{self.base_url}/ajax/illust/{illust_id}/pages", params={"lang": "zh"}, referer=f"{self.base_url}/artworks/{illust_id}")
        body = raw.get("body") if isinstance(raw.get("body"), list) else []
        return [
            {str(key): self._text(value) for key, value in item.get("urls", {}).items()}
            for item in body if isinstance(item, dict) and isinstance(item.get("urls"), dict)
        ]
