# FletViewer Agent Notes

## 项目目标

FletViewer 是跨平台 Anime Provider 浏览/下载工具，目标平台为 Windows / Linux / Android / Web / Server；核心能力包括 provider 抓取、登录/API/Cookie、标签检索、图片缓存、批量下载、本地画廊管理。

参考方向：Pix-Ez Viewer、Imgur Grabber、EHViewer、Venera、Mihon/Tachiyomi、Emby。

## 协作风格

- 默认 TLDR：先结论、改了什么、还差什么；除非用户要求，不写长背景。
- Markdown 单行尽量承载完整意思，避免把短句拆成很多行导致屏幕右侧空白；列表项可以稍长。
- TODO 文档只保留“决策、约束、下一步”；长期规则写进 `AGENTS.md`，实验流水账写进 `tmp/` 或 commit message。
- 不要随意重构。优先小改、可验证、低风险；不要为了“统一”抹掉 provider 差异。

## Shell / 环境

- Windows 默认 `bash` 会被 WSL2 劫持且当前 WSL 不可用；需要类 Unix shell 时用 `sh -c "..."`。
- 中文/日文输出用 UTF-8：`sh -c "export PYTHONIOENCODING=utf-8 LANG=zh_CN.UTF-8; python script.py"`。
- 不要在工具里启动 Flet Web：`python app/main.py --web` 会阻塞；Web 模式由用户手动测试。
- Flet Web 异常缓存可能来自 `~/.flet`；必要时用户手动删：`Remove-Item -LiteralPath "$env:USERPROFILE\.flet" -Recurse -Force`。

## Flet API 坑

- 不用 `ft.alignment.center`；居中写 `ft.Alignment(0, 0)`。
- `ft.Image` 必须有有效 `src`；占位统一用 `app.controls.async_image.image_placeholder()` 或 `Container + Icon`，不要 `ft.Image(src=None)`，不要 1x1 base64 空图。
- 图片展示统一走 `app.controls.async_image.image_src_for_page(page, data, mime)`，不要直接把 bytes 或本地文件路径塞给 `ft.Image(src=...)`；Web 端读不了服务器本地路径。
- 当前 `ft.Tab` 用 `ft.Tab(label=...)`；内容放 `ft.TabBarView`，不要传 `text=` / `tab_content=`。
- Dialog 用 `dialog.open = True; page.show_dialog(dialog); page.pop_dialog()`，不要用 `page.open()` / `page.close()`。
- `ft.TextField` 不支持 `suffix_text=`；需要单位后缀时用 `ft.Row([field, ft.Text("px")])`。

## UI 线程 / 更新

- 事件 handler 之外只要修改 Flet 控件属性或控件树，必须触发 `page.update()`；项目辅助为 `from app.ui_update import request_update; request_update(page)`。
- 会修改 UI 的后台任务用 `page.run_thread(worker)`，不要用裸 `threading.Thread(...)` 直接改控件。
- 不要把 `page.schedule_update()` 当后台完成后的主 flush；已实测会出现控件树已变但前端不刷新的问题。
- 纯 IO 后台服务可以保留线程池，但不能直接改 UI；UI 通过轮询状态或 `page.run_thread()` worker 刷新。

## 图像与缓存

- 不要恢复本地 HTTP 图片代理，不要恢复 `/thumb?url=...`；当前链路是 `UI -> async_image/image_viewer -> ImageFetcherService -> JSON index -> HatH-style disk cache -> bytes -> ft.Image`。
- `app/image_cache.py` 是 provider-agnostic；index 为 `url -> filename`，文件位于 `Data/ImageCache/files/<hash[0:2]>/<hash[2:4]>/<filename>`。
- 文件名当前为 `sha256(normalized_url) + ext`；index 指向文件不存在时按 stale repair 删除映射后重拉。
- EH sprite crop URL 形如 `https://...webp@x=1800-2000&y=0-282`，`@x/y` 是本地裁剪指令，不是真实远端 URL；`app/image_fetcher.py` 先拉原 sprite，再用 Pillow 裁剪并按完整 crop URL 缓存。
- 设置页“是否加载图像”关闭后，`async_image()` 和图像查看器不得读缓存、不得请求远端，只显示占位；该开关只影响图片资源，不影响列表 HTML/JSON 请求。

## 浏览器会话 / 网络

- EH 请求尽量复用 `app/browser_session.py` 的 `browser_session` 单例，共享 `requests.Session`、cookie jar、UA、Accept、Accept-Language 和连接。
- 页面里不要随意新建 `EHentaiClient()`；用 `browser_session.get_eh_client(require_login=False)` 或 `browser_session.get_eh_client(require_login=True)`。
- 登录必需页面用 `require_login=True`，公开页面用 `False`；登录验证有 TTL 缓存，保存 EH 凭据后要让相关 view cache 失效。
- 图片 fetch 也走 `browser_session.get(...)`，不要手拼 Cookie header。

## 页面 / 视图

- `app/main.py` 对导航页做 view cache；切页复用控件树，刷新由页面自己的“刷新”按钮负责。
- 保存设置若影响已有页面渲染，必须调用 `page.fletviewer_invalidate_views(...)` 清理缓存；卡片/JSON 列表设置在 view 创建时读取。
- 画廊列表统一入口：`app/views/gallery_debug.py:create_gallery_view(...)`；主页、热门、排行榜、收藏、订阅、搜索都应遵循同一卡片/JSON 设置。
- 详情页：`app/views/gallery_detail.py`；图像查看器：`app/views/image_viewer.py`。
- 图像查看器 provider-agnostic：输入 `ImageViewerItem(url, title, detail)`；EH 通过 `resolve_image_url(item, index)` 解析原图，Booru 直接传图片 URL。
- 查看器模式：`paged` / `vertical`；默认值写在 `AppConfig.json` 的 `image_viewer_mode`。
- 垂直模式必须窗口化加载，不得一次性创建整本真实图片；窗口外恢复 `Container + Icon` 以释放 UI 对 bytes 的引用。
- EH `ThumbnailsResult` 新代码优先用 `items`，保留旧字段 `thumbnails` / `urls` 兼容调试。

## 下载系统

- EH 批量下载默认只支持 Archive Download；逐页 fetch 只可用于预览/少量图片，不作为批量下载方案。
- `DownloadManager` 负责大文件任务、状态、断点续传、进度、重试/取消、完成事件；`LocalGalleryManager` 负责消费完成任务、创建本地画廊、移动 ZIP、写 metadata、提取封面、扫描本地画廊。
- EH Archive 保留远端 ZIP，不解压、不重命名；同目录写 `gallery.json` 和 `thumb.<ext>`；目录名为 `[<GID>][<TOKEN>] <SanitizedGalleryTitle>`，按 Windows 最严格规则清洗并限制长度。
- 目录约定：下载中 `FletViewer/Downloads/Downloading/<task_id>/`，本地归档 `FletViewer/Downloads/EHArchieve/[gid][token] title/`，任务索引 `FletViewer/Data/Downloads/tasks.json`。
- 下载网络必须复用 `browser_session` 的 cookie、UA、Referer 和连接状态；不要为 EH 下载单独新建裸 `requests.Session`。
- 断点续传用普通 HTTP Range，不做多线程分片；EH Archive 有 GP/IP/URL 时效限制，默认并发 1，最多 2。
- 进度持久化要节流，建议每 1MB 或每 2 秒写一次；UI 轮询任务状态刷新。
- 启动恢复：`running` 任务改为 `failed`；`completed` 但未 `consumed` 的任务可重新通知 `LocalGalleryManager`。
- Archive URL 通常 86400 秒有效且限制 IP；`task.json` / `gallery.json` 必须记录获取时间、有效期、最大 IP 数；URL 过期第一版标 failed，不自动重新消耗 GP。

## Provider 设计

- 可以共享工程层抽象，但不要强行统一协议层；Danbooru、Gelbooru、Moebooru、EH、Pixiv 的分页、认证、tag、文件 URL、rate limit、Cloudflare 状态都可能不同。
- 共享数据模型只能是最小公共字段，并允许 provider-specific metadata；不要丢弃 tags、rating、score、source、md5、page_url、archive 等关键字段。
- Booru 协议族：`DanbooruClient` 走现代 JSON API；`GelbooruClient` 走 gelbooru.com JSON DAPI；`GelbooruAlikeClient` / `SafebooruClient` / `Rule34Client` 走旧 Gelbooru-style XML DAPI；`MoebooruClient` 走 Moebooru XML API。
- Booru adapter 可输出 `BooruPost`、`ImageVariant`、`BooruSearchResult`、`TagSuggestion`，但不能抹平 provider-specific 字段。

## Challenge Backend

- Provider 不关心 challenge 如何解决；目标链路：`provider -> browser_session/transport -> challenge detector -> challenge backend -> cookie import -> retry once`。
- Challenge 产物是 `domain cookies + user-agent + target origin`，不是浏览器本身；解完后常规 provider 继续走轻量 HTTP session/transport。
- 平台策略：Android 用系统 WebView 让用户完成 challenge 并导出 cookies/UA；PC 桌面可用 Camoufox；server/web 优先手动 cookie import，只有服务器能跑浏览器且目标会话属于服务器 IP 时才考虑 Camoufox headless。
- Danbooru 实验结论：vanilla `requests` 访问 `/posts.json` 会被 CF 403；`curl_cffi` Chrome impersonation 可直接返回 JSON；Camoufox cookie + UA 交给 vanilla `requests` 仍失败，问题更像 transport fingerprint。
- EH forum 实验结论：`curl_cffi` 单独不够；Camoufox 过交互式 CF 后拿到 `cf_clearance` / `ipb_session_id`，再交给 `curl_cffi` 可复用。
- EH forum 自动点击经验：不要依赖 Turnstile 内部 checkbox DOM；当前可点击 `challenges.cloudflare.com` frame 外层 bounding box 中心，但必须保留 fallback。
- Browser profile cache 必须按站点/profile 隔离；EH 主站、EH forum、Danbooru、Gelbooru、Pixiv 分开缓存 cookies/UA/challenge 状态；日志和文档只允许打印 cookie 名称。

## 依赖准入

- 默认优先纯 Python 依赖；引入 native/binary/Rust/C 扩展前，必须确认 Windows、Linux、Android 的 wheel 或源码构建路径。
- 正式核心依赖不要轻易加入 Android 不可构建包；`curl_cffi`、`camoufox`、`playwright` 只能用于隔离的 PC/server challenge backend 或 `tmp/` 实验，不能进 Android 核心。
- `lxml` 优先替换：HTML 用 `BeautifulSoup(..., "html.parser")`，XML 用 `xml.etree.ElementTree`；替换后跑 EH 搜索、详情、缩略图、归档 smoke test。
- `Pillow` 用于 EH sprite crop 和封面处理，是 Android build 风险；先实测，失败时 Android 降级/禁用相关功能，不要引入更大的 native 图像依赖。
- `flet-web`、`fastapi`、`uvicorn` 不应默认进入 Android target；若带来 `pydantic_core` 等 native/Rust 依赖，拆到 optional dependencies 或 server-only 入口。
- 平台相关能力通过小接口注入，例如 challenge solver、文件选择器、WebView、系统下载目录；核心 provider、缓存、下载、数据模型尽量纯 Python。

## tmp 实验区

- `tmp/` 是隔离实验区，不是正式应用；可放 Camoufox、curl_cffi、Playwright、notebook 等实验依赖。
- `app/` 或正式 provider 不能直接 import `tmp/` 代码；迁移前必须检查 Android 依赖、敏感信息、协议边界、现有 `browser_session` / `image_cache` / `download_manager` 职责边界。
- `tmp/.cache/` 存放真实 cookies/profile，必须 gitignore，不能提交。
- Flet 打包必须排除 `tmp/`、`.cache/`、`*.ipynb` 和实验产物。

## Android 构建

- Flet 0.85.3 配套 Flutter 3.41.7；不要用 scoop/winget 装 Flutter，版本不匹配或源不存在。
- 不要用 Puro；Flet CLI 调用的 `flutter` 子进程不会自动拿到 Puro 环境。
- 推荐让 `flet build apk` 自动下载配套 Flutter 到 `C:\Users\<用户名>\flutter\3.41.7\`；PATH 上不要有其他 Flutter 干扰。
- Android SDK 需手动安装；推荐 SDK 36 + BuildTools 36.0.0，并执行 `flutter doctor --android-licenses` 接受许可。
- Windows 必须开启开发者模式，否则插件构建会卡在 symlink support。
- `ANDROID_HOME` / `ANDROID_SDK_ROOT` 必须指向真实 SDK 路径，Android Studio 默认通常是 `%LOCALAPPDATA%\Android\Sdk`。
- APK 产物在 `build/apk/app-release.apk`；默认 debug key 只适合本地测试，上架需配置 `[tool.flet.android.signing]`。
- 根目录 `main.py` 是 thin shim，转发到 `app/main.py`；改入口逻辑只改 `app/main.py`，不要动 shim。
- `pyproject.toml` 待修正：`requires-python >=3.10`；`[tool.flet.app].exclude` 必须包含 `tmp`、`.cache`、`*.ipynb`，并继续排除 `FletViewer`、`build`、`.git` 等产物。

## 日志

- 异步 worker 捕获异常时用 `app.debug_log.log_exception(...)`，不要只吞异常或只显示 UI 文本；终端需要 traceback。
- 网络和耗时路径用 `Timer(...)` / `log_debug(...)`；不要记录 cookie value、token、完整敏感 header。
