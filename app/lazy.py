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

    def resolve_if_created(self) -> T | None:
        """Return the instance without triggering lazy construction."""
        with self._lock:
            return self._instance

    def reset(self) -> T | None:
        """Release and return the current instance without creating one."""
        with self._lock:
            instance = self._instance
            self._instance = None
            return instance

    def __getattr__(self, name: str):
        return getattr(self.resolve(), name)
