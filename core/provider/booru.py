from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree


@dataclass(slots=True)
class ImageVariant:
    url: str = ""
    width: int = 0
    height: int = 0


@dataclass(slots=True)
class BooruPost:
    provider: str
    id: int | str
    page_url: str = ""
    original: ImageVariant = field(default_factory=ImageVariant)
    sample: ImageVariant = field(default_factory=ImageVariant)
    preview: ImageVariant = field(default_factory=ImageVariant)
    tags: dict[str, list[str]] = field(default_factory=dict)
    rating: str = ""
    score: int = 0
    source: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    @property
    def thumbnail_url(self) -> str:
        return self.preview.url or self.sample.url or self.original.url

    @property
    def image_url(self) -> str:
        return self.original.url or self.sample.url or self.preview.url


@dataclass(slots=True)
class BooruSearchResult:
    provider: str
    posts: list[BooruPost] = field(default_factory=list)
    query: str = ""
    page: int | str | None = None
    next_page: int | str | None = None
    total_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


@dataclass(slots=True)
class TagSuggestion:
    tag: str
    type: str = "general"
    count: int = 0
    raw: Any = None


class BooruProviderError(RuntimeError):
    """Booru Provider 通用错误。"""


class BooruNotImplementedError(BooruProviderError):
    """接口已预留但尚未绑定实现。"""


class BooruAccessDeniedError(BooruProviderError):
    """站点返回 403；调用方可提示认证或网络限制。"""


class BooruResponseError(BooruProviderError):
    """Provider 响应无法解析。"""


class BooruClient:
    """可由外部库 adapter 替换的缺省 Booru Provider。"""

    def __init__(self, provider_id: str, display_name: str, *, log_debug=None):
        self.provider_id = provider_id
        self.display_name = display_name
        self._log_debug = log_debug or (lambda _area, _message: None)

    def _not_ready(self, feature: str) -> None:
        self._log_debug("booru", f"{self.display_name} {feature} 尚未实现")
        raise BooruNotImplementedError(
            f"{self.display_name}「{feature}」尚未绑定 Provider 实现。"
        )

    def search_posts(
        self,
        query: str = "",
        *,
        page: int | str | None = None,
        limit: int = 40,
    ) -> BooruSearchResult:
        self._not_ready("搜索")

    def get_post(self, post_id: int | str) -> BooruPost:
        self._not_ready("作品详情")

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        self._not_ready("标签补全")


class HttpBooruClient(BooruClient):
    base_url = ""
    first_page = 1
    max_limit = 100

    def __init__(self, provider_id: str, display_name: str, *, transport, log_debug=None):
        super().__init__(provider_id, display_name, log_debug=log_debug)
        self.transport = transport

    def _get(self, url: str, **kwargs):
        try:
            response = self.transport.get(url, timeout=30, **kwargs)
            if response.status_code in {401, 403}:
                raise BooruAccessDeniedError(
                    f"{self.display_name} 返回 HTTP {response.status_code}。请检查 API 凭据或当前网络访问限制。"
                )
            response.raise_for_status()
            return response
        except BooruProviderError:
            raise
        except Exception as ex:
            raise BooruProviderError(f"{self.display_name} 请求失败: {ex}") from ex

    def _limit(self, value: int) -> int:
        return max(1, min(int(value), self.max_limit))

    def _absolute(self, value: Any) -> str:
        text = str(value or "")
        if text.startswith("//"):
            return "https:" + text
        return text if text.startswith(("http://", "https://")) else urljoin(self.base_url + "/", text)

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _tags(value: Any) -> list[str]:
        return [tag for tag in str(value or "").split() if tag]


class DanbooruClient(HttpBooruClient):
    base_url = "https://danbooru.donmai.us"
    max_limit = 200

    def __init__(self, *, transport, login: str = "", api_key: str = "", log_debug=None):
        super().__init__("danbooru", "Danbooru", transport=transport, log_debug=log_debug)
        self.login = login
        self.api_key = api_key

    def search_posts(self, query: str = "", *, page=None, limit: int = 40) -> BooruSearchResult:
        page = self.first_page if page is None else int(page)
        params = {"tags": query.strip(), "page": page, "limit": self._limit(limit)}
        if self.login:
            params["login"] = self.login
        if self.api_key:
            params["api_key"] = self.api_key
        raw = self._get(f"{self.base_url}/posts.json", params=params).json()
        if not isinstance(raw, list):
            raise BooruResponseError("Danbooru 返回了非列表响应")
        posts = [post for item in raw if isinstance(item, dict) and (post := self._post(item))]
        return BooruSearchResult("danbooru", posts, query, page, page + 1 if len(raw) >= params["limit"] else None, raw=raw)

    def _post(self, item: dict[str, Any]) -> BooruPost | None:
        original = self._absolute(item.get("file_url"))
        sample = self._absolute(item.get("large_file_url"))
        if not original and not sample:
            return None
        post_id = item.get("id", "")
        return BooruPost(
            "danbooru", post_id, f"{self.base_url}/posts/{post_id}",
            ImageVariant(original or sample, self._int(item.get("image_width")), self._int(item.get("image_height"))),
            ImageVariant(sample), ImageVariant(self._absolute(item.get("preview_file_url"))),
            {key: self._tags(item.get(f"tag_string_{key}")) for key in ("general", "artist", "character", "copyright", "meta")},
            str(item.get("rating") or ""), self._int(item.get("score")),
            [str(item["source"])] if item.get("source") else [], raw=item,
        )


class GelbooruClient(HttpBooruClient):
    base_url = "https://gelbooru.com"
    first_page = 0

    def __init__(self, *, transport, user_id: str = "", api_key: str = "", log_debug=None):
        super().__init__("gelbooru", "Gelbooru", transport=transport, log_debug=log_debug)
        self.user_id = user_id
        self.api_key = api_key

    def _auth_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.user_id:
            params["user_id"] = self.user_id
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def search_posts(self, query: str = "", *, page=None, limit: int = 40) -> BooruSearchResult:
        page = self.first_page if page is None else int(page)
        limit = self._limit(limit)
        params = {"page": "dapi", "s": "post", "q": "index", "json": "1", "tags": query.strip(), "pid": page, "limit": limit}
        params.update(self._auth_params())
        raw = self._get(f"{self.base_url}/index.php", params=params).json()
        items, total = self._parse_posts(raw)
        posts = [self._post(item) for item in items if isinstance(item, dict)]
        return BooruSearchResult("gelbooru", posts, query, page, page + 1 if len(items) >= limit else None, total, raw=raw)

    def get_post(self, post_id: int | str) -> BooruPost:
        params = {"page": "dapi", "s": "post", "q": "index", "json": "1", "id": post_id}
        params.update(self._auth_params())
        raw = self._get(f"{self.base_url}/index.php", params=params).json()
        items, _total = self._parse_posts(raw)
        if not items:
            raise BooruResponseError(f"Gelbooru 作品不存在: {post_id}")
        return self._post(items[0])

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        params = {
            "page": "dapi", "s": "tag", "q": "index", "json": "1",
            "name_pattern": f"{query.strip()}%", "limit": self._limit(limit),
            "order": "DESC", "orderby": "count",
        }
        params.update(self._auth_params())
        raw = self._get(f"{self.base_url}/index.php", params=params).json()
        items = raw.get("tag", []) if isinstance(raw, dict) else raw
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise BooruResponseError("Gelbooru 返回了无法识别的标签响应")
        type_names = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
        return [
            TagSuggestion(
                tag=str(item.get("name") or ""),
                type=type_names.get(self._int(item.get("type")), "general"),
                count=self._int(item.get("count")),
                raw=item,
            )
            for item in items
            if isinstance(item, dict) and item.get("name")
        ]

    def _parse_posts(self, raw: Any) -> tuple[list[dict[str, Any]], int | None]:
        attrs = raw.get("@attributes", {}) if isinstance(raw, dict) else {}
        items = raw.get("post", []) if isinstance(raw, dict) else raw
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise BooruResponseError("Gelbooru 返回了无法识别的响应")
        total = self._int(attrs.get("count")) if attrs.get("count") is not None else None
        return items, total

    def _post(self, item: dict[str, Any]) -> BooruPost:
        post_id = item.get("id", "")
        original = self._absolute(item.get("file_url"))
        return BooruPost(
            "gelbooru", post_id, f"{self.base_url}/index.php?page=post&s=view&id={post_id}",
            ImageVariant(original, self._int(item.get("width")), self._int(item.get("height"))),
            ImageVariant(self._absolute(item.get("sample_url")), self._int(item.get("sample_width")), self._int(item.get("sample_height"))),
            ImageVariant(self._absolute(item.get("preview_url")), self._int(item.get("preview_width")), self._int(item.get("preview_height"))),
            {"general": self._tags(item.get("tags"))}, str(item.get("rating") or ""), self._int(item.get("score")),
            [str(item["source"])] if item.get("source") else [],
            metadata={
                "md5": str(item.get("md5") or ""),
                "file_ext": str(item.get("image") or original).rsplit(".", 1)[-1].lower() if original else "",
                "owner": str(item.get("owner") or ""),
                "created_at": str(item.get("created_at") or ""),
                "has_notes": bool(item.get("has_notes")),
                "has_comments": bool(item.get("has_comments")),
            },
            raw=item,
        )


class SafebooruClient(HttpBooruClient):
    base_url = "https://safebooru.org"
    first_page = 0

    def __init__(self, *, transport, log_debug=None):
        super().__init__("safebooru", "Safebooru", transport=transport, log_debug=log_debug)

    def search_posts(self, query: str = "", *, page=None, limit: int = 40) -> BooruSearchResult:
        page = self.first_page if page is None else int(page)
        limit = self._limit(limit)
        response = self._get(f"{self.base_url}/index.php", params={"page": "dapi", "s": "post", "q": "index", "tags": query.strip(), "pid": page, "limit": limit})
        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as ex:
            raise BooruResponseError(f"Safebooru XML 解析失败: {ex}") from ex
        posts = [self._post(item.attrib) for item in root.findall("post")]
        total = self._int(root.attrib.get("count")) if "count" in root.attrib else None
        return BooruSearchResult("safebooru", posts, query, page, page + 1 if len(posts) >= limit else None, total, raw=response.text)

    def _post(self, item: dict[str, Any]) -> BooruPost:
        post_id = item.get("id", "")
        return BooruPost(
            "safebooru", post_id, f"{self.base_url}/index.php?page=post&s=view&id={post_id}",
            ImageVariant(self._absolute(item.get("file_url")), self._int(item.get("width")), self._int(item.get("height"))),
            ImageVariant(self._absolute(item.get("sample_url"))), ImageVariant(self._absolute(item.get("preview_url"))),
            {"general": self._tags(item.get("tags"))}, str(item.get("rating") or ""), self._int(item.get("score")),
            [str(item["source"])] if item.get("source") else [], raw=dict(item),
        )


BOORU_PROVIDERS = {
    "safebooru": "Safebooru",
    "gelbooru": "Gelbooru",
    "danbooru": "Danbooru",
}
