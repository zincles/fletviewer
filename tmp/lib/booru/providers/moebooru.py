from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

from ._base import _BaseBooruClient
from ..data import BooruPost, ImageVariant, TagSuggestion


class MoebooruClient(_BaseBooruClient):
    '''
    Moebooru XML API provider。

    这类站点通常使用 /post.xml 和 /tag.xml，分页是 1-based。
    '''
    provider = "moebooru"
    default_base_url = "https://konachan.com"
    first_page = 1
    max_limit = 100

    def fetch_search(self, tags: str, *, page: int, limit: int) -> Any:
        params = {"tags": tags, "page": max(1, page), "limit": limit}
        if self.user_id:
            params["login"] = self.user_id
        if self.api_key:
            params["api_key"] = self.api_key
        response = self.session.get(f"{self.base_url}/post.xml", params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def parse_search(self, raw: Any) -> tuple[list[BooruPost], int | None]:
        root = ElementTree.fromstring(raw)
        total_count = self.int_value(root.attrib.get("count"), default=-1)
        posts = [self.post_from_xml(item) for item in root.findall("post")]
        return posts, total_count if total_count >= 0 else None

    def get_post(self, post_id: int | str) -> BooruPost:
        params = {"tags": f"id:{post_id}", "limit": 1}
        if self.user_id:
            params["login"] = self.user_id
        if self.api_key:
            params["api_key"] = self.api_key
        response = self.session.get(f"{self.base_url}/post.xml", params=params, timeout=self.timeout)
        response.raise_for_status()
        posts, _ = self.parse_search(response.text)
        if not posts:
            raise LookupError(f"post not found: {post_id}")
        return posts[0]

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        response = self.session.get(
            f"{self.base_url}/tag.xml",
            params={"name": f"{query}*", "limit": limit, "order": "count"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        return [self.tag_suggestion_from_xml(item) for item in root.findall("tag")]

    def post_from_xml(self, item: ElementTree.Element) -> BooruPost:
        post_id = item.attrib.get("id", "")
        file_url = self.absolute_url(item.attrib.get("file_url"))
        sample_url = self.absolute_url(item.attrib.get("sample_url") or item.attrib.get("file_url"))
        preview_url = self.absolute_url(item.attrib.get("preview_url"))
        return BooruPost(
            provider=self.provider,
            id=post_id,
            page_url=f"{self.base_url}/post/show/{post_id}/" if post_id else "",
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
            tags={"general": self.split_tags(item.attrib.get("tags"))},
            rating=item.attrib.get("rating", ""),
            score=self.int_value(item.attrib.get("score")),
            file_ext=file_url.rsplit(".", 1)[-1].lower() if file_url else "",
            file_size=self.int_value(item.attrib.get("file_size")),
            md5=item.attrib.get("md5", ""),
            source=self.source_list(item.attrib.get("source")),
            created_at=item.attrib.get("created_at", ""),
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
