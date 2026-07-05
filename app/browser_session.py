import threading
import time
from urllib.parse import urlsplit

import requests

from app.debug_log import Timer, log_debug
from app.storage import load_app_config, load_eh_config
from lib.provider.ehgrabber import EH_DOMAIN_EH, EHentaiClient

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif")


def _is_image_request_url(url: str) -> bool:
    """判断 URL 是否像图片资源请求，用于降低高频图片日志噪音。"""
    path = urlsplit(url).path.lower()
    return path.endswith(_IMAGE_SUFFIXES)


class BrowserSessionService:
    """维护全局浏览器式会话，统一 EH Cookie、UA、连接复用和登录验证。"""

    def __init__(self):
        """创建 requests.Session 并设置浏览器请求头。"""
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
                "Connection": "keep-alive",
            }
        )
        self._lock = threading.RLock()
        self._cookie_signature: tuple[str, str, str, str] | None = None
        self._verified_at = 0.0
        self._verified_ok = False
        self.verify_ttl_seconds = 300

    def login_enabled(self) -> bool:
        """返回应用配置中是否启用自动登录。"""
        return bool(load_app_config().get("enable_login", True))

    def login_status_text(self) -> str:
        """返回给设置页展示的登录状态文字。"""
        if not self.login_enabled():
            return "游客模式"
        cfg = load_eh_config()
        if not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash"):
            return "登录已启用，但缺少必填凭据"
        with self._lock:
            if self._verified_ok and time.time() - self._verified_at < self.verify_ttl_seconds:
                return "已登录（验证缓存有效）"
            if self._cookie_signature:
                return "登录已启用，Cookie 已载入"
        return "登录已启用，等待载入 Cookie"

    def login_status_level(self) -> str:
        """返回登录状态等级，用于设置页状态灯。"""
        if not self.login_enabled():
            return "guest"
        cfg = load_eh_config()
        if not cfg.get("ipb_member_id") or not cfg.get("ipb_pass_hash"):
            return "warning"
        with self._lock:
            if self._verified_ok and time.time() - self._verified_at < self.verify_ttl_seconds:
                return "ok"
            if self._cookie_signature:
                return "pending"
        return "warning"

    def set_login_enabled(self, enabled: bool, *, verify: bool = True) -> bool:
        """切换网络单例的登录/游客模式；开启时可立即验证登录。"""
        with self._lock:
            self._verified_at = 0.0
            self._verified_ok = False
            if not enabled:
                self._clear_eh_cookies_locked()
                self._cookie_signature = None
                log_debug("浏览器会话", "EH 登录开关=关，已清理 Cookie")
                return False
        if verify:
            return self.ensure_logged_in(force=True)
        return self.configure_from_storage()

    def _clear_eh_cookies_locked(self) -> None:
        """清理会话中 EH/ExHentai 相关 Cookie；调用方需持有锁。"""
        for domain in (".e-hentai.org", ".exhentai.org"):
            for key in ("ipb_member_id", "ipb_pass_hash", "igneous", "star"):
                try:
                    self.session.cookies.clear(domain=domain, path="/", name=key)
                except KeyError:
                    pass

    def configure_from_storage(self) -> bool:
        """按当前登录开关从配置载入 Cookie；关闭登录时进入游客模式。"""
        if not self.login_enabled():
            with self._lock:
                self._clear_eh_cookies_locked()
                self._cookie_signature = None
                self._verified_at = 0.0
                self._verified_ok = False
            log_debug("浏览器会话", "EH 登录开关=关，当前使用游客会话")
            return False

        cfg = load_eh_config()
        signature = tuple(cfg.get(k, "") for k in ("ipb_member_id", "ipb_pass_hash", "igneous", "star"))
        if not signature[0] or not signature[1]:
            log_debug("浏览器会话", "EH 登录开关=开，但缺少 ipb_member_id/ipb_pass_hash")
            return False

        with self._lock:
            if signature == self._cookie_signature:
                return True

            for domain in (".e-hentai.org", ".exhentai.org"):
                for key, value in zip(("ipb_member_id", "ipb_pass_hash", "igneous", "star"), signature):
                    if value:
                        self.session.cookies.set(key, value, domain=domain)
            self._cookie_signature = signature
            self._verified_at = 0.0
            self._verified_ok = False
            log_debug("浏览器会话", f"已从配置载入 EH Cookie has_cookie={self.has_eh_cookie()}")
            return True

    def has_eh_cookie(self) -> bool:
        """检查当前 Session 是否已有 EH 登录 Cookie。"""
        with self._lock:
            return any(cookie.name == "ipb_member_id" and cookie.value for cookie in self.session.cookies)

    def ensure_logged_in(self, *, force: bool = False) -> bool:
        """验证当前 Cookie 是否能访问登录必需页面，并缓存验证结果。"""
        if not self.configure_from_storage():
            return False

        now = time.time()
        with self._lock:
            if not force and self._verified_ok and now - self._verified_at < self.verify_ttl_seconds:
                log_debug("浏览器会话", "登录验证缓存命中")
                return True

            with Timer("浏览器会话", "验证登录 GET favorites.php"):
                resp = self.session.get("https://e-hentai.org/favorites.php", timeout=30)
            ok = resp.status_code == 200 and len(resp.text.strip()) >= 500 and "Favorites" in resp.text
            log_debug("浏览器会话", f"登录验证结果 status={resp.status_code} bytes={len(resp.content)} ok={ok}")
            self._verified_at = now
            self._verified_ok = ok
            return ok

    def get_eh_client(self, *, domain: str = EH_DOMAIN_EH, require_login: bool = False) -> EHentaiClient:
        """创建复用全局 Session 的 EH client；必要时先验证登录。"""
        if require_login:
            if not self.ensure_logged_in():
                raise RuntimeError("请先在账户页填写有效凭据")
        else:
            self.configure_from_storage()
        log_debug("浏览器会话", f"创建 EH 客户端 require_login={require_login} 登录开关={self.login_enabled()} has_cookie={self.has_eh_cookie()}")
        return EHentaiClient(domain=domain, session=self.session)

    def get_session(self) -> requests.Session:
        """返回底层 requests.Session，供需要自定义请求行为的服务使用。"""
        self.configure_from_storage()
        return self.session

    def get(self, url: str, **kwargs) -> requests.Response:
        """用全局会话发起 GET 请求，并记录耗时与响应摘要。"""
        self.configure_from_storage()
        quiet_image = _is_image_request_url(url)
        with self._lock:
            if quiet_image:
                resp = self.session.get(url, **kwargs)
            else:
                with Timer("浏览器会话", f"GET {url}"):
                    resp = self.session.get(url, **kwargs)
            if kwargs.get("stream"):
                log_debug("浏览器会话", f"GET 流式完成 status={resp.status_code} final_url={resp.url}")
            elif not quiet_image or resp.status_code >= 400:
                log_debug("浏览器会话", f"GET 完成 status={resp.status_code} bytes={len(resp.content)} final_url={resp.url}")
            return resp

    def post(self, url: str, **kwargs) -> requests.Response:
        """用全局会话发起 POST 请求，并记录耗时与响应摘要。"""
        self.configure_from_storage()
        with self._lock:
            with Timer("浏览器会话", f"POST {url}"):
                resp = self.session.post(url, **kwargs)
                log_debug("浏览器会话", f"POST 完成 status={resp.status_code} bytes={len(resp.content)} final_url={resp.url}")
            return resp

    def head(self, url: str, **kwargs) -> requests.Response:
        """用全局会话发起 HEAD 请求，并记录耗时与响应摘要。"""
        self.configure_from_storage()
        with self._lock:
            with Timer("浏览器会话", f"HEAD {url}"):
                resp = self.session.head(url, **kwargs)
                log_debug("浏览器会话", f"HEAD 完成 status={resp.status_code} final_url={resp.url}")
            return resp


browser_session = BrowserSessionService()
