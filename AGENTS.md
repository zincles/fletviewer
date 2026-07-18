# FletViewer Agent Notes

## 项目目标

FletViewer 是跨平台 Anime Provider 浏览/下载工具，目标平台为 Windows / Linux / Android / Web / Server；核心能力包括 provider 抓取、登录/API/Cookie、标签检索、图片缓存、批量下载、本地画廊管理。

当前产品使用 Python + Flet，Flet 同时承担桌面、Android 和 Web UI，Web/NAS 是一等部署目标。项目不再推进 Flutter + Serious Python bridge；Flet 是当前前端，但不是未来不可替换的架构约束。

未来唯一业务核心是纯 Rust `fvcore`：同一 Cargo crate 同时提供可嵌入 library 和可独立运行的 executable，并全面替代当前 Python `core/`。Python 实现仅作为重写期间的只读行为和 fixture 参考，不打包为 Python `fvcore`；迁移决策、并发模型和顺序以根目录 `FVCORE.md` 为准。

参考方向：Pix-Ez Viewer、Imgur Grabber、EHViewer、Venera、Mihon/Tachiyomi、Emby。

## 协作风格

- 默认 TLDR：先结论、改了什么、还差什么；除非用户要求，不写长背景。
- Markdown 单行尽量承载完整意思，避免把短句拆成很多行导致屏幕右侧空白；列表项可以稍长。
- TODO 文档只保留“决策、约束、下一步”；长期规则写进 `AGENTS.md`，实验流水账写进 `tmp/` 或 commit message。
- 不要随意重构。优先小改、可验证、低风险；不要为了“统一”抹掉 provider 差异。

## 禁止使用子代理

- 本规则适用于本仓库及其所有子目录中的全部任务。
- 禁止创建、调用、委派或等待任何 subagent（子代理）。
- 禁止使用 `spawn_agent`、`followup_task`、`send_message`、`wait_agent`、`interrupt_agent`、`list_agents`，以及其他任何多代理协作功能。
- 所有分析、检索、文件修改、测试和答复都必须由当前主代理独立完成。
- 即使子代理可能提升速度或质量，也不得启用；如果单一代理确实无法继续，应直接向用户说明限制。

## 架构边界

- `core/` 是与 UI 框架无关的业务核心；Provider、网络协议、缓存、数据库、下载、图片获取等能力优先放入 `core/`。
- `app/` 是 Flet 前端和应用装配层；负责页面、控件、主题、导航、展示状态，以及把配置、路径、日志和平台能力注入 `core/` 服务。
- 依赖方向固定为 `app -> core`；`core/` 不得 import `app`、`flet` 或其他具体前端，也不得通过 fallback import 绕过该边界。
- `core/` 的公开输入输出使用普通 Python 类型、dataclass、枚举、dict、bytes 和 Path；不得返回或持有 Flet 控件。
- 平台相关能力由 `core/` 定义小接口/回调并由 `app/` 注入；不要让核心业务直接调用 Toast、Dialog、页面导航或 UI 更新。

## fvcore

- `fvcore/` 必须保持纯 Rust，不嵌入或调用 Python、Dart、JavaScript 等语言的业务实现。
- `fvcore` 长期保持一个 Cargo crate；同一 package 的 library 实现完整核心方法，executable 负责读取配置和运行同一 Runtime，不预设 provider/server/CLI/C ABI/前端子 crate。
- `fvcore` 可独立运行，也可被第三方 Rust 程序嵌入；对外统一使用 command、不可变 snapshot、带 revision 的 event 和二进制 resource 语义。
- 当前 Python `core/` 是 Rust 迁移的 executable specification。先固定 fixture、输入输出、错误和状态，再实现 Rust；不要逐行翻译。
- 默认禁止 `unsafe`；本轮不为假设中的 C ABI、JNI 或平台 binding 预留 unsafe。未来确有不可替代需求时先更新 `FVCORE.md` 并记录安全不变量。
- 不允许 Python 与 Rust 实现同时写同一份 SQLite、Cache、Downloads 或本地画廊；对比测试使用只读 fixture或隔离临时目录。
- Rust 并发设计必须异步、可取消、有 deadline、有界队列和不可变 task snapshot；不得把现有 Python 线程/锁结构机械翻译过去。
- JSON 只承载控制数据；图片和 Archive 等大资源使用 bytes/stream/resource handle，不以 base64 作为正式跨组件接口。
- 最终范围覆盖 Python Core 的全部正式能力，包括 Provider、网络、图像、缓存、下载、ZIP/CBZ、本地画廊、历史和存储；迁移按纵向能力分批验收，不把早期批次范围视为永久裁剪。
- 标准 `fvcore` executable 必须始终编译 HTTP 控制面；是否监听只由 args/配置决定，不通过 Cargo feature 形成缺少控制面的正式内核变体。
- Runtime 是配置、Provider profile/session、operation、图像缓存和下载任务的唯一 owner；通常一进程一个 Runtime，外部使用可克隆 handle，不使用 Rust `static` 全局可变单例或 Core-wide 大锁。
- 同一 Provider profile 共用连接池、认证、代理、限流和 session generation；EH 搜索/详情/图片/Archive 必须复用同一逻辑会话，配置变化创建新 generation，旧请求自然持有旧 generation 至完成。
- 图片链路按 memory -> disk -> network；网络未命中优先 fetch 到有界内存、发布共享不可变 bytes，再可选异步落盘。所有内存、在途 bytes、队列和并发必须有硬上限。
- 图像磁盘缓存使用真实内容的 128-bit MD5，即 32 位小写十六进制文件名加规范化后缀，并按前四位两级分片；Booru original 的 Provider MD5 用于 fetch 前去重及 fetch 后校验。
- `fvcore` 可以引入支持 Windows、Linux、Android 和 server 的成熟 Rust 依赖；WASM 不在本轮目标。依赖引入前检查目标构建、feature、维护状态、许可证和安全公告。

## Flet 与 Flutter 扩展

- `app/` 是当前正式产品前端，不是等待独立 Flutter UI 替换的兼容层；已完成的 Python Core/Facade 解耦用于控制业务边界、测试，并为纯 Rust `fvcore` 提供迁移基线。
- 不为独立 Flutter UI 创建 Serious Python bridge、JSON-RPC/FFI 通道或第二套 Dart 业务模型；未来任何前端/控制传输只能包装 `fvcore` 的公开方法，不复制业务。
- 优先使用 Flet 内建跨平台能力。只有 Flet API 经实测无法可靠满足具体平台需求时，才增加小型 Flutter extension。
- Flutter extension 必须提供 Python wrapper，以窄接口接入 `app/`；`core/` 不得 import extension、Flutter/Dart 包或 Flet 控件。
- 每个 extension 在引入前必须确认 Windows、Linux、Android 和 Web 的支持矩阵。Web 无法使用时必须有 fallback、明确禁用状态或服务器侧替代，不能阻断 Web 应用启动。
- Dart 端只实现平台机制，不复制 Provider、网络会话、Cookie、缓存、数据库、下载任务或画廊业务。

## Web / NAS

- Web/NAS 是正式运行模式，不是只用于调试的附属目标；桌面、Android 和 Web 应复用同一 Core/Facade 与主要页面结构。
- Web 模式的 Data、Cache、Downloads、Temp、Cookie 和下载任务属于服务器。浏览器本地文件只能通过上传、下载或文件选择能力交换，不得伪装为服务器 `Path`。
- 当前优先支持可信环境中的单用户或共享实例。在实现用户隔离前，不得假定 Cookie、历史、任务和本地画廊按浏览器用户隔离。
- 暴露到不可信网络前必须考虑反向代理 TLS、认证、访问控制、上传限制和敏感日志；应用文档不得暗示当前实例天然适合公网多用户部署。

## Shell / 环境

- Windows 默认 `bash` 会被 WSL2 劫持且当前 WSL 不可用；需要类 Unix shell 时用 `sh -c "..."`。
- 中文/日文输出用 UTF-8：`sh -c "export PYTHONIOENCODING=utf-8 LANG=zh_CN.UTF-8; python script.py"`。
- 不要在工具里启动 Flet Web：`flet run --web --recursive` 会阻塞；Web 模式由用户手动测试。
- Flet Web 异常缓存可能来自 `~/.flet`；必要时用户手动删：`Remove-Item -LiteralPath "$env:USERPROFILE\.flet" -Recurse -Force`。

## Flet API 坑

- 查询 Flet 控件、方法、属性、类型、CLI 或平台行为时，优先检索 `docs/index.md` 的项目索引和 `docs/flet/` 的本地官方文档副本，不要凭记忆猜测 API；项目锁定 `flet==0.85.3`，采用副本中较新 API 前必须确认版本并实测。
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
- `app/image_cache.py` 是 provider-agnostic；index 为 `url -> filename`，文件位于 Cache 域的 `files/<hash[0:2]>/<hash[2:4]>/<filename>`。
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
- 子页面导航使用“入栈/出栈”语义封装，例如 `push_view(...)` / `pop_view()`；业务页面不要散落直接 `page.views.append(...)` / `page.views.pop()`。
- 底层实现必须保持 `page.route`、浏览器/系统 history 和 `page.views` 同步；优先在统一 route/view helper 或 `page.on_route_change` 中维护 View 栈。
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

## Challenge / 浏览器实验

- Rust `fvcore` 当前不实现 challenge backend、Camoufox、Playwright、Turnstile、浏览器 profile、Cloudflare bypass 或 transport fingerprint 伪装。
- Danbooru、Gelbooru 和其他 Booru 只使用公开 API 与正式 API 凭据；401/403/429、HTML 非预期响应和访问阻断返回稳定错误，不尝试绕过。
- Pixiv 使用用户导入 Cookie 和现有 Web AJAX；EH 使用用户提供 Cookie 和普通共享会话。遇到必须交互的 challenge 时明确失败，不启动浏览器。
- `tmp/` 既有 Camoufox/curl_cffi 实验仅作为历史研究保留，暂停扩展，不得进入 Rust workspace 或正式 Core 依赖。

## 依赖准入

- 默认优先纯 Python 依赖；引入 native/binary/Rust/C 扩展前，必须确认 Windows、Linux、Android 的 wheel 或源码构建路径。
- 正式核心依赖不要轻易加入 Android 不可构建包；`curl_cffi`、`camoufox`、`playwright` 只保留在 `tmp/` 历史实验中，不能进入正式 Python Core 或 Rust `fvcore`。
- `lxml` 优先替换：HTML 用 `BeautifulSoup(..., "html.parser")`，XML 用 `xml.etree.ElementTree`；替换后跑 EH 搜索、详情、缩略图、归档 smoke test。
- `Pillow` 用于 EH sprite crop 和封面处理，是 Android build 风险；先实测，失败时 Android 降级/禁用相关功能，不要引入更大的 native 图像依赖。
- `flet-web` 不应默认进入 Android target；Server 若引入 `fastapi`、`uvicorn` 等依赖，必须拆到 optional dependencies 或 server-only 入口。
- 平台相关能力通过小接口注入，例如文件选择器、WebView、系统下载目录；核心 provider、缓存、下载、数据模型尽量纯 Python。

## tmp 实验区

- `tmp/` 是隔离实验区，不是正式应用；可放 Camoufox、curl_cffi、Playwright、notebook 等实验依赖。
- `app/` 或正式 provider 不能直接 import `tmp/` 代码；迁移前必须检查 Android 依赖、敏感信息、协议边界、现有 `browser_session` / `image_cache` / `download_manager` 职责边界。
- `tmp/.cache/` 存放真实 cookies/profile，必须 gitignore，不能提交。
- Flet 打包必须排除 `tmp/`、`.cache/`、`*.ipynb` 和实验产物。

## Android 构建

- 平台存储拆分尚未完成验收：Data、Cache、Downloads、Temp 四域和桌面迁移代码已落地，但 Android 覆盖升级与“清除缓存”真机验证仍待完成；详细决策和验收矩阵以 `TODO.md` 为准。验收完成前不要把 Android 实际路径当成稳定接口，也不要新增依赖旧 `FletViewer/` 相对根目录的业务代码。
- Flet 0.85.3 配套 Flutter 3.41.7；不要用 scoop/winget 装 Flutter，版本不匹配或源不存在。
- 不要用 Puro；Flet CLI 调用的 `flutter` 子进程不会自动拿到 Puro 环境。
- 推荐让 `flet build apk` 自动下载配套 Flutter 到 `C:\Users\<用户名>\flutter\3.41.7\`；PATH 上不要有其他 Flutter 干扰。
- Android 返回键行为以正式 APK 为准；Flet 官方 Debug App 连接 Web/server 地址时返回键可能被 Debug App 外壳拦截，不能作为正式 APK 返回行为依据。
- Android SDK 需手动安装；推荐 SDK 36 + BuildTools 36.0.0，并执行 `flutter doctor --android-licenses` 接受许可。
- Windows 必须开启开发者模式，否则插件构建会卡在 symlink support。
- `ANDROID_HOME` / `ANDROID_SDK_ROOT` 必须指向真实 SDK 路径，Android Studio 默认通常是 `%LOCALAPPDATA%\Android\Sdk`。
- APK 产物在 `build/apk/app-release.apk`；默认 debug key 只适合本地测试，上架需配置 `[tool.flet.android.signing]`。
- 根目录 `main.py` 是 thin shim，转发到 `app/main.py`；改入口逻辑只改 `app/main.py`，不要动 shim。
- `pyproject.toml` 待修正：`requires-python >=3.10`；`[tool.flet.app].exclude` 必须包含 `tmp`、`.cache`、`*.ipynb`，并继续排除 `FletViewer`、`build`、`.git` 等产物。

## 日志

- 异步 worker 捕获异常时用 `app.debug_log.log_exception(...)`，不要只吞异常或只显示 UI 文本；终端需要 traceback。
- 网络和耗时路径用 `Timer(...)` / `log_debug(...)`；不要记录 cookie value、token、完整敏感 header。
