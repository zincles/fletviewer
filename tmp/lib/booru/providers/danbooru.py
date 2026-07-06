from __future__ import annotations

from typing import Any

from ._base import _BaseBooruClient
from ..data import BooruPost, ImageVariant, TagSuggestion


class DanbooruClient(_BaseBooruClient):
    '''
    Danbooru 现代 JSON API provider。

    使用 /posts.json 和 /posts/<id>.json；分页是 1-based。
    '''
    provider = "danbooru"
    default_base_url = "https://danbooru.donmai.us"
    first_page = 1
    max_limit = 200

    def validate_tags(self, tags: str) -> str:
        '''Danbooru 当前将 rating:safe 表达为 rating:general。'''
        if "danbooru.donmai.us" in self.base_url and "rating:safe" in tags.lower():
            return tags.replace("rating:safe", "rating:general")
        return tags

    def fetch_search(self, tags: str, *, page: int, limit: int) -> Any:
        params = {"tags": tags, "page": page, "limit": limit}
        if self.user_id:
            params["login"] = self.user_id
        if self.api_key:
            params["api_key"] = self.api_key
        response = self.session.get(f"{self.base_url}/posts.json", params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def parse_search(self, raw: Any) -> tuple[list[BooruPost], int | None]:
        if not isinstance(raw, list):
            return [], None
        posts = [post for item in raw if isinstance(item, dict) and (post := self.post_from_json(item)) is not None]
        return posts, None

    def get_post(self, post_id: int | str) -> BooruPost:
        params = {}
        if self.user_id:
            params["login"] = self.user_id
        if self.api_key:
            params["api_key"] = self.api_key
        response = self.session.get(f"{self.base_url}/posts/{post_id}.json", params=params, timeout=self.timeout)
        response.raise_for_status()
        post = self.post_from_json(response.json())
        if post is None:
            raise LookupError(f"post has no file_url: {post_id}")
        return post

    def tag_suggestions(self, query: str, *, limit: int = 20) -> list[TagSuggestion]:
        response = self.session.get(
            f"{self.base_url}/autocomplete.json",
            params={"search[query]": f"*{query}*", "search[type]": "tag_query", "limit": limit},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return [self.tag_suggestion_from_json(item) for item in data if isinstance(item, dict)]

    def post_from_json(self, item: dict[str, Any]) -> BooruPost | None:
        '''
        将 Danbooru post JSON 转成统一 BooruPost。

        Danbooru 会返回被删除/不可见、没有 file_url 的条目；这些条目不适合展示，直接跳过。
        '''
        file_url = self.absolute_url(item.get("file_url"))
        if not file_url:
            return None
        post_id = item.get("id", "")
        large_url = self.absolute_url(item.get("large_file_url"))
        if file_url.endswith(".zip") and large_url:
            file_url = large_url
        return BooruPost(
            provider=self.provider,
            id=post_id,
            page_url=f"{self.base_url}/posts/{post_id}" if post_id else "",
            original=ImageVariant(
                url=file_url,
                width=self.int_value(item.get("image_width")),
                height=self.int_value(item.get("image_height")),
            ),
            sample=ImageVariant(url=large_url),
            preview=ImageVariant(url=self.absolute_url(item.get("preview_file_url"))),
            tags={
                "general": self.split_tags(item.get("tag_string_general")),
                "artist": self.split_tags(item.get("tag_string_artist")),
                "character": self.split_tags(item.get("tag_string_character")),
                "copyright": self.split_tags(item.get("tag_string_copyright")),
                "meta": self.split_tags(item.get("tag_string_meta")),
            },
            rating=str(item.get("rating") or ""),
            score=self.int_value(item.get("score")),
            file_ext=str(item.get("file_ext") or ""),
            file_size=self.int_value(item.get("file_size")),
            md5=str(item.get("md5") or ""),
            source=self.source_list(item.get("source")),
            uploader_id=str(item.get("uploader_id") or ""),
            created_at=str(item.get("created_at") or ""),
            has_notes=item.get("last_noted_at") is not None,
            has_comments=item.get("last_commented_at") is not None,
            raw=item,
        )

    def tag_suggestion_from_json(self, item: dict[str, Any]) -> TagSuggestion:
        type_map = {"0": "general", "1": "artist", "3": "copyright", "4": "character", "5": "meta"}
        raw_type = str(item.get("category") or "")
        return TagSuggestion(
            tag=str(item.get("value") or ""),
            type=type_map.get(raw_type, "general"),
            count=self.int_value(item.get("post_count")),
            raw=item,
        )
