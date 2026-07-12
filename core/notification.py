from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Notification:
    title: str
    body: str
    category: str = "general"
    data: dict = field(default_factory=dict)


class NotificationBackend(Protocol):
    def send(self, notification: Notification) -> None: ...


class Notifier:
    """隔离 backend 故障，通知失败不得影响业务流程。"""

    def __init__(self, backend: NotificationBackend):
        self.backend = backend

    def send(self, notification: Notification) -> None:
        try:
            self.backend.send(notification)
        except Exception:
            pass
