# fvcore

`fvcore` 是 FletViewer 及其他调用者共用的纯 Rust 业务核心。它既可根据配置独立运行，也可作为 Rust library 嵌入其他程序。

当前 crate 已建立第一版 Foundation：版本化配置、稳定错误、强类型 Runtime/Operation ID、`CoreBuilder` / `CoreRuntime` / `CoreHandle`、有界命令与 operation 队列、deadline/取消、revision/event cursor、协作关闭、始终编译的 HTTP 控制面、四域存储、跨进程实例锁、版本化 `redb` 状态数据库，以及 Reqwest/Rustls 共享网络和不可变 Provider session generation。真实 Provider 已完成 Danbooru JSON 与 Gelbooru JSON DAPI 的搜索/详情和已知 MD5 original 图片主链路，并建立 EH Archive 选项查询起点；接下来完善图像缓存监管和未知 MD5 alias。完整顺序、并发约束、外部接口和切换策略见仓库根目录的 [`FVCORE.md`](../FVCORE.md)。

约束：

- `fvcore` 只包含 Rust，不嵌入或调用 Python、Dart、JavaScript 等业务实现。
- `fvcore` 长期保持一个 Cargo crate；同一 package 提供 `lib.rs` 的嵌入 API 和 `main.rs` 的可运行 Core，不预先拆 provider/server/adapter crate。
- 标准 executable 始终编译集成 HTTP 控制面；是否监听只由运行参数或配置决定，HTTP 与嵌入 API 使用同一 Runtime。
- Core 不依赖 Flet、Flutter、Bevy 或具体前端；本轮不实现任何前端、binding、WASM 或 challenge backend。
- 可以引入支持 Windows、Linux、Android 和 server 的成熟 Rust 依赖；引入前检查目标平台、维护状态、许可证、安全公告和 feature 范围。
- 默认禁止 `unsafe`；如未来确有不可替代需求，必须先修改架构决策并记录安全不变量。
- 最终业务范围覆盖现有 Python `core/` 的全部正式能力；Python 实现只作为重写期间的只读行为和 fixture 参考，切换完成后退出正式运行路径。

## 当前命令

| 命令 | 行为 |
|---|---|
| `cargo run -- run` | 使用默认配置运行，HTTP 默认不监听 |
| `cargo run -- --web` | 运行并监听默认地址 `127.0.0.1:8787` |
| `cargo run -- --webui` | 开启 HTTP listener 和内嵌调试 WebUI |
| `cargo run -- --web --no-webui` | 只提供 JSON/SSE/resource API，不挂载 HTML WebUI |
| `cargo run -- --no-web` | 即使配置启用也不启动 HTTP listener |
| `cargo run -- --web-listen 127.0.0.1:9000` | 运行并覆盖 HTTP 监听地址 |
| `cargo run -- --config fvcore.toml run` | 从 TOML 配置运行 |
| `cargo run -- --config fvcore.toml check` | 解析并验证配置后退出，不创建存储目录 |

配置文件始终可省略。未提供 `--config` 时，`run` 和 `check` 都构造完整的 `CoreConfig::default()`，其中包含 `eh/default`、`pixiv/default`、`danbooru/default`、`gelbooru/default` 四个无需凭据即可创建的默认会话。TOML 省略 `profiles` 时也保留这四项；一旦显式声明任意 `[profiles.*]`，整个 profile map 由配置文件提供，不与默认 map 隐式合并。

HTTP Foundation 路由：

| 路径 | 内容 |
|---|---|
| `/` | 单页调试总览：Runtime、HTTP、存储、全部 profile session、Booru 搜索和最近 operation；可由配置或 `--no-webui` 移除 |
| `/ui/search` | Danbooru/Gelbooru 服务端渲染搜索和分页 |
| `/ui/post` | Post metadata 与 original Fetch 表单 |
| `/ui/operations`、`/ui/operation` | Operation 列表、自动刷新详情、取消和结果图片 |
| `/health/live` | HTTP server 存活状态 |
| `/health/ready` | Runtime 是否 ready |
| `/api/v1/runtime` | JSON Runtime snapshot |
| `/api/v1/profiles` | 安全的 Provider profile/generation snapshot |
| `/api/v1/profiles/{provider}/{profile}/probe` | POST，仅探测已配置的 profile 根地址 |
| `/api/v1/providers/danbooru/{profile}/posts` | GET，Danbooru JSON API 搜索；query 为 `tags/page/limit` |
| `/api/v1/providers/danbooru/{profile}/posts/{id}` | GET，Danbooru JSON API 详情 |
| `/api/v1/providers/gelbooru/{profile}/posts` | GET，Gelbooru JSON DAPI 搜索；query 为 `tags/page/limit` |
| `/api/v1/providers/gelbooru/{profile}/posts/{id}` | GET，Gelbooru JSON DAPI 详情 |
| `/api/v1/providers/{provider}/{profile}/posts/{id}/original/fetch` | POST，启动 Danbooru/Gelbooru original image operation |
| `/api/v1/providers/pixiv/{profile}/illusts/{id}` | GET，Pixiv AJAX 作品详情与多页 metadata |
| `/api/v1/providers/pixiv/{profile}/illusts/{id}/pages/{page}/fetch` | POST，启动 Pixiv original page image operation |
| `/api/v1/providers/eh/{profile}/galleries/{gid}/{token}/archives` | GET，查询 EH Original/Resample/H@H Archive 选项 |
| `/api/v1/resources/images/{md5}/{extension}` | GET，返回已验证的不可变图片 bytes，不使用 base64 |
| `/api/v1/operations` | GET 查询 operation；POST 启动 Foundation fake operation |
| `/api/v1/operations/{id}` | 查询单个 operation snapshot |
| `/api/v1/operations/{id}/cancel` | 协作取消 operation |
| `/api/v1/events?cursor=<sequence>` | SSE replay 和实时事件 |

最小配置示例：

```toml
schema_version = 1
instance_name = "fvcore"
command_capacity = 256
shutdown_seconds = 15

[control]
enabled = true
listen = "127.0.0.1:8787"
webui_enabled = true

[storage]
data = "FletViewer/Data"
cache = "FletViewer/Cache"
downloads = "FletViewer/Downloads"
temp = "FletViewer/Temp"

[operations]
max_active = 128
max_queued = 256
retained_terminal = 512
default_deadline_seconds = 30

[events]
capacity = 1024
retained = 2048

[network]
connect_timeout_seconds = 10
request_timeout_seconds = 30
max_response_bytes = 8388608
max_redirects = 5
# proxy_url = "http://127.0.0.1:7890"

[images]
max_image_bytes = 33554432
memory_cache_bytes = 134217728
max_inflight_bytes = 134217728
cache_write_queue = 64

[profiles.danbooru_default]
provider = "danbooru"
profile = "default"
base_url = "https://danbooru.donmai.us/"
user_agent = "fvcore/0.1.0"
allowed_redirect_hosts = []
# cookie_env = "FVCORE_DANBOORU_COOKIE"
# api_user_env = "FVCORE_DANBOORU_LOGIN"
# api_key_env = "FVCORE_DANBOORU_API_KEY"
max_concurrent_requests = 4
min_request_interval_ms = 0
```

四个内建 profile 的默认 origin 和图片 host allowlist：

| 内部 ID | 显示名称 | 默认 origin | 默认额外图片 host |
|---|---|---|---|
| `eh/default` | EHentai | `https://e-hentai.org/` | 无 |
| `pixiv/default` | Pixiv | `https://www.pixiv.net/` | `i.pximg.net` |
| `danbooru/default` | Danbooru | `https://danbooru.donmai.us/` | `cdn.donmai.us` |
| `gelbooru/default` | Gelbooru | `https://gelbooru.com/` | `img1` 至 `img4.gelbooru.com` |

默认会话不包含 Cookie 或 API key。需要登录或 API 凭据时，通过 TOML 的 `cookie_env`、`api_user_env`、`api_key_env` 指向环境变量；secret value 不直接写进 TOML。当前 Rust 能力为 Danbooru/Gelbooru 搜索、详情和原图，EH Archive 选项起点，以及 Pixiv AJAX 作品详情、多页 metadata 和 original page Fetch。

`run` 会在任何 Runtime actor 或 HTTP listener 启动前创建并规范化四个存储域，在 Data 域取得 `.fvcore.lock` 独占锁，并打开 `Data/fvcore.redb`。四域必须互不相同且不能互相嵌套；同一 Data 域同时只允许一个 Runtime 持有。

Fake operation 只用于在真实 Provider 接入前验证排队、过载、deadline、取消、revision 和事件，不是正式 Provider 功能。事件 journal 有界；cursor 早于最早保留事件时，调用者必须重新查询 snapshot 后再订阅。SSE 慢消费者会收到 `resync_required` 后断开。

Provider 网络只使用配置中的 HTTP(S) origin。底层 transport 只接受相对路径，拒绝绝对 URL、跨 origin 路径逃逸、跨 scheme redirect 和未授权 redirect host；响应体在接收过程中受硬字节上限约束。Cookie 只从 `cookie_env` 指定的环境变量读取，snapshot、日志和配置序列化结果只显示 `has_cookie`，不包含 secret value。Profile 更新会创建新 generation；新请求立即使用新 generation，已经持有旧 generation 的请求继续完成且全程不持有 registry 锁。

每个 profile generation 还拥有独立的并发 semaphore 和最小请求启动间隔；等待并发槽或速率间隔均可取消。Danbooru API 凭据通过 HTTP Basic Auth 注入，Gelbooru API 凭据按其 DAPI 要求加入 query；凭据只从 `api_user_env` / `api_key_env` 读取，不进入公开 snapshot 或日志。

Danbooru/Gelbooru original fetch 先解析 post metadata，并要求 Provider 提供有效 original MD5。已知 MD5 按 `memory -> Cache/files/<前两位>/<后两位>/<md5>.<规范扩展名> -> shared network` 查询；网络结果检查 metadata 长度、magic bytes 和真实内容 MD5，失败时不入缓存。同一 MD5 的并发 operation 共享一次 transfer，各自可取消，最后一个订阅者离开时才取消底层请求。二进制由嵌入 API 的 `ImageResource` 或 HTTP resource 路由返回，不进入 JSON/base64。CDN URL 必须使用 profile scheme 且 host 位于 profile origin 或 `allowed_redirect_hosts`；Cookie 只发送给 profile 自身 host。

Pixiv original 没有 Provider 内容摘要，使用 `ResourceKey(pixiv, illust_id, page, original)` 合并请求并查询 `Cache/image_aliases.json`。首次网络完成后计算真实内容 MD5、发布内存 resource，并将 blob 与 alias 送入有界异步写队列；重启后 alias 可直接定位内容寻址 blob。Runtime 关闭在 deadline 内 drain 写队列。Pixiv AJAX 请求附带同 origin Referer、`X-Requested-With` 和用户导入 Cookie；图片 Cookie 不传播到 `i.pximg.net`，但保留作品页 Referer。

调试 WebUI 完全由 Axum 服务端渲染，CSS 通过 `include_str!` 编译进 executable；不使用 Node.js、npm、前端框架、外部 CDN 或 base64 图片。搜索使用普通 GET，Fetch/取消使用普通 POST，运行中的 operation 页面通过 `<meta refresh>` 刷新。`control.enabled = false` 表示完全不监听 HTTP；`control.enabled = true, webui_enabled = false` 表示 API-only；两者都为 `true` 时提供 API 和 WebUI。当前控制面没有内置认证，默认只应监听 loopback 或由可信反向代理提供 TLS、认证和访问控制。
