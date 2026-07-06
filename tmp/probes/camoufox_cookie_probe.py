from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tmp.lib.challenge import solve_with_camoufox
from tmp.lib.challenge.camoufox_solver import is_common_challenge_html


TARGETS = {
    "eh-forum": "https://forums.e-hentai.org/",
    "danbooru": "https://danbooru.donmai.us/posts.json?tags=cat+rating%3Ageneral&page=1&limit=3",
}


def eh_forum_success(title: str, html: str, cookies: list[dict[str, Any]]) -> bool:
    '''EH 论坛的成功条件：页面标题进入论坛，或已经拿到 cf_clearance。'''
    names = {str(cookie.get("name")) for cookie in cookies}
    return "E-Hentai Forums" in title or "cf_clearance" in names


def danbooru_success(title: str, html: str, cookies: list[dict[str, Any]]) -> bool:
    '''Danbooru API 的成功条件：浏览器页面中已经出现 JSON 内容。'''
    text = html.lstrip()
    return text.startswith("<html") and "danbooru" in title.lower() or text.startswith("[")


def parse_humanize(args: list[str]) -> bool | float:
    '''解析 Camoufox humanize 参数。'''
    if "--humanize" in args:
        return True
    for arg in args:
        if arg.startswith("--humanize="):
            return float(arg.split("=", 1)[1])
    return True


def main() -> int:
    '''
    用通用 solve_with_camoufox() 测试指定目标。

    这里只打印 cookie 名称，不打印 cookie 值。
    '''
    args = sys.argv[1:]
    target_name = next((arg for arg in args if not arg.startswith("--")), "eh-forum")
    url = TARGETS.get(target_name, target_name)
    success_predicate = eh_forum_success if target_name == "eh-forum" else danbooru_success

    result = solve_with_camoufox(
        url,
        headless="--visible" not in args,
        humanize=parse_humanize(args),
        disable_coop="--no-disable-coop" not in args,
        auto_click="--no-auto-click" not in args,
        success_predicate=success_predicate,
    )

    print("target:", target_name)
    print("url:", result.url)
    print("final url:", result.final_url)
    print("title:", result.title)
    print("solved:", result.solved)
    print("challenge detected:", result.challenge_detected)
    print("cookie names:", result.cookie_names)
    print("common challenge html:", is_common_challenge_html(result.html_prefix))
    print("html prefix:", result.html_prefix)
    return 0 if result.solved else 1


if __name__ == "__main__":
    raise SystemExit(main())
