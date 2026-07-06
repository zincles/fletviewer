from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests


DANBOORU_HOME = "https://danbooru.donmai.us/"
DANBOORU_POSTS = "https://danbooru.donmai.us/posts.json"
POSTS_QUERY = {"tags": "cat rating:general", "page": 1, "limit": 3}


@dataclass(slots=True)
class BrowserState:
    '''
    早期 Danbooru Camoufox 实验用状态结构。

    后续通用代码请优先使用 tmp.lib.challenge.CamoufoxSolveResult。
    '''
    user_agent: str
    cookies: list[dict[str, Any]]


def is_cloudflare_html(text: str) -> bool:
    markers = [
        "Just a moment",
        "/cdn-cgi/challenge-platform/",
        "cf-browser-verification",
        "cf-challenge",
        "challenges.cloudflare.com",
    ]
    return any(marker in text for marker in markers)


def import_browser_cookies(session: requests.Session, cookies: list[dict[str, Any]]) -> None:
    '''
    将 Camoufox cookies 注入 requests session。

    这个早期实验用于证明：Danbooru 的 Camoufox cookie + UA 不能让 vanilla requests 通过 CF。
    '''
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        session.cookies.set(
            name,
            value,
            domain=cookie.get("domain") or ".danbooru.donmai.us",
            path=cookie.get("path") or "/",
        )


def verify_with_requests(state: BrowserState) -> bool:
    '''用 vanilla requests 验证 Camoufox cookie handoff 是否足够。'''
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": state.user_agent,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": DANBOORU_HOME,
        }
    )
    import_browser_cookies(session, state.cookies)

    response = session.get(
        DANBOORU_POSTS,
        params=POSTS_QUERY,
        timeout=30,
    )
    print("requests status:", response.status_code)
    print("requests content-type:", response.headers.get("Content-Type"))
    print("requests cf html:", is_cloudflare_html(response.text))

    try:
        data = response.json()
    except ValueError:
        print(response.text[:800].replace("\n", " "))
        return False

    print("json posts:", len(data) if isinstance(data, list) else type(data).__name__)
    if isinstance(data, list) and data:
        print("first post:", data[0].get("id"), data[0].get("preview_file_url"))
    return response.ok and isinstance(data, list)


def solve_with_camoufox(*, headless: bool = False, timeout_ms: int = 120_000) -> BrowserState:
    '''
    早期 Danbooru 专用 Camoufox probe。

    新代码请优先使用 tmp.lib.challenge.solve_with_camoufox()。
    '''
    try:
        from camoufox.sync_api import Camoufox
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "camoufox is not installed. Install it in this environment first, then rerun:\n"
            "  pip install camoufox\n"
            "  python -m camoufox fetch\n"
        ) from exc

    with Camoufox(headless=headless) as browser:
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        print("opening:", DANBOORU_HOME)
        page.goto(DANBOORU_HOME, wait_until="domcontentloaded", timeout=timeout_ms)
        wait_for_cloudflare(page, timeout_ms=timeout_ms)

        api_url = f"{DANBOORU_POSTS}?{urlencode(POSTS_QUERY)}"
        print("opening api:", api_url)
        page.goto(api_url, wait_until="domcontentloaded", timeout=timeout_ms)
        wait_for_cloudflare(page, timeout_ms=timeout_ms)
        api_text = page.locator("body").inner_text(timeout=10_000)
        print("browser api body prefix:", api_text[:500].replace("\n", " "))

        user_agent = page.evaluate("navigator.userAgent")
        cookies = page.context.cookies(DANBOORU_HOME)
        print("browser user-agent:", user_agent)
        print("browser cookies:", [cookie.get("name") for cookie in cookies])

        return BrowserState(user_agent=user_agent, cookies=cookies)


def wait_for_cloudflare(page: Any, *, timeout_ms: int) -> None:
    '''等待页面不再包含常见 Cloudflare markers。'''
    deadline = time.monotonic() + timeout_ms / 1000
    last_title = ""
    while time.monotonic() < deadline:
        title = page.title()
        html = page.content()
        if title != last_title:
            print("page title:", title)
            last_title = title

        if not is_cloudflare_html(html):
            print("cloudflare markers cleared")
            return

        print("waiting for challenge to clear...")
        page.wait_for_timeout(3000)

    print("challenge wait timed out; continuing with current browser state")


def main() -> int:
    '''运行早期 Danbooru Camoufox cookie handoff 实验。'''
    headless = "--headless" in sys.argv
    state = solve_with_camoufox(headless=headless)
    print("state json:")
    print(json.dumps({"user_agent": state.user_agent, "cookies": state.cookies}, ensure_ascii=False, indent=2)[:2000])
    ok = verify_with_requests(state)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
