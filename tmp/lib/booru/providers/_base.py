from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urljoin

import requests

from ..data import BooruPost, BooruSearchResult, TagSuggestion


DEFAULT_TIMEOUT = 30
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FletViewer/tmp-booru-probe"


class _BaseBooruClient(ABC):
    '''
    Booru provider 的内部抽象基类。

    这里统一外部调用形状，但不试图统一 HTTP 协议。每个子类必须自己实现 endpoint、分页、
    响应格式和字段解析。
    '''
    provider = "base"
    default_base_url = ""
    first_page = 1
    max_limit = 100

    def __init__(
        self,
        base_url: str | None = None,
        *,
        session: requests.Session | None = None,
        user_id: str = "",
        api_key: str = "",
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", DEFAULT_USER_AGENT)
        self.session.headers.setdefault("Accept", "application/json, text/xml;q=0.9, */*;q=0.8")
        self.session.headers.setdefault("Accept-Language", "en-US,en;q=0.9")
        self.user_id = user_id
        self.api_key = api_key
        self.timeout = timeout

    def search_posts(self, tags: str = "", *, page: int | None = None, limit: int = 20) -> BooruSearchResult:
        '''
        搜索 post，并返回统一的 BooruSearchResult。

        注意：page 默认值来自具体 provider 的 first_page，不要假设所有站点都是 1-based。
        '''
        page = self.first_page if page is None else page
        limit = self.normalize_limit(limit)
        tags = self.validate_tags(tags.strip())
        raw = self.fetch_search(tags, page=page, limit=limit)
        posts, total_count = self.parse_search(raw)
        return BooruSearchResult(
            provider=self.provider,
            posts=posts,
            tags=tags,
            page=page,
            limit=limit,
            total_count=total_count,
            has_next=len(posts) >= limit,
            raw=raw,
        )

    @abstractmethod
    def fetch_search(self, tags: str, *, page: int, limit: int) -> Any:
        '''发起 provider 专属搜索请求，返回未解析的原始响应。'''
        raise NotImplementedError

    @abstractmethod
    def parse_search(self, raw: Any) -> tuple[list[BooruPost], int | None]:
        '''将 provider 原始响应解析成统一 BooruPost 列表。'''
        raise NotImplementedError

    @abstractmethod
    def get_post(self, post_id: int | str) -> BooruPost:
        '''获取单个 post。'''
        raise NotImplementedError

    def get_thumbnail_url(self, post: BooruPost) -> str:
        return post.thumbnail_url

    def get_sample_url(self, post: BooruPost) -> str:
        return post.sample_url

    def get_original_url(self, post: BooruPost) -> str:
        return post.original_url

    def next_page(self, result: BooruSearchResult) -> int:
        return result.page + 1

    def previous_page(self, result: BooruSearchResult) -> int:
        return max(self.first_page, result.page - 1)

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        return []

    def validate_tags(self, tags: str) -> str:
        return tags

    def normalize_limit(self, limit: int) -> int:
        return max(1, min(int(limit), self.max_limit))

    def absolute_url(self, value: Any) -> str:
        '''将站点返回的相对 URL、协议相对 URL 统一转成绝对 URL。'''
        if not value:
            return ""
        text = str(value)
        if text.startswith("//"):
            return "https:" + text
        if text.startswith("http://") or text.startswith("https://"):
            return text
        return urljoin(self.base_url + "/", text)

    @staticmethod
    def int_value(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def bool_value(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).lower() in {"1", "true", "yes"}

    @staticmethod
    def split_tags(value: Any) -> list[str]:
        if not value:
            return []
        return [tag for tag in str(value).split() if tag]

    @staticmethod
    def source_list(value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return [str(value)]
