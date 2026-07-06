from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tmp.lib.challenge import CamoufoxSolveResult, solve_with_camoufox
from tmp.lib.challenge.camoufox_solver import html_prefix, is_common_challenge_html


DEFAULT_URL = "https://forums.e-hentai.org/"


@dataclass(slots=True)
class CurlProbeResult:
    ok: bool
    status: int
    content_type: str
    challenge: bool


def eh_forum_success(title: str, html: str, cookies: list[dict[str, Any]]) -> bool:
    '''EH 论坛的成功条件：进入论坛标题，或拿到 cf_clearance。'''
    cookie_names = {str(cookie.get("name")) for cookie in cookies}
    return "E-Hentai Forums" in title or "cf_clearance" in cookie_names


def probe_curl_cffi(url: str, impersonate: str = "chrome") -> CurlProbeResult:
    '''
    不使用 Camoufox，直接测试 curl_cffi 是否能访问 EH 论坛。

    当前实验结论是：EH 论坛交互式 CF challenge 下 curl_cffi 单独不够。
    '''
    try:
        from curl_cffi import requests
    except ModuleNotFoundError as exc:
        raise SystemExit("curl_cffi is not installed; run `pip install curl_cffi` first") from exc

    session = requests.Session(impersonate=impersonate)
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    response = session.get(url, timeout=45, allow_redirects=True)
    challenge = is_common_challenge_html(response.text)
    print("curl_cffi impersonate:", impersonate)
    print("status:", response.status_code)
    print("url:", response.url)
    print("content-type:", response.headers.get("Content-Type", ""))
    print("challenge markers:", challenge)
    print("cookies:", [cookie.name for cookie in session.cookies.jar])
    print("prefix:", html_prefix(response.text))
    return CurlProbeResult(
        ok=response.ok and not challenge,
        status=response.status_code,
        content_type=response.headers.get("Content-Type", ""),
        challenge=challenge,
    )


def verify_cookies_with_curl(url: str, result: CamoufoxSolveResult) -> bool:
    '''将 Camoufox 解盾后的 cookies + user-agent 注入 curl_cffi，并验证后续访问。'''
    if not result.cookies:
        print("no browser cookies to verify")
        return False
    try:
        from curl_cffi import requests
    except ModuleNotFoundError:
        print("curl_cffi is not installed; skipping cookie verification")
        return False

    session = requests.Session(impersonate="chrome")
    session.headers.update(
        {
            "User-Agent": result.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    for cookie in result.cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        session.cookies.set(name, value, domain=cookie.get("domain") or "forums.e-hentai.org", path=cookie.get("path") or "/")

    response = session.get(url, timeout=45, allow_redirects=True)
    challenge = is_common_challenge_html(response.text)
    print("curl verify status:", response.status_code)
    print("curl verify url:", response.url)
    print("curl verify content-type:", response.headers.get("Content-Type", ""))
    print("curl verify challenge markers:", challenge)
    print("curl verify prefix:", html_prefix(response.text))
    return response.ok and not challenge


def parse_humanize(args: list[str]) -> bool | float:
    '''解析 Camoufox humanize 参数。'''
    if "--humanize" in args:
        return True
    for arg in args:
        if arg.startswith("--humanize="):
            return float(arg.split("=", 1)[1])
    return False


def main() -> int:
    '''
    EH 论坛 challenge 专用 probe。

    默认先测试 curl_cffi；传入 --camoufox 时使用 Camoufox 解盾并验证 cookie handoff。
    '''
    args = sys.argv[1:]
    url = next((arg for arg in args if not arg.startswith("--")), DEFAULT_URL)
    mode = "camoufox" if "--camoufox" in args else "curl"

    if mode == "curl":
        for impersonate in ["chrome", "chrome124", "safari", "firefox"]:
            print("=" * 80)
            try:
                result = probe_curl_cffi(url, impersonate=impersonate)
            except Exception as exc:
                print(type(exc).__name__, exc)
                continue
            if result.ok:
                print("success with:", impersonate)
                return 0
        print("curl_cffi did not clear the challenge; try `--camoufox`")
        return 1

    result = solve_with_camoufox(
        url,
        headless="--headless" in args,
        humanize=parse_humanize(args),
        disable_coop="--disable-coop" in args,
        auto_click="--auto-click" in args,
        success_predicate=eh_forum_success,
    )
    print("title:", result.title)
    print("final url:", result.final_url)
    print("solved:", result.solved)
    print("challenge markers:", result.challenge_detected)
    print("cookies:", result.cookie_names)
    print("prefix:", result.html_prefix)
    if not result.solved:
        return 1
    return 0 if verify_cookies_with_curl(url, result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
