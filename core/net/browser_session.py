from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from core.provider.ehgrabber import EH_DOMAIN_EH, EHentaiClient


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif")
EH_COOKIE_KEYS = ("ipb_member_id", "ipb_pass_hash", "igneous", "star")
SENSITIVE_QUERY_KEYS = {"api_key", "access_token", "token", "password", "pass_hash"}


def is_image_request_url(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(IMAGE_SUFFIXES)


def redact_url(url: str) -> str:
    """隐藏日志 URL 中的认证参数，同时保留可排障的请求形状。"""
    parsed = urlsplit(str(url))
    query = urlencode([
        (key, "<redacted>" if key.lower() in SENSITIVE_QUERY_KEYS else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


class BrowserSessionService:
    def __init__(
        self,
        *,
        load_app_config: Callable[[], dict],
        load_eh_config: Callable[[], dict],
        log_debug: Callable[[str, str], None] | None = None,
        timer_factory: Callable[[str, str], object] | None = None,
    ):
        self._load_app_config = load_app_config
        self._load_eh_config = load_eh_config
        self._log_debug = log_debug or (lambda _area, _message: None)
        self._timer_factory = timer_factory or _NullTimer
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
                "Connection": "keep-alive",
            }
        )
        self._lock = threading.RLock()
        self._request_idle = threading.Condition(self._lock)
        self._active_requests = 0
        self._cookie_signature: tuple[str, str, str, str] | None = None
        self._login_configured: bool | None = None
        self._verified_at = 0.0
        self._verified_ok = False
        self._proxy_signature: tuple[str, str] | None = None
        self._client_session = _BrowserSessionFacade(self)
        self.verify_ttl_seconds = 300

    def configure_proxy_from_storage(self) -> None:
        config = self._load_app_config()
        mode = str(config.get("proxy_mode") or "disabled")
        proxy_url = str(config.get("proxy_url") or "").strip()
        signature = (mode, proxy_url)
        with self._lock:
            if signature == self._proxy_signature:
                return
            while self._active_requests:
                self._request_idle.wait()
            if mode == "system":
                self.session.proxies.clear()
                self.session.trust_env = True
            elif mode == "manual":
                parsed = urlsplit(proxy_url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    raise ValueError("代理地址必须是有效的 http:// 或 https:// URL")
                self.session.trust_env = False
                self.session.proxies = {"http": proxy_url, "https": proxy_url}
            else:
                mode = "disabled"
                self.session.proxies.clear()
                self.session.trust_env = False
            self._proxy_signature = (mode, proxy_url if mode == "manual" else "")
            self._debug(f"代理配置已应用 mode={mode}")

    def login_enabled(self) -> bool:
        return bool(self._load_app_config().get("enable_login", True))

    def login_status_text(self) -> str:
        if not self.login_enabled():
            return "游客模式"
        cfg = self._load_eh_config()
        if not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash"):
            return "登录已启用，但缺少必填凭据"
        with self._lock:
            if self._verified_ok and time.time() - self._verified_at < self.verify_ttl_seconds:
                return "已登录（验证缓存有效）"
            if self._cookie_signature:
                return "登录已启用，Cookie 已载入"
        return "登录已启用，等待载入 Cookie"

    def login_status_level(self) -> str:
        if not self.login_enabled():
            return "guest"
        cfg = self._load_eh_config()
        if not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash"):
            return "warning"
        with self._lock:
            if self._verified_ok and time.time() - self._verified_at < self.verify_ttl_seconds:
                return "ok"
            if self._cookie_signature:
                return "pending"
        return "warning"

    def set_login_enabled(self, enabled: bool, *, verify: bool = True) -> bool:
        with self._lock:
            self._verified_at = 0.0
            self._verified_ok = False
            if not enabled:
                while self._active_requests:
                    self._request_idle.wait()
                self._clear_eh_cookies_locked()
                self._cookie_signature = None
                self._login_configured = False
                self._debug("EH 登录开关=关，已清理 Cookie")
                return False
        if verify:
            return self.ensure_logged_in(force=True)
        return self.configure_from_storage()

    def configure_from_storage(self) -> bool:
        self.configure_proxy_from_storage()
        if not self.login_enabled():
            with self._lock:
                if self._login_configured is False:
                    return False
                while self._active_requests:
                    self._request_idle.wait()
                self._clear_eh_cookies_locked()
                self._cookie_signature = None
                self._login_configured = False
                self._verified_at = 0.0
                self._verified_ok = False
            self._debug("EH 登录开关=关，当前使用游客会话")
            return False

        cfg = self._load_eh_config()
        signature = tuple(cfg.get(k, "") for k in EH_COOKIE_KEYS)
        if not signature[0] or not signature[1]:
            with self._lock:
                if self._cookie_signature is not None:
                    while self._active_requests:
                        self._request_idle.wait()
                    self._clear_eh_cookies_locked()
                self._cookie_signature = None
                self._login_configured = True
                self._verified_at = 0.0
                self._verified_ok = False
            self._debug("EH 登录开关=开，但缺少 ipb_member_id/ipb_pass_hash")
            return False

        with self._lock:
            if signature == self._cookie_signature:
                return True
            while self._active_requests:
                self._request_idle.wait()
            for domain in (".e-hentai.org", ".exhentai.org", "hentaiverse.org"):
                for key, value in zip(EH_COOKIE_KEYS, signature):
                    if value:
                        self.session.cookies.set(key, value, domain=domain)
            self._cookie_signature = signature
            self._login_configured = True
            self._verified_at = 0.0
            self._verified_ok = False
            self._debug(f"已从配置载入 EH Cookie has_cookie={self.has_eh_cookie()}")
            return True

    def has_eh_cookie(self) -> bool:
        with self._lock:
            return any(cookie.name == "ipb_member_id" and cookie.value for cookie in self.session.cookies)

    def ensure_logged_in(self, *, force: bool = False) -> bool:
        if not self.configure_from_storage():
            return False
        now = time.time()
        with self._lock:
            if not force and self._verified_ok and now - self._verified_at < self.verify_ttl_seconds:
                self._debug("登录验证缓存命中")
                return True
            with self._timer("验证登录 GET favorites.php"):
                resp = self.session.get("https://e-hentai.org/favorites.php", timeout=30)
            ok = resp.status_code == 200 and len(resp.text.strip()) >= 500 and "Favorites" in resp.text
            self._debug(f"登录验证结果 status={resp.status_code} bytes={len(resp.content)} ok={ok}")
            self._verified_at = now
            self._verified_ok = ok
            return ok

    def get_eh_client(self, *, domain: str = EH_DOMAIN_EH, require_login: bool = False) -> EHentaiClient:
        if require_login:
            if not self.ensure_logged_in():
                raise RuntimeError("请先在账户页填写有效凭据")
        else:
            self.configure_from_storage()
        self._debug(f"创建 EH 客户端 要求登录={require_login} 登录开关={self.login_enabled()} 已有Cookie={self.has_eh_cookie()}")
        return EHentaiClient(domain=domain, session=self._client_session, log_debug=self._log_debug)

    def get_session(self) -> requests.Session:
        self.configure_from_storage()
        return self.session

    def proxy_status_text(self) -> str:
        self.configure_proxy_from_storage()
        mode = self._proxy_signature[0] if self._proxy_signature else "disabled"
        if mode == "manual":
            parsed = urlsplit(self._proxy_signature[1])
            return f"手动代理 · {parsed.hostname}:{parsed.port or 80}"
        if mode == "system":
            return "跟随系统环境代理"
        return "代理已关闭"

    def get(self, url: str, **kwargs) -> requests.Response:
        quiet_image = is_image_request_url(url)
        with self._request_lease():
            if quiet_image:
                resp = self.session.get(url, **kwargs)
            else:
                with self._timer(f"GET {url}"):
                    resp = self.session.get(url, **kwargs)
        if kwargs.get("stream"):
            self._debug(f"GET 流式完成 状态码={resp.status_code} 最终URL={redact_url(resp.url)}")
        elif not quiet_image or resp.status_code >= 400:
            self._debug(f"GET 完成 状态码={resp.status_code} 字节数={len(resp.content)} 最终URL={redact_url(resp.url)}")
        return resp

    def post(self, url: str, **kwargs) -> requests.Response:
        with self._request_lease():
            with self._timer(f"POST {url}"):
                resp = self.session.post(url, **kwargs)
        self._debug(f"POST 完成 状态码={resp.status_code} 字节数={len(resp.content)} 最终URL={redact_url(resp.url)}")
        return resp

    def head(self, url: str, **kwargs) -> requests.Response:
        with self._request_lease():
            with self._timer(f"HEAD {url}"):
                resp = self.session.head(url, **kwargs)
        self._debug(f"HEAD 完成 状态码={resp.status_code} 最终URL={redact_url(resp.url)}")
        return resp

    def _clear_eh_cookies_locked(self) -> None:
        for domain in (".e-hentai.org", ".exhentai.org", "hentaiverse.org"):
            for key in EH_COOKIE_KEYS:
                try:
                    self.session.cookies.clear(domain=domain, path="/", name=key)
                except KeyError:
                    pass

    @contextmanager
    def _request_lease(self):
        with self._lock:
            # 通用 Provider/图片请求只共享代理和连接池；EH Cookie 仅由 get_eh_client 配置。
            self.configure_proxy_from_storage()
            self._active_requests += 1
        try:
            yield
        finally:
            with self._lock:
                self._active_requests -= 1
                if not self._active_requests:
                    self._request_idle.notify_all()

    def _debug(self, message: str) -> None:
        self._log_debug("浏览器会话", message)

    def _timer(self, message: str):
        return self._timer_factory("浏览器会话", message)


class _NullTimer:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _BrowserSessionFacade:
    """让 provider 复用统一请求入口，同时保留 requests.Session 常用接口。"""

    def __init__(self, service: BrowserSessionService):
        self._service = service

    @property
    def headers(self):
        return self._service.session.headers

    @property
    def cookies(self):
        return self._service.session.cookies

    def get(self, url: str, **kwargs) -> requests.Response:
        return self._service.get(url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self._service.post(url, **kwargs)

    def head(self, url: str, **kwargs) -> requests.Response:
        return self._service.head(url, **kwargs)
