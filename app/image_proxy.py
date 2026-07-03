"""E-Hentai 图片透明代理。

提供 /thumb?url=<原URL> 端点，规避 Web 模式下的 CORS 问题。
对上层完全透明：调用方只需 public_src(comic.cover) 即可拿到可用的图片 src。

Web 模式：复用已有的 FastAPI 实例，加一个 @app.get("/thumb") 路由。
桌面模式：起一个 ThreadingHTTPServer (127.0.0.1 随机端口, daemon thread)。

未来加缓存层时，只需在 _handle_thumb 内部加 cache.get/fetch 判断即可，
上层调用方 (home.py 等) 无需任何改动。
"""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlparse, parse_qs

import requests

from app.storage import load_eh_config

# 桌面模式本地服务端口（start_cache_server 后填充）
_PORT: int | None = None

# 共用的请求头基础
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _build_headers() -> dict:
    """构造发往 EH 的请求头：Cookie + Referer + UA。

    从 FletViewer/Config/EHArchieve.json 读凭据。未登录则只发 UA+Referer。
    """
    cfg = load_eh_config()
    cookies = []
    for k in ("ipb_member_id", "ipb_pass_hash", "igneous", "star"):
        v = cfg.get(k, "")
        if v:
            cookies.append(f"{k}={v}")
    headers = {
        "User-Agent": _UA,
        "Referer": "https://e-hentai.org/",
    }
    if cookies:
        headers["Cookie"] = "; ".join(cookies)
    return headers


def _handle_thumb(url: str) -> tuple[bytes, str]:
    """核心：转发一张图片，返回 (bytes, content_type)。

    当前为纯转发，无缓存。未来可在此函数内部加 cache.get/fetch。
    失败时抛异常，由调用方（FastAPI 路由 / http.server handler）转 502。
    """
    headers = _build_headers()
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    ct = resp.headers.get("Content-Type", "image/jpeg")
    return resp.content, ct


def public_src(url: str) -> str:
    """把原始 EH 图片 URL 转成对前端透明的同源 src。

    Web 模式：/thumb?url=<quote(url)>  （同源相对路径，规避 CORS）
    桌面模式：http://127.0.0.1:<_PORT>/thumb?url=<quote(url)>
    """
    if not url:
        return ""
    q = quote(url, safe="")
    if os.environ.get("FLETVIEWER_WEB") == "1":
        return f"/thumb?url={q}"
    if _PORT is None:
        # 桌面模式未启动服务时回退到原 URL（桌面 Flutter 无 CORS）
        return url
    return f"http://127.0.0.1:{_PORT}/thumb?url={q}"


# ---------------------------------------------------------------------------
# 桌面模式本地 HTTP 服务
# ---------------------------------------------------------------------------


class _ThumbHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/thumb":
            self.send_response(404)
            self.end_headers()
            return
        qs = parse_qs(parsed.query)
        url_list = qs.get("url")
        if not url_list:
            self.send_response(400)
            self.end_headers()
            return
        url = url_list[0]
        try:
            data, ct = _handle_thumb(url)
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as ex:
            print(f"[proxy error] {ex}")
            self.send_response(502)
            self.end_headers()

    def log_message(self, fmt, *args):
        # 静默默认访问日志，保留上面手打的 [proxy error]
        pass


def start_cache_server() -> int:
    """桌面模式：启动本地 /thumb 服务，返回端口。

    仅在桌面模式调用。Web 模式复用 FastAPI 实例，不需要这个。
    """
    global _PORT
    if _PORT is not None:
        return _PORT
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _ThumbHandler)
    _PORT = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    print(f"[proxy] 本地图片代理服务已启动: http://127.0.0.1:{_PORT}/thumb")
    return _PORT
