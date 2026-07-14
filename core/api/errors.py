from __future__ import annotations

from dataclasses import asdict, dataclass

from core.api.dto import JSONValue, json_safe


@dataclass(slots=True)
class BackendErrorPayload:
    code: str
    message: str
    provider: str = ""
    retryable: bool = False

    def to_dict(self) -> dict[str, JSONValue]:
        return json_safe(asdict(self))


class BackendError(RuntimeError):
    def __init__(self, code: str, message: str, *, provider: str = "", retryable: bool = False):
        super().__init__(message)
        self.payload = BackendErrorPayload(code, message, provider, retryable)

    def to_dict(self) -> dict[str, JSONValue]:
        return self.payload.to_dict()
