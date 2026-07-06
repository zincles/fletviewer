from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .camoufox_solver import CamoufoxSolveResult, is_common_challenge_html


# 实验用本地缓存目录。这里会保存真实 cookie 值，必须保持 gitignore，绝不能提交。
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "browser_profiles"


@dataclass(slots=True)
class BrowserProfileCache:
    # profile 是逻辑浏览器状态桶，不一定等同单个 origin。
    # 除非有明确理由，否则 EH 论坛、EH 主站、Danbooru、Pixiv 等都应该分开缓存。
    profile: str
    origin: str
    user_agent: str
    cookies: list[dict[str, Any]]
    created_at: str
    updated_at: str
    source_url: str = ""
    final_url: str = ""

    @property
    def cookie_names(self) -> list[str]:
        return [str(cookie.get("name")) for cookie in self.cookies if cookie.get("name")]


class BrowserCacheManager:
    '''
    基于 profile 的浏览器状态缓存管理器。

    缓存内容包括 cookies 和生成这些 cookies 时使用的浏览器 user-agent。
    使用缓存前应调用 verify_with_curl() 验证，因为 CF cookie 可能在本地 expires 前提前失效。
    '''

    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self._memory: dict[str, BrowserProfileCache] = {}

    def get(self, profile: str) -> BrowserProfileCache | None:
        '''从内存或磁盘加载 profile，但不验证其是否仍然有效。'''
        profile = normalize_profile(profile)
        if profile in self._memory:
            return self._memory[profile]
        path = self.path_for(profile)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        cache = BrowserProfileCache(**data)
        self._memory[profile] = cache
        return cache

    def save(self, cache: BrowserProfileCache) -> BrowserProfileCache:
        '''
        持久化 profile。

        序列化内容包含真实 cookie value，不要把完整 JSON 打到日志里。
        '''
        cache.profile = normalize_profile(cache.profile)
        now = utc_now()
        if not cache.created_at:
            cache.created_at = now
        cache.updated_at = now
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.path_for(cache.profile).write_text(json.dumps(asdict(cache), ensure_ascii=False, indent=2), encoding="utf-8")
        self._memory[cache.profile] = cache
        return cache

    def save_solve_result(
        self,
        result: CamoufoxSolveResult,
        *,
        profile: str | None = None,
        origin: str | None = None,
    ) -> BrowserProfileCache:
        '''将 Camoufox 解盾结果保存为指定逻辑 profile。'''
        origin = origin or origin_from_url(result.url)
        profile = normalize_profile(profile or profile_from_origin(origin))
        existing = self.get(profile)
        cache = BrowserProfileCache(
            profile=profile,
            origin=origin,
            user_agent=result.user_agent,
            cookies=result.cookies,
            created_at=existing.created_at if existing else utc_now(),
            updated_at=utc_now(),
            source_url=result.url,
            final_url=result.final_url,
        )
        return self.save(cache)

    def apply_to_curl_session(self, session: Any, cache: BrowserProfileCache) -> None:
        '''将缓存中的 user-agent 和 cookies 注入 curl_cffi 风格的 session。'''
        if cache.user_agent:
            session.headers.update({"User-Agent": cache.user_agent})
        for cookie in cache.cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if not name or value is None:
                continue
            session.cookies.set(
                name,
                value,
                domain=cookie.get("domain") or urlparse(cache.origin).hostname,
                path=cookie.get("path") or "/",
            )

    def verify_with_curl(self, profile: str, url: str, *, impersonate: str = "chrome") -> bool:
        '''
        使用 curl_cffi 验证缓存是否仍能访问目标 URL。

        只有请求成功且响应不再包含 challenge HTML 时才返回 True。
        '''
        cache = self.get(profile)
        if not cache:
            print("browser cache: miss", normalize_profile(profile))
            return False
        try:
            from curl_cffi import requests
        except ModuleNotFoundError:
            print("curl_cffi is not installed; cannot verify cache")
            return False

        session = requests.Session(impersonate=impersonate)
        session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        self.apply_to_curl_session(session, cache)
        response = session.get(url, timeout=45, allow_redirects=True)
        challenge = is_common_challenge_html(response.text)
        print("browser cache verify profile:", cache.profile)
        print("browser cache verify status:", response.status_code)
        print("browser cache verify challenge:", challenge)
        return response.ok and not challenge

    def path_for(self, profile: str) -> Path:
        return self.cache_dir / f"{normalize_profile(profile)}.json"


def origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def profile_from_origin(origin: str) -> str:
    host = urlparse(origin).hostname or origin
    return host.lower()


def normalize_profile(profile: str) -> str:
    '''归一化 profile 名称，使其可以安全用作文件名。'''
    return "".join(ch if ch.isalnum() or ch in {".", "-", "_"} else "_" for ch in profile.strip().lower())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


browser_cache = BrowserCacheManager()
