from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol


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

    def __init__(self, backend: NotificationBackend, log_exception: Callable[[str, str], None] | None = None):
        self.backend = backend
        self._log_exception = log_exception

    def send(self, notification: Notification) -> None:
        try:
            self.backend.send(notification)
        except Exception as ex:
            if self._log_exception is not None:
                self._log_exception(
                    "通知",
                    f"通知 backend 执行失败 backend={type(self.backend).__name__} category={notification.category}：{ex}",
                )
