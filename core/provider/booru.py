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

    @property
    def all_tags(self) -> list[str]:
        return list(dict.fromkeys(tag for values in self.tags.values() for tag in values))

    def tags_for(self, tag_type: str = "general") -> list[str]:
        return list(self.tags.get(tag_type, []))


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


@dataclass(frozen=True, slots=True)
class BooruProviderSpec:
    id: str
    display_name: str
    protocol: str
    base_url: str
    supports_detail: bool = True
    supports_tag_suggestions: bool = False


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

    def _json(self, url: str, **kwargs) -> Any:
        response = self._get(url, **kwargs)
        try:
            return response.json()
        except (TypeError, ValueError) as ex:
            content_type = response.headers.get("Content-Type", "")
            raise BooruResponseError(
                f"{self.display_name} 返回了非 JSON 响应（Content-Type: {content_type or '未知'}）。"
            ) from ex

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

    def __init__(self, *, transport, login: str = "", api_key: str = "", log_debug=None, provider_id: str = "danbooru", display_name: str = "Danbooru", base_url: str | None = None):
        super().__init__(provider_id, display_name, transport=transport, log_debug=log_debug)
        if base_url:
            self.base_url = base_url.rstrip("/")
        self.login = login
        self.api_key = api_key

    def search_posts(self, query: str = "", *, page=None, limit: int = 40) -> BooruSearchResult:
        page = self.first_page if page is None else int(page)
        params = {"tags": query.strip(), "page": page, "limit": self._limit(limit)}
        if self.login:
            params["login"] = self.login
        if self.api_key:
            params["api_key"] = self.api_key
        raw = self._json(f"{self.base_url}/posts.json", params=params)
        if not isinstance(raw, list):
            raise BooruResponseError("Danbooru 返回了非列表响应")
        posts = [post for item in raw if isinstance(item, dict) and (post := self._post(item))]
        return BooruSearchResult(self.provider_id, posts, query, page, page + 1 if len(raw) >= params["limit"] else None, raw=raw)

    def get_post(self, post_id: int | str) -> BooruPost:
        params: dict[str, Any] = {}
        if self.login:
            params["login"] = self.login
        if self.api_key:
            params["api_key"] = self.api_key
        raw = self._json(f"{self.base_url}/posts/{post_id}.json", params=params)
        if not isinstance(raw, dict) or not (post := self._post(raw)):
            raise BooruResponseError(f"Danbooru 作品不存在: {post_id}")
        return post

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        params = {
            "search[name_matches]": f"{query.strip()}*",
            "search[order]": "count",
            "limit": self._limit(limit),
        }
        raw = self._json(f"{self.base_url}/tags.json", params=params)
        if not isinstance(raw, list):
            raise BooruResponseError(f"{self.display_name} 返回了无法识别的标签响应")
        type_names = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
        return [
            TagSuggestion(
                str(item.get("name") or ""),
                type_names.get(self._int(item.get("category")), "general"),
                self._int(item.get("post_count")),
                item,
            )
            for item in raw
            if isinstance(item, dict) and item.get("name")
        ]

    def _post(self, item: dict[str, Any]) -> BooruPost | None:
        original = self._absolute(item.get("file_url"))
        sample = self._absolute(item.get("large_file_url"))
        if not original and not sample:
            return None
        post_id = item.get("id", "")
        return BooruPost(
            self.provider_id, post_id, f"{self.base_url}/posts/{post_id}",
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
        raw = self._json(f"{self.base_url}/index.php", params=params)
        items, total = self._parse_posts(raw)
        posts = [self._post(item) for item in items if isinstance(item, dict)]
        return BooruSearchResult("gelbooru", posts, query, page, page + 1 if len(items) >= limit else None, total, raw=raw)

    def get_post(self, post_id: int | str) -> BooruPost:
        params = {"page": "dapi", "s": "post", "q": "index", "json": "1", "id": post_id}
        params.update(self._auth_params())
        raw = self._json(f"{self.base_url}/index.php", params=params)
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
        raw = self._json(f"{self.base_url}/index.php", params=params)
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
            raise BooruResponseError(f"{self.display_name} XML 解析失败: {ex}") from ex
        if root.tag == "error":
            raise BooruAccessDeniedError(f"{self.display_name} API 拒绝请求: {(root.text or '').strip() or '未知原因'}")
        posts = [self._post(item.attrib) for item in root.findall("post")]
        total = self._int(root.attrib.get("count")) if "count" in root.attrib else None
        return BooruSearchResult(self.provider_id, posts, query, page, page + 1 if len(posts) >= limit else None, total, raw=response.text)

    def get_post(self, post_id: int | str) -> BooruPost:
        response = self._get(
            f"{self.base_url}/index.php",
            params={"page": "dapi", "s": "post", "q": "index", "id": post_id},
        )
        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as ex:
            raise BooruResponseError(f"{self.display_name} XML 解析失败: {ex}") from ex
        item = root.find("post")
        if item is None:
            raise BooruResponseError(f"{self.display_name} 作品不存在: {post_id}")
        return self._post(item.attrib)

    def _post(self, item: dict[str, Any]) -> BooruPost:
        post_id = item.get("id", "")
        return BooruPost(
            self.provider_id, post_id, f"{self.base_url}/index.php?page=post&s=view&id={post_id}",
            ImageVariant(self._absolute(item.get("file_url")), self._int(item.get("width")), self._int(item.get("height"))),
            ImageVariant(self._absolute(item.get("sample_url"))), ImageVariant(self._absolute(item.get("preview_url"))),
            {"general": self._tags(item.get("tags"))}, str(item.get("rating") or ""), self._int(item.get("score")),
            [str(item["source"])] if item.get("source") else [], raw=dict(item),
        )


class GelbooruAlikeClient(SafebooruClient):
    """Configurable old Gelbooru-style XML DAPI client."""

    def __init__(self, provider_id: str, display_name: str, base_url: str, *, transport, log_debug=None):
        HttpBooruClient.__init__(self, provider_id, display_name, transport=transport, log_debug=log_debug)
        self.base_url = base_url.rstrip("/")

    def _post(self, item: dict[str, Any]) -> BooruPost:
        post = super()._post(item)
        post.provider = self.provider_id
        post.page_url = f"{self.base_url}/index.php?page=post&s=view&id={post.id}"
        return post

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        response = self._get(
            f"{self.base_url}/index.php",
            params={
                "page": "dapi",
                "s": "tag",
                "q": "index",
                "name_pattern": f"{query.strip()}%",
                "limit": self._limit(limit),
                "orderby": "count",
                "order": "DESC",
            },
        )
        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as ex:
            raise BooruResponseError(f"{self.display_name} 标签 XML 解析失败: {ex}") from ex
        type_names = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
        return [
            TagSuggestion(
                str(item.attrib.get("name") or ""),
                type_names.get(self._int(item.attrib.get("type")), "general"),
                self._int(item.attrib.get("count")),
                dict(item.attrib),
            )
            for item in root.findall("tag")
            if item.attrib.get("name")
        ]


class MoebooruClient(HttpBooruClient):
    """Moebooru JSON API used by Yande.re, Konachan and Lolibooru."""

    max_limit = 100

    def __init__(self, provider_id: str, display_name: str, base_url: str, *, transport, api_path: str = "/post.json", log_debug=None):
        super().__init__(provider_id, display_name, transport=transport, log_debug=log_debug)
        self.base_url = base_url.rstrip("/")
        self.api_path = api_path

    def search_posts(self, query: str = "", *, page=None, limit: int = 40) -> BooruSearchResult:
        page = self.first_page if page is None else int(page)
        limit = self._limit(limit)
        raw = self._json(f"{self.base_url}{self.api_path}", params={"tags": query.strip(), "page": page, "limit": limit})
        if not isinstance(raw, list):
            raise BooruResponseError(f"{self.display_name} 返回了非列表响应")
        posts = [self._post(item) for item in raw if isinstance(item, dict)]
        return BooruSearchResult(self.provider_id, posts, query, page, page + 1 if len(raw) >= limit else None, raw=raw)

    def get_post(self, post_id: int | str) -> BooruPost:
        raw = self._json(f"{self.base_url}{self.api_path}", params={"tags": f"id:{post_id}", "limit": 1})
        if not isinstance(raw, list) or not raw:
            raise BooruResponseError(f"{self.display_name} 作品不存在: {post_id}")
        return self._post(raw[0])

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        raw = self._json(
            f"{self.base_url}/tag.json",
            params={"name": f"{query.strip()}*", "order": "count", "limit": self._limit(limit)},
        )
        if not isinstance(raw, list):
            raise BooruResponseError(f"{self.display_name} 返回了无法识别的标签响应")
        type_names = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
        return [
            TagSuggestion(
                str(item.get("name") or ""),
                type_names.get(self._int(item.get("type")), "general"),
                self._int(item.get("count")),
                item,
            )
            for item in raw
            if isinstance(item, dict) and item.get("name")
        ]

    def _post(self, item: dict[str, Any]) -> BooruPost:
        post_id = item.get("id", "")
        return BooruPost(
            self.provider_id,
            post_id,
            f"{self.base_url}/post/show/{post_id}",
            ImageVariant(self._absolute(item.get("file_url")), self._int(item.get("width")), self._int(item.get("height"))),
            ImageVariant(self._absolute(item.get("sample_url")), self._int(item.get("sample_width")), self._int(item.get("sample_height"))),
            ImageVariant(self._absolute(item.get("preview_url")), self._int(item.get("preview_width")), self._int(item.get("preview_height"))),
            {"general": self._tags(item.get("tags"))},
            str(item.get("rating") or ""),
            self._int(item.get("score")),
            [str(item["source"])] if item.get("source") else [],
            raw=item,
        )


class E621Client(HttpBooruClient):
    """E621-compatible JSON API, including E926."""

    max_limit = 320

    def __init__(self, provider_id: str, display_name: str, base_url: str, *, transport, log_debug=None):
        super().__init__(provider_id, display_name, transport=transport, log_debug=log_debug)
        self.base_url = base_url.rstrip("/")

    def search_posts(self, query: str = "", *, page=None, limit: int = 40) -> BooruSearchResult:
        page = self.first_page if page is None else int(page)
        limit = self._limit(limit)
        raw = self._json(f"{self.base_url}/posts.json", params={"tags": query.strip(), "page": page, "limit": limit})
        items = raw.get("posts", []) if isinstance(raw, dict) else []
        if not isinstance(items, list):
            raise BooruResponseError(f"{self.display_name} 返回了无法识别的响应")
        posts = [self._post(item) for item in items if isinstance(item, dict)]
        return BooruSearchResult(self.provider_id, posts, query, page, page + 1 if len(items) >= limit else None, raw=raw)

    def get_post(self, post_id: int | str) -> BooruPost:
        raw = self._json(f"{self.base_url}/posts/{post_id}.json")
        item = raw.get("post") if isinstance(raw, dict) else None
        if not isinstance(item, dict):
            raise BooruResponseError(f"{self.display_name} 作品不存在: {post_id}")
        return self._post(item)

    def _post(self, item: dict[str, Any]) -> BooruPost:
        post_id = item.get("id", "")
        file = item.get("file") if isinstance(item.get("file"), dict) else {}
        sample = item.get("sample") if isinstance(item.get("sample"), dict) else {}
        preview = item.get("preview") if isinstance(item.get("preview"), dict) else {}
        raw_tags = item.get("tags") if isinstance(item.get("tags"), dict) else {}
        tags = {str(key): [str(tag) for tag in value if tag] for key, value in raw_tags.items() if isinstance(value, list)}
        sources = item.get("sources") if isinstance(item.get("sources"), list) else []
        return BooruPost(
            self.provider_id,
            post_id,
            f"{self.base_url}/posts/{post_id}",
            ImageVariant(self._absolute(file.get("url")), self._int(file.get("width")), self._int(file.get("height"))),
            ImageVariant(self._absolute(sample.get("url")), self._int(sample.get("width")), self._int(sample.get("height"))),
            ImageVariant(self._absolute(preview.get("url")), self._int(preview.get("width")), self._int(preview.get("height"))),
            tags,
            str(item.get("rating") or ""),
            self._int(item.get("score", {}).get("total") if isinstance(item.get("score"), dict) else item.get("score")),
            [str(source) for source in sources],
            metadata={"md5": str(file.get("md5") or "")},
            raw=item,
        )


class PhilomenaClient(HttpBooruClient):
    """Philomena JSON API used by Derpibooru and Furbooru."""

    max_limit = 50

    def __init__(self, provider_id: str, display_name: str, base_url: str, *, transport, api_key: str = "", log_debug=None):
        super().__init__(provider_id, display_name, transport=transport, log_debug=log_debug)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def search_posts(self, query: str = "", *, page=None, limit: int = 40) -> BooruSearchResult:
        page = self.first_page if page is None else int(page)
        limit = self._limit(limit)
        params: dict[str, Any] = {"q": query.strip(), "page": page, "per_page": limit}
        if self.api_key:
            params["key"] = self.api_key
        raw = self._json(f"{self.base_url}/api/v1/json/search/images", params=params)
        items = raw.get("images", []) if isinstance(raw, dict) else []
        if not isinstance(items, list):
            raise BooruResponseError(f"{self.display_name} 返回了无法识别的响应")
        posts = [self._post(item) for item in items if isinstance(item, dict)]
        total = self._int(raw.get("total")) if isinstance(raw, dict) and raw.get("total") is not None else None
        return BooruSearchResult(self.provider_id, posts, query, page, page + 1 if len(items) >= limit else None, total, raw=raw)

    def get_post(self, post_id: int | str) -> BooruPost:
        raw = self._json(f"{self.base_url}/api/v1/json/images/{post_id}")
        item = raw.get("image") if isinstance(raw, dict) else None
        if not isinstance(item, dict):
            raise BooruResponseError(f"{self.display_name} 作品不存在: {post_id}")
        return self._post(item)

    def _post(self, item: dict[str, Any]) -> BooruPost:
        post_id = item.get("id", "")
        reps = item.get("representations") if isinstance(item.get("representations"), dict) else {}
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        return BooruPost(
            self.provider_id,
            post_id,
            f"{self.base_url}/images/{post_id}",
            ImageVariant(self._absolute(reps.get("full")), self._int(item.get("width")), self._int(item.get("height"))),
            ImageVariant(self._absolute(reps.get("large"))),
            ImageVariant(self._absolute(reps.get("thumb") or reps.get("small"))),
            {"general": [str(tag) for tag in tags if tag]},
            str(item.get("sfw") if "sfw" in item else ""),
            self._int(item.get("score")),
            [str(item["source_url"])] if item.get("source_url") else [],
            raw=item,
        )


class PahealClient(HttpBooruClient):
    """Rule34.Paheal legacy XML API."""

    first_page = 1

    def __init__(self, *, transport, log_debug=None):
        super().__init__("paheal", "Paheal", transport=transport, log_debug=log_debug)
        self.base_url = "https://rule34.paheal.net"

    def search_posts(self, query: str = "", *, page=None, limit: int = 40) -> BooruSearchResult:
        page = self.first_page if page is None else int(page)
        limit = self._limit(limit)
        response = self._get(
            f"{self.base_url}/api/danbooru/find_posts/index.xml",
            params={"tags": query.strip(), "page": page, "limit": limit},
        )
        items = self._parse_posts(response.text)
        posts = [self._post(item) for item in items]
        return BooruSearchResult(self.provider_id, posts, query, page, page + 1 if len(items) >= limit else None, raw=response.text)

    def get_post(self, post_id: int | str) -> BooruPost:
        response = self._get(
            f"{self.base_url}/api/danbooru/find_posts/index.xml",
            params={"id": post_id, "limit": 1},
        )
        items = self._parse_posts(response.text)
        if not items:
            raise BooruResponseError(f"Paheal 作品不存在: {post_id}")
        return self._post(items[0])

    @staticmethod
    def _parse_posts(text: str) -> list[dict[str, str]]:
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as ex:
            raise BooruResponseError(f"Paheal XML 解析失败: {ex}") from ex
        candidates = list(root.findall(".//tag")) + list(root.findall(".//post"))
        if root.tag in {"tag", "post"}:
            candidates.insert(0, root)
        return [dict(item.attrib) for item in candidates if item.attrib.get("file_url")]

    def _post(self, item: dict[str, Any]) -> BooruPost:
        post_id = item.get("id", "")
        return BooruPost(
            self.provider_id,
            post_id,
            f"{self.base_url}/post/view/{post_id}",
            ImageVariant(self._absolute(item.get("file_url")), self._int(item.get("width")), self._int(item.get("height"))),
            ImageVariant(self._absolute(item.get("sample_url"))),
            ImageVariant(self._absolute(item.get("preview_url"))),
            {"general": self._tags(item.get("tags"))},
            str(item.get("rating") or ""),
            self._int(item.get("score")),
            [str(item["source"])] if item.get("source") else [],
            raw=dict(item),
        )


BOORU_PROVIDER_SPECS = {
    spec.id: spec
    for spec in (
        BooruProviderSpec("safebooru", "Safebooru", "gelbooru_xml", "https://safebooru.org", True, True),
        BooruProviderSpec("gelbooru", "Gelbooru", "gelbooru_json", "https://gelbooru.com", True, True),
        BooruProviderSpec("danbooru", "Danbooru", "danbooru", "https://danbooru.donmai.us", True, True),
        BooruProviderSpec("rule34", "Rule34", "gelbooru_xml", "https://rule34.xxx", True, True),
        # Realbooru currently returns an empty result set for the smoke-test query.
        # BooruProviderSpec("realbooru", "Realbooru", "gelbooru_xml", "https://realbooru.com", True, True),
        BooruProviderSpec("tbib", "TBIB", "gelbooru_xml", "https://tbib.org", True, True),
        BooruProviderSpec("xbooru", "Xbooru", "gelbooru_xml", "https://xbooru.com", True, True),
        BooruProviderSpec("hypnohub", "Hypnohub", "gelbooru_xml", "https://hypnohub.net", True, True),
        BooruProviderSpec("yandere", "Yande.re", "moebooru", "https://yande.re", True, True),
        BooruProviderSpec("lolibooru", "Lolibooru", "moebooru", "https://lolibooru.moe", True, True),
        BooruProviderSpec("konachan", "Konachan", "moebooru", "https://konachan.com", True, True),
        BooruProviderSpec("konachan_net", "Konachan.net", "moebooru", "https://konachan.net", True, True),
        BooruProviderSpec("e621", "E621", "e621", "https://e621.net"),
        BooruProviderSpec("e926", "E926", "e621", "https://e926.net"),
        BooruProviderSpec("derpibooru", "Derpibooru", "philomena", "https://derpibooru.org"),
        BooruProviderSpec("furbooru", "Furbooru", "philomena", "https://furbooru.org"),
        BooruProviderSpec("behoimi", "Behoimi", "moebooru", "http://behoimi.org"),
    )
}

BOORU_PROVIDERS = {provider_id: spec.display_name for provider_id, spec in BOORU_PROVIDER_SPECS.items()}


def create_booru_client(provider_id: str, *, transport, log_debug=None, credentials: dict[str, str] | None = None) -> BooruClient:
    spec = BOORU_PROVIDER_SPECS.get(provider_id)
    if spec is None:
        raise KeyError(f"未知 Booru Provider: {provider_id}")
    credentials = credentials or {}
    if spec.protocol == "gelbooru_json":
        return GelbooruClient(
            transport=transport,
            user_id=credentials.get("user_id", ""),
            api_key=credentials.get("api_key", ""),
            log_debug=log_debug,
        )
    if spec.protocol == "gelbooru_xml":
        return GelbooruAlikeClient(spec.id, spec.display_name, spec.base_url, transport=transport, log_debug=log_debug)
    if spec.protocol == "danbooru":
        return DanbooruClient(
            transport=transport,
            login=credentials.get("login", ""),
            api_key=credentials.get("api_key", ""),
            provider_id=spec.id,
            display_name=spec.display_name,
            base_url=spec.base_url,
            log_debug=log_debug,
        )
    if spec.protocol == "moebooru":
        api_path = "/post/index.json" if spec.id == "behoimi" else "/post.json"
        return MoebooruClient(spec.id, spec.display_name, spec.base_url, transport=transport, api_path=api_path, log_debug=log_debug)
    if spec.protocol == "e621":
        return E621Client(spec.id, spec.display_name, spec.base_url, transport=transport, log_debug=log_debug)
    if spec.protocol == "philomena":
        return PhilomenaClient(
            spec.id,
            spec.display_name,
            spec.base_url,
            transport=transport,
            api_key=credentials.get("api_key", ""),
            log_debug=log_debug,
        )
    if spec.protocol == "paheal":
        return PahealClient(transport=transport, log_debug=log_debug)
    return BooruClient(spec.id, spec.display_name, log_debug=log_debug)
