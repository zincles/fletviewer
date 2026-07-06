from __future__ import annotations

from typing import Any

import requests


def create_requests_session() -> requests.Session:
    '''创建普通 requests session。只作为 fallback；遇到 Cloudflare/TLS 指纹拦截时通常不够用。'''
    session = requests.Session()
    session.headers.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FletViewer/tmp-booru-probe")
    return session


def create_curl_cffi_session(*, impersonate: str = "chrome") -> Any:
    '''创建 curl_cffi session，用浏览器 TLS/HTTP 指纹访问目标站。'''
    try:
        from curl_cffi import requests as curl_requests
    except ModuleNotFoundError as exc:
        raise RuntimeError("curl_cffi is not installed; run `pip install curl_cffi` first") from exc
    return curl_requests.Session(impersonate=impersonate)


def create_browser_like_session(*, impersonate: str = "chrome") -> Any:
    '''优先创建 curl_cffi session；不可用时回退 requests。'''
    try:
        return create_curl_cffi_session(impersonate=impersonate)
    except RuntimeError:
        return create_requests_session()
