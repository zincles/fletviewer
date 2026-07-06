from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tmp.lib.challenge import browser_cache, solve_with_camoufox


TARGETS = {
    "eh-forum": {
        "url": "https://forums.e-hentai.org/",
        "profile": "eh-forum",
    },
    "danbooru": {
        "url": "https://danbooru.donmai.us/posts.json?tags=cat+rating%3Ageneral&page=1&limit=3",
        "profile": "danbooru",
    },
}


def eh_forum_success(title: str, html: str, cookies: list[dict[str, Any]]) -> bool:
    '''EH 论坛的成功条件：进入论坛标题，或拿到 cf_clearance。'''
    names = {str(cookie.get("name")) for cookie in cookies}
    return "E-Hentai Forums" in title or "cf_clearance" in names


def danbooru_success(title: str, html: str, cookies: list[dict[str, Any]]) -> bool:
    '''Danbooru API 在 Camoufox 中会被 Firefox 包成 HTML pre，因此用内容前缀判断 JSON。'''
    return html.lstrip().startswith("<html") and "[{" in html


def success_predicate_for(name: str):
    return eh_forum_success if name == "eh-forum" else danbooru_success


def main() -> int:
    '''验证浏览器 profile 缓存是否可用；不可用时调用 Camoufox 解盾并保存缓存。'''
    args = sys.argv[1:]
    target_name = next((arg for arg in args if not arg.startswith("--")), "eh-forum")
    target = TARGETS.get(target_name, {"url": target_name, "profile": target_name})
    url = target["url"]
    profile = target["profile"]
    force = "--force" in args

    cache = browser_cache.get(profile)
    if cache:
        print("cache found:", cache.profile, cache.origin, cache.cookie_names, cache.updated_at)
    else:
        print("cache miss:", profile)

    if cache and not force and browser_cache.verify_with_curl(profile, url):
        print("cache is valid")
        return 0

    print("solving with Camoufox:", url)
    result = solve_with_camoufox(
        url,
        headless="--visible" not in args,
        humanize=True,
        disable_coop=True,
        auto_click=True,
        success_predicate=success_predicate_for(target_name),
    )
    print("solved:", result.solved)
    print("title:", result.title)
    print("cookies:", result.cookie_names)
    if not result.solved:
        return 1

    saved = browser_cache.save_solve_result(result, profile=profile)
    print("cache saved:", saved.profile, saved.origin, saved.cookie_names, saved.updated_at)

    if browser_cache.verify_with_curl(profile, url):
        print("saved cache is valid")
        return 0
    print("saved cache failed verification")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
