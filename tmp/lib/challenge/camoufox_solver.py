from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


# 各站点的成功信号不同，所以 predicate 必须允许注入。
# 例如 EH 论坛可以用 title/cf_clearance 判断，API 页面可能没有 title。
ChallengePredicate = Callable[[str], bool]
SuccessPredicate = Callable[[str, str, list[dict[str, Any]]], bool]


@dataclass(slots=True)
class CamoufoxSolveResult:
    # 注意：cookies 含真实敏感值。probe 只能打印 cookie_names，不能打印原始 cookie value。
    url: str
    final_url: str
    title: str
    user_agent: str
    cookies: list[dict[str, Any]]
    html_prefix: str
    solved: bool
    challenge_detected: bool

    @property
    def cookie_names(self) -> list[str]:
        return [str(cookie.get("name")) for cookie in self.cookies if cookie.get("name")]


def is_common_challenge_html(text: str) -> bool:
    lower = text.lower()
    markers = [
        "just a moment",
        "checking your browser",
        "ddos-guard",
        "cloudflare",
        "/cdn-cgi/challenge-platform/",
        "cf-browser-verification",
        "cf-challenge",
        "challenges.cloudflare.com",
    ]
    return any(marker in lower for marker in markers)


def html_prefix(text: str, limit: int = 500) -> str:
    return " ".join(text[:limit].split())


def solve_with_camoufox(
    url: str,
    *,
    headless: bool = True,
    humanize: bool | float = True,
    disable_coop: bool = True,
    auto_click: bool = True,
    timeout_ms: int = 120_000,
    challenge_predicate: ChallengePredicate = is_common_challenge_html,
    success_predicate: SuccessPredicate | None = None,
) -> CamoufoxSolveResult:
    '''
    用 Camoufox 打开目标 URL，并返回可复用的浏览器状态。

    这个函数只负责引导通过 Cloudflare/浏览器质询，不是常规数据请求层。
    拿到 cookies 和 user-agent 后，应优先缓存起来，再用 curl_cffi 进行后续轻量请求。
    '''
    try:
        from camoufox.sync_api import Camoufox
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "camoufox is not installed. Install it first:\n"
            "  pip install camoufox\n"
            "  python -m camoufox fetch"
        ) from exc

    with Camoufox(headless=headless, humanize=humanize, disable_coop=disable_coop) as browser:
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

        wait_result = _wait_for_solved(
            page,
            context,
            url,
            timeout_ms=timeout_ms,
            auto_click=auto_click,
            challenge_predicate=challenge_predicate,
            success_predicate=success_predicate,
        )

        title, html = _safe_title_content(page)
        cookies = context.cookies(url)
        user_agent = page.evaluate("navigator.userAgent")
        final_url = page.url
        challenge_detected = challenge_predicate(html)
        solved = wait_result or (success_predicate(title, html, cookies) if success_predicate else not challenge_detected)

        return CamoufoxSolveResult(
            url=url,
            final_url=final_url,
            title=title,
            user_agent=user_agent,
            cookies=cookies,
            html_prefix=html_prefix(html),
            solved=bool(solved),
            challenge_detected=challenge_detected,
        )


def _wait_for_solved(
    page: Any,
    context: Any,
    url: str,
    *,
    timeout_ms: int,
    auto_click: bool,
    challenge_predicate: ChallengePredicate,
    success_predicate: SuccessPredicate | None,
) -> bool:
    '''
    等待 challenge 结束，并在需要时尝试自动点击质询控件。

    Turnstile/Managed Challenge 需要几秒钟挂载控件。EH 论坛测试中，太早点击只会移动鼠标，
    不会真正命中控件，所以这里会先延迟，再开始自动点击。
    '''
    deadline = time.monotonic() + timeout_ms / 1000
    started = time.monotonic()
    last_title = ""
    auto_click_attempts = 0

    while time.monotonic() < deadline:
        title, html = _safe_title_content(page)
        cookies = context.cookies(url)

        if title != last_title:
            print("page title:", title)
            last_title = title

        if success_predicate and success_predicate(title, html, cookies):
            print("success predicate reached")
            return True

        if not challenge_predicate(html):
            print("challenge markers cleared")
            return True

        if auto_click:
            elapsed = time.monotonic() - started
            if elapsed < 6:
                print("auto-click: waiting for widget mount", int(6 - elapsed), "s")
            else:
                auto_click_attempts += 1
                _try_auto_click_challenge(page, attempt=auto_click_attempts)

        print("waiting for challenge to clear...")
        try:
            page.wait_for_timeout(3000)
        except Exception as exc:
            print("page wait interrupted:", type(exc).__name__, exc)
            return False

    print("challenge wait timed out; continuing with current browser state")
    return False


def _safe_title_content(page: Any) -> tuple[str, str]:
    '''
    安全读取页面 title 和 HTML。

    Cloudflare 页面在质询期间会频繁变更和跳转。Playwright 偶发读取失败通常只是导航噪声，
    不应该直接视为解盾失败。
    '''
    try:
        return page.title(), page.content()
    except Exception as exc:
        print("page changing:", type(exc).__name__, exc)
        try:
            page.wait_for_timeout(1000)
            return page.title(), page.content()
        except Exception:
            return "", ""


def _try_auto_click_challenge(page: Any, *, attempt: int) -> bool:
    '''
    尝试自动点击 Cloudflare/Turnstile 质询区域。

    不依赖 Turnstile 内部 DOM。该 DOM 是跨源 iframe，且在 Playwright/Camoufox 下不稳定。
    当前 EH 论坛测试中最可靠的方法是：找到外层 challenge frame 的 bounding box，并点击中心。
    '''
    print("auto-click attempt:", attempt)
    clicked = False
    try:
        print("auto-click: frames", [frame.url for frame in page.frames])
    except Exception as exc:
        print("auto-click frame list failed:", type(exc).__name__, exc)

    for frame in page.frames:
        if "challenges.cloudflare.com" not in frame.url and "turnstile" not in frame.url.lower():
            continue

        try:
            element = frame.frame_element()
            box = element.bounding_box()
            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                print("auto-click: frame_element center", int(x), int(y), "box", box)
                _human_mouse_click(page, x, y)
                clicked = True
                break
        except Exception as exc:
            print("auto-click frame_element failed:", type(exc).__name__, exc)

    if not clicked:
        print("auto-click: challenge frame not clickable yet")
    return clicked


def _human_mouse_click(page: Any, x: float, y: float) -> None:
    '''以较自然的路径移动并点击目标坐标。'''
    page.mouse.move(x - 90, y - 35)
    page.mouse.move(x - 55, y - 12)
    page.mouse.move(x - 20, y + 8)
    page.mouse.move(x, y)
    page.mouse.click(x, y)
