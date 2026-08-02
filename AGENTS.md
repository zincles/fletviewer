# FletViewer Agent Notes

## 项目目标

FletViewer 是跨平台 Anime Provider 浏览、阅读和下载工具，目标平台为 Windows、Linux、Android、Web 和 Server；核心能力包括 Provider 查询与认证、标签检索、图片缓存、持久下载、本地画廊和历史。

目标产品架构固定为 **Flutter 前端 + 纯 Rust `fvcore` 后端**，最终彻底删除 Python/Flet 正式运行路径：

```text
Flutter UI -> HTTP command/query + SSE event + binary resource/stream -> fvcore Runtime
```

- Flutter 负责 UI、路由、主题、展示状态、平台生命周期、文件选择、分享和通知。
- `fvcore` 负责全部 Provider、网络会话、认证、配置、operation、图片、缓存、下载、ZIP/CBZ、本地画廊、历史和存储。
- 当前 Python `app/` 与 `core/` 只是迁移源、fixture 来源和临时可运行基线，不再继续产品化；迁移完成后连同 Flet 依赖、入口和文档副本一起删除。
- `fvcore` 同一 Cargo crate 同时提供可嵌入 library 和可独立运行的 executable；标准产品 transport 由 executable 的 HTTP/SSE/resource 控制面提供。
- 参考方向：Pix-Ez Viewer、Imgur Grabber、EHViewer、Venera、Mihon/Tachiyomi、Emby。

## 协作风格

- 默认 TLDR：先结论、改了什么、还差什么；除非用户要求，不写长背景。
- 无论用户使用英文、中文或混合语言输入，默认使用中文回复；只有用户明确要求其他输出语言时才切换。
- Markdown 单行尽量承载完整意思，避免把短句拆成很多行；列表项可以较长。
- `TODO.md` 只保留当前决策、约束和下一步；长期规则写入本文件，历史流水由 Git 保存，隔离实验放 `tmp/`。
- 优先小改、可验证、低风险；不要为“统一”抹掉 Provider 差异。

## 禁止使用子代理

- 本规则适用于本仓库及其所有子目录中的全部任务。
- 禁止创建、调用、委派或等待任何 subagent（子代理）。
- 禁止使用 `spawn_agent`、`followup_task`、`send_message`、`wait_agent`、`interrupt_agent`、`list_agents`，以及其他任何多代理协作功能。
- 所有分析、检索、文件修改、测试和答复都必须由当前主代理独立完成。
- 即使子代理可能提升速度或质量，也不得启用；单一代理确实无法继续时直接说明限制。

## 目录职责与迁移边界

- `fvcore/`：当前唯一新增业务实现位置；纯 Rust Core、executable、HTTP 控制面和服务端调试 WebUI。
- `frontend/`：目标 Flutter 工程位置（创建后）；只包含 UI、平台机制和 `fvcore` transport client，不包含业务副本。
- `app/`、`core/`、根 `main.py`、`pyproject.toml`：待退役 Python/Flet 实现；只允许迁移 fixture、行为对照、严重数据安全修复或删除工作，不新增产品能力。
- `docs/flet/`：只供维护遗留实现时查证锁定版本 API，不作为目标 Flutter 技术文档；退役时删除。
- `tmp/`：隔离历史实验，不得被 `fvcore` 或 Flutter 正式代码 import/依赖，不得提交 Cookie/profile/cache secret。

## 目标架构边界

- 依赖方向固定为 `Flutter frontend -> fvcore transport -> fvcore Runtime`；Flutter 不直接读取 Core 数据库、缓存索引、下载任务文件或服务器 `Path`。
- Flutter 只维护展示状态和短生命周期交互状态；Provider session、operation、download、cache、gallery 和 history 的权威状态全部属于 `fvcore`。
- Dart client 只包装公开 command/query/event/resource 契约，使用与公开 DTO 一一对应的不可变模型；不得复制 Provider parser、重试/恢复状态机、缓存键、下载调度或存储业务。
- 控制数据使用 JSON；图片和 Archive 使用二进制 resource/stream，不以 base64 作为正式接口。
- SSE 只是 invalidation/revision 信号。客户端收到事件后按 ID 查询权威 snapshot；重复/乱序事件按 revision 丢弃，lagged、断线或 Runtime ID 变化后全量重拉。
- 同一组 Data、Cache、Downloads、Temp 在任一时刻只能有一个 Runtime owner；禁止 Python/Rust 双写，也禁止按 Provider、页面或任务族局部切换。
- 平台文件选择器返回的路径/URI 由 Flutter 平台层消费；Core 只暴露或接受受管 resource/stream 和类型化 command，不接受任意外部绝对路径或把 `content://` 冒充 `Path`。

## fvcore 核心约束

- `fvcore/` 必须保持纯 Rust，不嵌入或调用 Python、Dart、JavaScript 或其他语言的业务实现。
- 长期保持一个 Cargo crate；同一 package 的 library 实现完整 Core，executable 装配并运行同一 Runtime，不预建 Provider/server/CLI/C ABI 子 crate。
- 对外统一使用 command、不可变 snapshot、带 revision 的 event 和二进制 resource；不得暴露 HTTP client、Cookie jar、锁、数据库连接、Future、Tokio task 或服务器绝对路径。
- 当前 Python `core/` 仅是 executable specification 和 fixture 来源；先固定输入输出、错误、状态与持久化语义，再在 Rust 实现，不逐行翻译 Python 线程/锁模型。
- 默认 `#![forbid(unsafe_code)]`；不为假设中的 C ABI、JNI/FFI 预留 `unsafe`。未来确有不可替代需求时先更新 `FVCORE.md` 并记录安全不变量。
- Runtime 是配置、Profile/session、operation、图像缓存、下载和存储的唯一 owner；通常一进程一个 Runtime，外部使用可克隆 handle，不使用全局可变单例或 Core-wide 大锁。
- 并发必须异步、可取消、有 deadline、有界队列和不可变 task snapshot；所有内存、在途 bytes、队列与并发有硬上限。
- HTTP 控制面始终编译进标准 executable；配置只决定是否监听，不产生缺少控制面的正式变体。
- 公开错误使用稳定 `code`、安全 `message`、`retryable` 和适用的 Provider 信息；客户端不得解析自然语言 message 决定业务。

## executable、配置与控制面

- Runtime 配置固定为 `fvcore` executable 同目录的 `config.json`，暂不允许运行命令指定其他配置；相对存储路径以该目录为基准。
- `run` 不挂载 WebUI，listener 是否启用由配置决定；`web` 强制启用 listener 和 WebUI；二者支持 `--quit-in-seconds <正整数>` 并从 ready 后计时走正常 graceful shutdown。
- `run` / `web` 在创建 Runtime、数据库、锁或存储目录前严格解析并完整验证配置；缺失、未知字段或约束失败均拒绝启动。
- `check-config` 默认检查 executable 同级配置，也可离线检查显式文件；`create-config` 默认安全生成且拒绝覆盖，只有 `--override` 才通过锁和恢复副本重置完整默认值。
- 通过 Cargo 开发时，无参数命令统一使用 `fvcore/target/debug/config.json`，不能因当前工作目录存在其他配置产生歧义。
- HTTP API、SSE、resource 和服务端调试 WebUI 复用同一 Runtime；handler 只能包装 Core 方法，不能直接读写 registry、数据库或文件。
- 当前控制面无内置认证；调试 WebUI 的配置页按测试阶段例外明文处理 Provider secret，只允许可信 LAN。公网必须由可信反向代理提供 TLS、认证和访问控制。
- 正式配置 snapshot/API/event/log 必须脱敏；不得输出 Cookie/API secret、代理 URL/凭据、签名 URL、当前 Pixiv 用户 ID或服务器绝对路径。

## Provider 与网络

- 同一 Provider profile 共用连接池、认证、代理、限流和 session generation；配置变化创建新 generation，旧请求自然持有旧 generation 至完成，不持锁跨网络 `.await`。
- Provider transport 只接受配置 origin 及 allowlist redirect host，限制 redirect 和响应体大小；Cookie/API secret 不进入缓存键、任务、公开 DTO 或日志。
- EH 搜索、详情、图片和 Archive 共用同一逻辑会话。标准 E-Hentai 页面 origin 为 `e-hentai.org`，reader 私有 API 为 `api.e-hentai.org/api.php`；ExHentai 使用其 origin 下 `/api.php`。私有 API 即使以 `text/html` 返回也应按有界 body 尝试解析 JSON。
- EH 逐页 reader 图片可能重采样，只用于阅读；只有 Original Archive 承诺原始文件，批量下载不伪装为逐页原图。
- Danbooru、Gelbooru 和其他 Booru 只使用公开 API 与正式凭据；401/403/429、HTML 非预期响应和阻断返回稳定错误，不实现网页 fallback 或绕过。
- Booru 协议差异必须保留：Danbooru JSON、Gelbooru JSON DAPI、Gelbooru-style XML、Moebooru、E621、Philomena 和 Paheal 不强行共用 parser。
- Pixiv 使用用户导入 Cookie 和 Web AJAX，不实现浏览器登录、自动 Cookie 导出或 challenge bypass。
- Rust 正式代码不实现 Camoufox、Playwright、Turnstile、浏览器 profile、Cloudflare bypass、TLS impersonation 或 transport fingerprint 伪装。

## 图像与缓存

- 图像链路固定为 memory -> disk -> network；网络未命中优先 fetch 到有界内存、发布共享不可变 bytes，再可选异步落盘。
- 缓存使用真实内容的 128-bit MD5：32 位小写十六进制文件名加规范化后缀，并按前四位两级分片。Booru original 的 Provider MD5 用于 fetch 前去重和 fetch 后校验。
- 已知 MD5 按摘要合并，未知 MD5 按稳定 `ResourceKey` 合并；相同内容在内存和磁盘各只保留一份。
- 单个调用者取消只取消订阅；最后一个消费者离开才取消底层 transfer。内存缓存按 byte budget 淘汰，不按条目数假装有界。
- 响应进入缓存前检查状态、长度、Content-Type/magic、大小和 checksum；磁盘写使用同域 staging、flush 和原子发布，索引缺失执行 stale repair。

## 下载与本地画廊

- EH Archive 保留服务器原始 ZIP，不解压、不重压、不改名；Original/Resample 显式提交，H@H 只展示。
- Archive 获得并发槽后才取得签名 URL；记录 acquired time、有效期和 IP 限制。过期不自动重新消耗 GP；提交中断恢复为 `cost_unknown`，不得自动重放。
- 通用下载使用普通 HTTP Range，不做多线程分片；严格处理 200/206/416、If-Range、Content-Range、长度变化和断线。
- Booru/Pixiv 持久单图下载必须复用 `ImageService`，不得重复 fetch；用户产物属于 Downloads，不因清理 Cache 消失。
- `DownloadTaskView` 是 Flutter 下载列表/detail 的统一安全 DTO；Archive 与图片任务共享状态和 capability，但不伪造不支持的 command。
- 统一 download cancel/retry/delete 由 Runtime 按 owner 分派；非法 family/state 返回 `download_task_action_not_allowed`，任务不存在和队列满分别返回稳定错误。
- `redb` 本地画廊登记表是“已导入”权威状态，只保存 gallery ID 到受管根直接子目录名；导入只接受完整健康检查后的 gallery ID，不接受调用方路径。
- ZIP 阅读限制 member 数、单页和总声明大小、重复/隐藏/逃逸路径、加密和损坏；公开资源不暴露 Archive Path 或原文件名。
- 删除本地画廊必须预检并使用短期一次性确认令牌；导出使用有界异步 stream handle，句柄存活期间持有共享画廊占用。

## Flutter 前端

- Flutter 是目标正式前端，不经过 Flet、Python wrapper 或 Serious Python bridge；目标工程放在 `frontend/`。
- 第一条纵向验收链固定为：启动或连接 Runtime -> 校验协议/Runtime/四域身份 -> 查询统一下载列表 -> SSE 驱动按 ID 刷新 -> 读取二进制图片 resource -> 按 owner 责任 graceful shutdown。
- 桌面 Flutter 负责发现、启动或复用 packaged `fvcore` executable；只关闭自己启动的进程，并显示有界脱敏启动诊断。
- Server/Web 使用长期运行的 `fvcore`；Flutter Web 复用相同 Dart client model，经同源反向代理或明确受控的跨源策略连接，不能默认开放任意 CORS。
- Android 先用隔离 APK 验证 Rust sidecar 打包、private storage、loopback、后台、返回键、进程回收和恢复；只有实测不可靠才评估窄 JNI/FFI。
- Dart DTO 保留 provider-specific metadata；不得创建可变任务 registry、复制 retry/recovery 规则或通过本地状态猜测 capability。
- Flutter 平台层负责 FilePicker/SAF、分享、通知和把 Core resource stream 写到用户选择目标；不得把 `content://` 或浏览器文件伪装为服务器 `Path`。

## Web / NAS

- Web/NAS 是一等运行模式。Data、Cache、Downloads、Cookie、任务和本地画廊属于服务器，不代表浏览器设备本地状态。
- 当前首先面向可信网络中的单用户或共享实例；实现用户隔离前，不得假定凭据、历史和任务按浏览器用户隔离。
- 暴露到不可信网络前必须提供 TLS、认证、访问控制、上传限制和敏感日志治理；文档不得暗示当前实例天然适合公网多用户。

## 平台与依赖准入

- Rust 依赖引入前检查 Windows、Linux、Android 和 server target、feature、维护状态、许可证、安全公告、阻塞/分配行为；WASM 不是本轮 Core 目标。
- 优先 Rustls 等不依赖不可控系统运行时的实现；不得把 Python、Node、浏览器或实验工具带入 `fvcore` 运行时。
- Flutter package 必须确认 Windows、Linux、Android 和 Web 支持矩阵；平台插件只能实现平台机制，不复制业务，并为不支持平台提供明确禁用或 server fallback。
- 不因 Flet 旧版本、旧 APK 布局或 Python wheel 约束塑造新 Flutter/Rust 架构。
- Windows/Linux packaged executable 布局、配置邻接、版本握手和启动失败诊断必须自动验收；Android 行为只以目标 Flutter APK 真机结果为准。

## Legacy Python/Flet

- 不再为 Flet 重做页面、导航、主题、Web/NAS UX、分页或 Flutter extension，也不把 Rust 部分接回 Flet 形成过渡产品架构。
- 不给 Python Core 增加 Provider、下载、缓存、存储或平台依赖；需要的正式行为直接迁移到 Rust。
- 只有迁移 fixture、行为对照、严重数据安全修复或删除工作可以修改 `app/` / `core/`；修改时继续遵守其既有 `app -> core` 边界，不引入反向依赖。
- 查询遗留 Flet API 时使用 `docs/index.md` 和 `docs/flet/` 的本地锁定文档，不凭记忆升级 API。
- Python 与 Rust 对比测试只读 fixture或使用隔离临时四域，绝不同时写真实产品 SQLite、Cache、Downloads 或画廊。
- 迁移完成后删除 Python `app/`、`core/`、tests、`main.py`、Python/Flet 依赖和 Flet 文档，而不是保留兼容层、shim 或 deprecated 路径。

## 验证

- Rust 改动在 `fvcore/` 运行：`cargo fmt --all -- --check`、`cargo check --all-targets`、`cargo test --all-targets`、`cargo clippy --all-targets -- -D warnings`、`cargo doc --no-deps`。
- Flutter 工程创建后运行 `flutter analyze`、`flutter test`，行为变更还需真实桌面或目标平台 smoke；UI 改动必须实际驱动应用确认。
- 遗留 Python 改动按影响范围运行 `python -m compileall -q app core tests` 和相关 `python -m unittest`；不因退役方向降低数据安全修复的验证标准。
- 所有文档或代码修改后从仓库根运行 `git diff --check`；不得留下 whitespace error。

## 日志与敏感信息

- 日志记录 Runtime/operation/task ID、Provider、phase、耗时、队列和取消原因；不得记录 Cookie、API key、完整签名 URL、敏感 query/header 或服务器绝对路径。
- 后台 task panic/error 必须由 supervisor 回收并反映到 snapshot/event；Flutter transport 错误与 Core domain error 必须区分。
