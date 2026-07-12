from __future__ import annotations

import threading
from typing import Callable, Generic, TypeVar


T = TypeVar("T")


class LazyProxy(Generic[T]):
    """在首次属性访问时创建目标对象。"""

    def __init__(self, factory: Callable[[], T]):
        self._factory = factory
        self._instance: T | None = None
        self._lock = threading.Lock()

    def resolve(self) -> T:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = self._factory()
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self.resolve(), name)
