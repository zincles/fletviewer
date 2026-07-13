from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, Hashable, TypeVar


ItemT = TypeVar("ItemT")
CursorT = TypeVar("CursorT")


@dataclass(slots=True)
class PageBatch(Generic[ItemT, CursorT]):
    """与 UI 框架无关的一页数据。"""

    items: list[ItemT]
    next_cursor: CursorT | None = None


@dataclass(frozen=True, slots=True)
class LoadRequest(Generic[CursorT]):
    generation: int
    cursor: CursorT | None
    replace: bool


@dataclass(slots=True)
class PagedFeedState(Generic[ItemT, CursorT]):
    """分页集合状态机；Flutter/Flet 适配层只负责渲染和调度。"""

    items: list[ItemT] = field(default_factory=list)
    next_cursor: CursorT | None = None
    generation: int = 0
    loading: bool = False
    _keys: set[Hashable] = field(default_factory=set)
    _requested: set[tuple[int, str]] = field(default_factory=set)

    def begin(self, cursor: CursorT | None = None, *, replace: bool = False) -> LoadRequest[CursorT] | None:
        if self.loading and not replace:
            return None
        if replace:
            self.generation += 1
            self.items.clear()
            self._keys.clear()
            self.next_cursor = None
            self._requested.clear()
        request_key = (self.generation, repr(cursor))
        if request_key in self._requested:
            return None
        self._requested.add(request_key)
        self.loading = True
        return LoadRequest(self.generation, cursor, replace)

    def complete(
        self,
        request: LoadRequest[CursorT],
        batch: PageBatch[ItemT, CursorT],
        *,
        key_of: Callable[[ItemT], Hashable],
    ) -> list[ItemT]:
        if request.generation != self.generation:
            return []
        incoming: list[ItemT] = []
        for item in batch.items:
            key = key_of(item)
            if key in self._keys:
                continue
            self._keys.add(key)
            self.items.append(item)
            incoming.append(item)
        self.next_cursor = batch.next_cursor
        self.loading = False
        return incoming

    def fail(self, request: LoadRequest[CursorT], *, retryable: bool = True) -> None:
        if request.generation != self.generation:
            return
        self.loading = False
        if retryable:
            self._requested.discard((request.generation, repr(request.cursor)))
