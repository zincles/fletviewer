# tmp 实验区

这个目录是临时实验区，刻意和正式应用代码隔离。

办公室规则：
- 不碰 `app/`、`lib/provider/ehgrabber.py`、下载系统、正式 UI。
- 这里只做 provider、Cloudflare challenge、浏览器缓存等实验。
- 有用的代码回家后再检查未提交变更，并整理进正式项目。

## 目录结构

```text
tmp/
├── docs/       实验记录和结论。
├── lib/        实验性 Python 库。
└── probes/     可直接运行的验证脚本和 notebook。
```

## Challenge Solver

可复用的 Camoufox challenge solver 位于：

```text
tmp/lib/challenge/
├── __init__.py
├── browser_cache.py
└── camoufox_solver.py
```

导入方式：

```python
from tmp.lib.challenge import browser_cache, solve_with_camoufox
```

`solve_with_camoufox()` 会返回：
- cookies
- user-agent
- final URL
- title
- 简短 HTML prefix
- 是否解决 challenge
- 最终页面是否仍命中 challenge markers

probe 只打印 cookie 名称，不打印 cookie 值。

浏览器 profile 缓存位置：

```text
tmp/.cache/browser_profiles/
```

缓存按目标站点/profile 分离，例如：

```text
eh-forum
danbooru
```

这样后续 EH 主站、EH 论坛、Booru、Pixiv、Gelbooru 等站点可以分别保存自己的 cookies、UA 和 challenge 状态。

## Booru 实验库

当前 Booru 抽象位于：

```text
tmp/lib/booru/
├── data/       共享数据结构。
├── providers/  不同协议/站点的 provider 实现。
├── factory.py
└── transport.py
```

示例：

```python
from tmp.lib.booru import create_booru_client, create_browser_like_session

session = create_browser_like_session(impersonate="chrome")
client = create_booru_client("danbooru", session=session)
result = client.search_posts("cat rating:general", limit=3)

for post in result.posts:
    print(post.id, post.thumbnail_url, post.original_url)
```

当前 provider：
- `DanbooruClient`
- `GelbooruClient`
- `GelbooruAlikeClient`
- `SafebooruClient`
- `Rule34Client`
- `MoebooruClient`

## 常用 Probe

```powershell
python tmp/probes/cached_access_probe.py
python tmp/probes/challenge_cache_probe.py eh-forum
python tmp/probes/challenge_cache_probe.py danbooru
python tmp/probes/curl_cffi_danbooru_probe.py
python tmp/probes/camoufox_danbooru_probe.py
python tmp/probes/camoufox_cookie_probe.py eh-forum
python tmp/probes/camoufox_cookie_probe.py danbooru
python tmp/probes/eh_forum_challenge_probe.py
python tmp/probes/eh_forum_challenge_probe.py --camoufox --headless --humanize --disable-coop --auto-click
```

Notebook：

```text
tmp/probes/danbooru_probe.ipynb
```

## 详细记录

Challenge、transport、缓存实验的详细结论在：

```text
tmp/docs/challenge_backend_notes.md
```

## 今日工作总结

今天在 `tmp/` 下建立了一套隔离实验栈：

- 参考 LoliSnatcher 的 Booru handler 思路，做了 Python 版 `tmp/lib/booru/`。
- 将 Booru 的数据结构和 provider 实现拆开，分别放到 `data/` 和 `providers/`。
- 增加了 Danbooru、Gelbooru、Gelbooru-alike/Safebooru/Rule34、Moebooru 的实验 client。
- 增加了 `curl_cffi` browser-like transport helper。
- 验证 Danbooru 会拦截普通 `requests`，但 `curl_cffi impersonate="chrome"` 可以直接访问 API。
- 用 Camoufox 测试 Danbooru，确认浏览器环境能访问，但把 cookie + UA 转给 vanilla `requests` 不能解决 Danbooru。
- 测试 EH 论坛 Cloudflare challenge，确认 `curl_cffi` 单独不够。
- 验证 Camoufox 可以解决 EH 论坛 challenge，并拿到 `cf_clearance` / `ipb_session_id`。
- 找到了可靠自动点击方式：点击外层 `challenges.cloudflare.com` frame 的 bounding box 中心，而不是访问内部 checkbox DOM。
- 验证 Camoufox headless + humanize + auto-click 可以在当前环境自动解决 EH 论坛 challenge。
- 抽象出 `solve_with_camoufox()`，放到 `tmp/lib/challenge/`。
- 增加 `browser_cache` 单例，用 profile 维度缓存 cookies + user-agent + metadata。
- 分别缓存并复用了 `eh-forum` 和 `danbooru` 两个 profile。
- 增加 `cached_access_probe.py`，验证不启动 Camoufox，仅靠缓存 cookies + UA + `curl_cffi` 就能访问 EH 论坛和 Danbooru。

当前实用模型：

```text
普通 API 访问：
  curl_cffi transport

交互式 Cloudflare challenge：
  Camoufox headless/visible
  -> cookies + user-agent
  -> browser_cache
  -> curl_cffi 复用

未来移动端：
  WebView
  -> cookies + user-agent
  -> 同一套 cache/session 模型
```

当前重要结论：
- Booru 系可以在工程层统一，但协议层必须严格区分。
- Danbooru 这种 API 场景优先用 `curl_cffi`，不需要 Camoufox 常驻。
- EH 论坛这类交互式 CF 场景需要 Camoufox/WebView 先过盾，再把 cookies 交给轻量 transport。
- 服务端部署可以先尝试 Camoufox headless 自动解盾；失败时未来再考虑 noVNC/远程接管。
