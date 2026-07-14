from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def json_safe(value: Any) -> JSONValue:
    """Convert provider metadata to values safe to pass across a Dart bridge."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


@dataclass(slots=True)
class MediaItemDTO:
    provider: str
    id: str
    title: str
    thumbnail_url: str = ""
    image_url: str = ""
    page_url: str = ""
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0
    subtitle: str = ""
    description: str = ""
    tags: dict[str, list[str]] = field(default_factory=dict)
    rating: str = ""
    score: int = 0
    source: list[str] = field(default_factory=list)
    page_count: int = 0
    creator_id: str = ""
    creator_name: str = ""
    category: str = ""
    language: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(asdict(self))

    # Temporary Python UI aliases. They are not part of the serialized contract.
    @property
    def cover(self) -> str:
        return self.thumbnail_url

    @property
    def sub_title(self) -> str:
        return self.subtitle

    @property
    def stars(self) -> float:
        return float(self.metadata.get("stars") or 0)

    @property
    def max_page(self) -> int:
        return self.page_count

    @property
    def type(self) -> str:
        return self.category

    @property
    def uploader(self) -> str:
        return self.creator_name

    @property
    def cover_width(self) -> int:
        return self.width

    @property
    def cover_height(self) -> int:
        return self.height

    @property
    def cover_aspect_ratio(self) -> float:
        return self.aspect_ratio


@dataclass(slots=True)
class CommentDTO:
    id: str = ""
    author: str = ""
    content: str = ""
    created_at: str = ""
    score: int | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    # Temporary aliases used by the EH Python UI.
    @property
    def user_name(self) -> str:
        return self.author

    @property
    def time(self) -> str:
        return self.created_at


@dataclass(slots=True)
class RelatedMediaDTO:
    id: str
    title: str = ""
    page_url: str = ""
    relation: str = "related"
    subtitle: str = ""
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    # Temporary aliases used by the EH Python UI.
    @property
    def url(self) -> str:
        return self.page_url

    @property
    def posted(self) -> str:
        return self.subtitle


@dataclass(slots=True)
class MediaDetailDTO:
    provider: str
    id: str
    title: str
    subtitle: str = ""
    thumbnail_url: str = ""
    image_url: str = ""
    page_url: str = ""
    description: str = ""
    tags: dict[str, list[str]] = field(default_factory=dict)
    page_count: int = 0
    creator_id: str = ""
    creator_name: str = ""
    category: str = ""
    language: str = ""
    rating: float = 0.0
    rating_count: int = 0
    favorite_count: int = 0
    created_at: str = ""
    width: int = 0
    height: int = 0
    comments: list[CommentDTO] = field(default_factory=list)
    related: list[RelatedMediaDTO] = field(default_factory=list)
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(asdict(self))

    # Temporary EH aliases. They are not part of the serialized contract.
    @property
    def cover(self) -> str:
        return self.thumbnail_url

    @property
    def max_page(self) -> int:
        return self.page_count

    @property
    def uploader(self) -> str:
        return self.creator_name

    @property
    def stars(self) -> float:
        return self.rating

    @property
    def upload_time(self) -> str:
        return self.created_at

    @property
    def url(self) -> str:
        return self.page_url

    @property
    def language_detail(self) -> str:
        return self.language

    @property
    def file_size(self) -> str:
        return str(self.metadata.get("file_size") or "")

    @property
    def visible(self) -> str:
        return str(self.metadata.get("visible") or "")

    @property
    def parent(self) -> str:
        return str(self.metadata.get("parent_url") or "")

    @property
    def newer_versions(self) -> list[RelatedMediaDTO]:
        return [item for item in self.related if item.relation == "newer_version"]


@dataclass(slots=True)
class PageResultDTO:
    provider: str
    items: list[MediaItemDTO] = field(default_factory=list)
    next_cursor: str | int | None = None
    prev_cursor: str | int | None = None
    query: str = ""
    total_count: int | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(asdict(self))

    # Temporary aliases used while the Python UI migrates to this contract.
    @property
    def comics(self) -> list[MediaItemDTO]:
        return self.items

    @property
    def next_url(self) -> str | int | None:
        return self.next_cursor

    @property
    def prev_url(self) -> str | int | None:
        return self.prev_cursor
