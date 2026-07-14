from __future__ import annotations

import threading
from typing import Protocol

from core.config.models import BackendConfig


class BackendConfigRepository(Protocol):
    def load(self) -> BackendConfig:
        ...

    def save(self, config: BackendConfig) -> None:
        ...


class MemoryBackendConfigRepository:
    """Small repository for tests, embedding, and bridge prototypes."""

    def __init__(self, config: BackendConfig | None = None):
        self._config = config or BackendConfig()
        self._lock = threading.RLock()

    def load(self) -> BackendConfig:
        with self._lock:
            return self._config

    def save(self, config: BackendConfig) -> None:
        if not isinstance(config, BackendConfig):
            raise TypeError("config must be BackendConfig")
        with self._lock:
            self._config = config
