"""Compatibility export for Flet modules migrating to app.backend."""

from app.backend import runtime
from core.net.browser_session import BrowserSessionService, DEFAULT_UA, EH_DOMAIN_EH, is_image_request_url


browser_session = runtime.browser_session


__all__ = ["BrowserSessionService", "DEFAULT_UA", "EH_DOMAIN_EH", "browser_session", "is_image_request_url"]
