from __future__ import annotations

import json
from typing import Any


DANBOORU_POSTS = "https://danbooru.donmai.us/posts.json"
POSTS_QUERY = {"tags": "cat rating:general", "page": 1, "limit": 3}


def is_cloudflare_html(text: str) -> bool:
    markers = [
        "Just a moment",
        "/cdn-cgi/challenge-platform/",
        "cf-browser-verification",
        "cf-challenge",
        "challenges.cloudflare.com",
    ]
    return any(marker in text for marker in markers)


def try_impersonation(impersonate: str) -> bool:
    '''
    用指定浏览器指纹测试 Danbooru API 是否能直接返回 JSON。

    这个 probe 用来区分“需要真浏览器”还是“只需要更像浏览器的 transport”。
    '''
    from curl_cffi import requests

    session = requests.Session(impersonate=impersonate)
    session.headers.update(
        {
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://danbooru.donmai.us/",
        }
    )
    response = session.get(DANBOORU_POSTS, params=POSTS_QUERY, timeout=30)
    print("=" * 80)
    print("impersonate:", impersonate)
    print("status:", response.status_code)
    print("content-type:", response.headers.get("Content-Type"))
    print("cf html:", is_cloudflare_html(response.text))

    data: Any
    try:
        data = response.json()
    except ValueError:
        print(response.text[:800].replace("\n", " "))
        return False

    print("json type:", type(data).__name__)
    if isinstance(data, list):
        print("json posts:", len(data))
        if data:
            print("first post:", data[0].get("id"), data[0].get("preview_file_url"))
    else:
        print(json.dumps(data, ensure_ascii=False)[:800])
    return response.ok and isinstance(data, list)


def main() -> int:
    '''依次尝试多个 curl_cffi impersonation preset。'''
    try:
        import curl_cffi  # noqa: F401
    except ModuleNotFoundError:
        print("curl_cffi is not installed. Install it first, then rerun:")
        print("  pip install curl_cffi")
        return 2

    impersonations = [
        "chrome",
        "chrome124",
        "chrome120",
        "chrome110",
        "safari",
        "safari17_0",
        "firefox",
    ]
    for impersonate in impersonations:
        try:
            if try_impersonation(impersonate):
                print("success with:", impersonate)
                return 0
        except Exception as exc:
            print("=" * 80)
            print("impersonate:", impersonate)
            print(type(exc).__name__, exc)

    print("no impersonation succeeded")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
