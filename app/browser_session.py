import threading
import time

import requests

from app.debug_log import Timer, log_debug
from app.storage import load_eh_config
from lib.provider.ehgrabber import EH_DOMAIN_EH, EHentaiClient

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class BrowserSessionService:
    def __init__(self):
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

    def configure_from_storage(self) -> bool:
        cfg = load_eh_config()
        signature = tuple(cfg.get(k, "") for k in ("ipb_member_id", "ipb_pass_hash", "igneous", "star"))
        if not signature[0] or not signature[1]:
            log_debug("browser", "no EH credentials configured")
            return False

        with self._lock:
            if signature == self._cookie_signature:
                log_debug("browser", "EH cookies already configured")
                return True

            for domain in (".e-hentai.org", ".exhentai.org"):
                for key, value in zip(("ipb_member_id", "ipb_pass_hash", "igneous", "star"), signature):
                    if value:
                        self.session.cookies.set(key, value, domain=domain)
            self._cookie_signature = signature
            self._verified_at = 0.0
            self._verified_ok = False
            log_debug("browser", "EH cookies configured from storage")
            return True

    def ensure_logged_in(self, *, force: bool = False) -> bool:
        if not self.configure_from_storage():
            return False

        now = time.time()
        with self._lock:
            if not force and self._verified_ok and now - self._verified_at < self.verify_ttl_seconds:
                log_debug("browser", "login verification cache hit")
                return True

            with Timer("browser", "verify login GET https://e-hentai.org/favorites.php"):
                resp = self.session.get("https://e-hentai.org/favorites.php", timeout=30)
            ok = resp.status_code == 200 and len(resp.text.strip()) >= 500 and "Favorites" in resp.text
            log_debug("browser", f"verify login status={resp.status_code} bytes={len(resp.content)} ok={ok}")
            self._verified_at = now
            self._verified_ok = ok
            return ok

    def get_eh_client(self, *, domain: str = EH_DOMAIN_EH, require_login: bool = False) -> EHentaiClient:
        if require_login:
            if not self.ensure_logged_in():
                raise RuntimeError("请先在账户页填写有效凭据")
        else:
            self.configure_from_storage()
        return EHentaiClient(domain=domain, session=self.session)

    def get_session(self) -> requests.Session:
        self.configure_from_storage()
        return self.session

    def get(self, url: str, **kwargs) -> requests.Response:
        self.configure_from_storage()
        with self._lock:
            with Timer("browser", f"GET {url}"):
                resp = self.session.get(url, **kwargs)
            if kwargs.get("stream"):
                log_debug("browser", f"GET status={resp.status_code} stream final_url={resp.url}")
            else:
                log_debug("browser", f"GET status={resp.status_code} bytes={len(resp.content)} final_url={resp.url}")
            return resp

    def post(self, url: str, **kwargs) -> requests.Response:
        self.configure_from_storage()
        with self._lock:
            with Timer("browser", f"POST {url}"):
                resp = self.session.post(url, **kwargs)
            log_debug("browser", f"POST status={resp.status_code} bytes={len(resp.content)} final_url={resp.url}")
            return resp

    def head(self, url: str, **kwargs) -> requests.Response:
        self.configure_from_storage()
        with self._lock:
            with Timer("browser", f"HEAD {url}"):
                resp = self.session.head(url, **kwargs)
            log_debug("browser", f"HEAD status={resp.status_code} final_url={resp.url}")
            return resp


browser_session = BrowserSessionService()
