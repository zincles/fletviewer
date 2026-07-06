from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ImageVariant:
    '''同一作品的某个图片版本，例如原图、sample 或 preview。'''
    url: str = ""
    width: int = 0
    height: int = 0

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.width and self.height else 0.0


@dataclass(slots=True)
class BooruPost:
    '''
    各类 Booru provider 统一输出的 post 数据结构。

    不同站点协议差异很大，provider 应在解析阶段尽量填充 original/sample/preview，
    外部代码不要直接依赖某个站点的 raw 字段。
    '''
    provider: str
    id: int | str
    page_url: str
    original: ImageVariant = field(default_factory=ImageVariant)
    sample: ImageVariant = field(default_factory=ImageVariant)
    preview: ImageVariant = field(default_factory=ImageVariant)
    tags: dict[str, list[str]] = field(default_factory=dict)
    rating: str = ""
    score: int = 0
    file_ext: str = ""
    file_size: int = 0
    md5: str = ""
    source: list[str] = field(default_factory=list)
    uploader_id: str = ""
    uploader_name: str = ""
    created_at: str = ""
    has_notes: bool = False
    has_comments: bool = False
    raw: Any = None

    @property
    def thumbnail_url(self) -> str:
        return self.preview.url or self.sample.url or self.original.url

    @property
    def sample_url(self) -> str:
        return self.sample.url or self.original.url or self.preview.url

    @property
    def original_url(self) -> str:
        return self.original.url or self.sample.url or self.preview.url

    @property
    def best_image_url(self) -> str:
        return self.original_url

    @property
    def width(self) -> int:
        return self.original.width or self.sample.width or self.preview.width

    @property
    def height(self) -> int:
        return self.original.height or self.sample.height or self.preview.height

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.width and self.height else 0.0

    @property
    def flat_tags(self) -> list[str]:
        '''按分类顺序展开 tags，并去重。'''
        seen: set[str] = set()
        result: list[str] = []
        for values in self.tags.values():
            for tag in values:
                if tag and tag not in seen:
                    seen.add(tag)
                    result.append(tag)
        return result


@dataclass(slots=True)
class BooruSearchResult:
    '''
    搜索结果的统一包装。

    page 的起始值由具体 provider 决定；Danbooru 是 1-based，Gelbooru DAPI 是 0-based。
    '''
    provider: str
    posts: list[BooruPost]
    tags: str
    page: int
    limit: int
    total_count: int | None = None
    has_next: bool = False
    raw: Any = None


@dataclass(slots=True)
class TagSuggestion:
    '''统一的 tag 自动补全结果。'''
    tag: str
    type: str = "general"
    count: int = 0
    raw: Any = None
