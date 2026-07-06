from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tmp.lib.challenge import browser_cache
from tmp.lib.challenge.camoufox_solver import html_prefix, is_common_challenge_html


TARGETS = {
    "eh-forum": {
        "url": "https://forums.e-hentai.org/",
        "profile": "eh-forum",
        "mode": "html",
    },
    "danbooru": {
        "url": "https://danbooru.donmai.us/posts.json?tags=cat+rating%3Ageneral&page=1&limit=3",
        "profile": "danbooru",
        "mode": "json",
    },
}


def fetch_with_cache(name: str) -> bool:
    '''
    只使用已保存的 browser_cache 访问目标站，不启动 Camoufox。

    这个 probe 用来确认缓存 cookies + user-agent 是否足够让 curl_cffi 继续访问目标站。
    '''
    try:
        from curl_cffi import requests
    except ModuleNotFoundError:
        print("curl_cffi is not installed; run `pip install curl_cffi` first")
        return False

    target = TARGETS[name]
    cache = browser_cache.get(target["profile"])
    if not cache:
        print("cache miss:", target["profile"])
        return False

    session = requests.Session(impersonate="chrome")
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    browser_cache.apply_to_curl_session(session, cache)

    response = session.get(target["url"], timeout=45, allow_redirects=True)
    challenge = is_common_challenge_html(response.text)
    print("=" * 80)
    print("target:", name)
    print("profile:", cache.profile)
    print("origin:", cache.origin)
    print("cookie names:", cache.cookie_names)
    print("status:", response.status_code)
    print("url:", response.url)
    print("content-type:", response.headers.get("Content-Type", ""))
    print("challenge markers:", challenge)

    if target["mode"] == "json":
        try:
            data = response.json()
        except ValueError:
            print("json parse failed")
            print("prefix:", html_prefix(response.text))
            return False
        print("json type:", type(data).__name__)
        print("json items:", len(data) if isinstance(data, list) else "n/a")
        if isinstance(data, list) and data:
            print("first post:", data[0].get("id"), data[0].get("preview_file_url"))
        return response.ok and not challenge and isinstance(data, list)

    print("prefix:", html_prefix(response.text))
    return response.ok and not challenge


def main() -> int:
    '''默认验证所有内置目标，也可以指定单个目标名称。'''
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    targets = args or list(TARGETS)
    ok = True
    for name in targets:
        if name not in TARGETS:
            print("unknown target:", name)
            ok = False
            continue
        ok = fetch_with_cache(name) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
