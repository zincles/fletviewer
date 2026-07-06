from __future__ import annotations

from html import unescape
from typing import Any
from xml.etree import ElementTree

from ._base import _BaseBooruClient
from ..data import BooruPost, ImageVariant, TagSuggestion


class GelbooruAlikeClient(_BaseBooruClient):
    '''
    旧 Gelbooru-style XML DAPI provider。

    用于 Safebooru、Rule34 等 Gelbooru-alike 站点。这里默认解析 XML，不走 gelbooru.com
    的现代 JSON DAPI。
    '''
    provider = "gelbooru_alike"
    default_base_url = "https://safebooru.org"
    first_page = 0
    max_limit = 100

    def __init__(self, *args: Any, api_base_url: str | None = None, **kwargs: Any):
        '''
        original_base_url 用于页面 URL，api_base_url 用于 API 请求。

        Rule34 这类站点页面域名和 API 域名不同，不能混用。
        '''
        super().__init__(*args, **kwargs)
        self.original_base_url = self.base_url
        self.api_base_url = (api_base_url or self.base_url).rstrip("/")

    def fetch_search(self, tags: str, *, page: int, limit: int) -> Any:
        response = self.session.get(
            f"{self.api_base_url}/index.php",
            params={
                "page": "dapi",
                "s": "post",
                "q": "index",
                "tags": tags.replace(" ", "+"),
                "limit": limit,
                "pid": max(0, page),
                **self.api_params(),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    def parse_search(self, raw: Any) -> tuple[list[BooruPost], int | None]:
        root = ElementTree.fromstring(raw)
        total_count = self.int_value(root.attrib.get("count"), default=-1)
        posts = [self.post_from_xml(item) for item in root.findall("post")]
        return posts, total_count if total_count >= 0 else None

    def get_post(self, post_id: int | str) -> BooruPost:
        response = self.session.get(
            f"{self.api_base_url}/index.php",
            params={"page": "dapi", "s": "post", "q": "index", "id": post_id, **self.api_params()},
            timeout=self.timeout,
        )
        response.raise_for_status()
        posts, _ = self.parse_search(response.text)
        if not posts:
            raise LookupError(f"post not found: {post_id}")
        return posts[0]

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        response = self.session.get(
            f"{self.api_base_url}/index.php",
            params={
                "page": "dapi",
                "s": "tag",
                "q": "index",
                "name_pattern": f"{query}%",
                "limit": limit,
                "order": "count",
                "direction": "desc",
                **self.api_params(),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        return [self.tag_suggestion_from_xml(item) for item in root.findall("tag")]

    def api_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.user_id:
            params["user_id"] = self.user_id
        return params

    def make_post_url(self, post_id: int | str) -> str:
        '''构造用户可打开的 post 页面 URL。'''
        return f"{self.original_base_url}/index.php?page=post&s=view&id={post_id}"

    def post_from_xml(self, item: ElementTree.Element) -> BooruPost:
        post_id = item.attrib.get("id", "")
        file_url = self.absolute_url(item.attrib.get("file_url"))
        sample_url = self.absolute_url(item.attrib.get("sample_url") or item.attrib.get("file_url"))
        preview_url = self.absolute_url(item.attrib.get("preview_url"))
        return BooruPost(
            provider=self.provider,
            id=post_id,
            page_url=self.make_post_url(post_id) if post_id else "",
            original=ImageVariant(
                url=file_url,
                width=self.int_value(item.attrib.get("width")),
                height=self.int_value(item.attrib.get("height")),
            ),
            sample=ImageVariant(
                url=sample_url,
                width=self.int_value(item.attrib.get("sample_width")),
                height=self.int_value(item.attrib.get("sample_height")),
            ),
            preview=ImageVariant(
                url=preview_url,
                width=self.int_value(item.attrib.get("preview_width")),
                height=self.int_value(item.attrib.get("preview_height")),
            ),
            tags={"general": self.split_tags(unescape(item.attrib.get("tags", "")))},
            rating=item.attrib.get("rating", ""),
            score=self.int_value(item.attrib.get("score")),
            file_ext=file_url.rsplit(".", 1)[-1].lower() if file_url else "",
            md5=item.attrib.get("md5", ""),
            source=self.source_list(item.attrib.get("source")),
            uploader_id=item.attrib.get("creator_id", ""),
            created_at=item.attrib.get("created_at", ""),
            has_notes=self.bool_value(item.attrib.get("has_notes")),
            has_comments=self.bool_value(item.attrib.get("has_comments")),
            raw=dict(item.attrib),
        )

    def tag_suggestion_from_xml(self, item: ElementTree.Element) -> TagSuggestion:
        type_map = {"0": "general", "1": "artist", "3": "copyright", "4": "character", "5": "meta"}
        raw_type = item.attrib.get("type", "")
        return TagSuggestion(
            tag=item.attrib.get("name", ""),
            type=type_map.get(raw_type, "general"),
            count=self.int_value(item.attrib.get("count")),
            raw=dict(item.attrib),
        )


class SafebooruClient(GelbooruAlikeClient):
    '''Safebooru preset，使用 Gelbooru-alike XML DAPI。'''
    provider = "safebooru"
    default_base_url = "https://safebooru.org"


class Rule34Client(GelbooruAlikeClient):
    '''
    Rule34 preset。

    页面域名是 rule34.xxx，但 API 默认走 api.rule34.xxx。
    '''
    provider = "rule34"
    default_base_url = "https://rule34.xxx"

    def __init__(self, *args: Any, api_base_url: str | None = "https://api.rule34.xxx", **kwargs: Any):
        super().__init__(*args, api_base_url=api_base_url, **kwargs)
