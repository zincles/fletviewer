"""Flet composition root; all service ownership lives in core.runtime."""

import atexit

from app.debug_log import Timer, log_debug
from app.backend_config import AppBackendConfigRepository
from core.runtime import BackendRuntime


runtime = BackendRuntime(
    config_repository=AppBackendConfigRepository(),
    log_debug=log_debug,
    timer_factory=Timer,
)
backend = runtime.backend
atexit.register(runtime.shutdown)

__all__ = ["backend", "runtime"]
