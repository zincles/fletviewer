from app.debug_log import Timer, log_debug
from app.storage import load_app_config, load_eh_config
from lib.net.browser_session import BrowserSessionService, DEFAULT_UA, EH_DOMAIN_EH, is_image_request_url


browser_session = BrowserSessionService(
    load_app_config=load_app_config,
    load_eh_config=load_eh_config,
    log_debug=log_debug,
    timer_factory=Timer,
)


__all__ = ["BrowserSessionService", "DEFAULT_UA", "EH_DOMAIN_EH", "browser_session", "is_image_request_url"]
