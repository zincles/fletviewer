from __future__ import annotations

from html import unescape
from typing import Any

from ._base import _BaseBooruClient
from ..data import BooruPost, ImageVariant, TagSuggestion


class GelbooruClient(_BaseBooruClient):
    '''
    gelbooru.com 当前 JSON DAPI provider。

    注意它不是所有 Gelbooru-like 站点的通用实现；Safebooru/Rule34 走 GelbooruAlikeClient。
    '''
    provider = "gelbooru"
    default_base_url = "https://gelbooru.com"
    first_page = 0
    max_limit = 100

    def validate_tags(self, tags: str) -> str:
        if "rating:safe" in tags.lower():
            return tags.replace("rating:safe", "rating:general")
        return tags

    def fetch_search(self, tags: str, *, page: int, limit: int) -> Any:
        response = self.session.get(
            f"{self.base_url}/index.php",
            params={
                "page": "dapi",
                "s": "post",
                "q": "index",
                "tags": tags.replace(" ", "+"),
                "limit": limit,
                "pid": max(0, page),
                "json": "1",
                **self.api_params(),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def parse_search(self, raw: Any) -> tuple[list[BooruPost], int | None]:
        if isinstance(raw, dict):
            total_count = self.int_value(raw.get("@attributes", {}).get("count"), default=-1)
            raw_posts = raw.get("post") or []
            if isinstance(raw_posts, dict):
                raw_posts = [raw_posts]
            posts = [self.post_from_json(item) for item in raw_posts if isinstance(item, dict)]
            return posts, total_count if total_count >= 0 else None
        if isinstance(raw, list):
            return [self.post_from_json(item) for item in raw if isinstance(item, dict)], None
        return [], None

    def get_post(self, post_id: int | str) -> BooruPost:
        response = self.session.get(
            f"{self.base_url}/index.php",
            params={
                "page": "dapi",
                "s": "post",
                "q": "index",
                "id": post_id,
                "json": "1",
                **self.api_params(),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        posts, _ = self.parse_search(response.json())
        if not posts:
            raise LookupError(f"post not found: {post_id}")
        return posts[0]

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        response = self.session.get(
            f"{self.base_url}/index.php",
            params={"page": "autocomplete2", "term": query, "type": "tag_query", "limit": limit, **self.api_params()},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            data = data.get("tag", [])
        return [self.tag_suggestion_from_json(item) for item in data if isinstance(item, dict)]

    def api_params(self) -> dict[str, str]:
        '''
        拼接 Gelbooru API 认证参数。

        许多 Gelbooru 请求需要 user_id/api_key，否则可能限流或拒绝访问。
        '''
        params: dict[str, str] = {}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.user_id:
            params["user_id"] = self.user_id
        return params

    def post_from_json(self, item: dict[str, Any]) -> BooruPost:
        post_id = item.get("id", "")
        file_url = self.absolute_url(item.get("file_url") or item.get("source"))
        sample_url = self.absolute_url(item.get("sample_url") or item.get("file_url"))
        preview_url = self.absolute_url(item.get("preview_url"))
        return BooruPost(
            provider=self.provider,
            id=post_id,
            page_url=f"{self.base_url}/index.php?page=post&s=view&id={post_id}" if post_id else "",
            original=ImageVariant(
                url=file_url,
                width=self.int_value(item.get("width")),
                height=self.int_value(item.get("height")),
            ),
            sample=ImageVariant(
                url=sample_url,
                width=self.int_value(item.get("sample_width")),
                height=self.int_value(item.get("sample_height")),
            ),
            preview=ImageVariant(
                url=preview_url,
                width=self.int_value(item.get("preview_width")),
                height=self.int_value(item.get("preview_height")),
            ),
            tags={"general": self.split_tags(unescape(str(item.get("tags") or "")))},
            rating=str(item.get("rating") or ""),
            score=self.int_value(item.get("score")),
            file_ext=str(item.get("image") or file_url).rsplit(".", 1)[-1].lower() if file_url else "",
            md5=str(item.get("md5") or ""),
            source=self.source_list(item.get("source")),
            uploader_name=str(item.get("owner") or ""),
            created_at=str(item.get("created_at") or ""),
            has_notes=self.bool_value(item.get("has_notes")),
            has_comments=self.bool_value(item.get("has_comments")),
            raw=item,
        )

    def tag_suggestion_from_json(self, item: dict[str, Any]) -> TagSuggestion:
        type_map = {
            "0": "general",
            "tag": "general",
            "1": "artist",
            "artist": "artist",
            "3": "copyright",
            "copyright": "copyright",
            "4": "character",
            "character": "character",
            "5": "meta",
            "metadata": "meta",
        }
        raw_type = str(item.get("category") or item.get("type") or "")
        return TagSuggestion(
            tag=str(item.get("value") or item.get("name") or ""),
            type=type_map.get(raw_type, "general"),
            count=self.int_value(item.get("count") or item.get("post_count")),
            raw=item,
        )
