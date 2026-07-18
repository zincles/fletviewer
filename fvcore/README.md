# fvcore

`fvcore` 是 FletViewer 及其他调用者共用的纯 Rust 业务核心。它既可根据配置独立运行，也可作为 Rust library 嵌入其他程序。

当前 crate 已建立第一版 Foundation：版本化配置、稳定错误、强类型 Runtime/Operation ID、`CoreBuilder` / `CoreRuntime` / `CoreHandle`、有界命令与 operation 队列、deadline/取消、revision/event cursor、协作关闭、始终编译的 HTTP 控制面、四域存储、跨进程实例锁、版本化 `redb` 状态数据库，以及 Reqwest/Rustls 共享网络和不可变 Provider session generation。接下来全面重写现有 Python Core 的全部正式业务能力；实现顺序、并发约束、外部接口和切换策略见仓库根目录的 [`FVCORE.md`](../FVCORE.md)。

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
| `cargo run -- --web-listen 127.0.0.1:9000` | 运行并覆盖 HTTP 监听地址 |
| `cargo run -- --config fvcore.toml run` | 从 TOML 配置运行 |
| `cargo run -- --config fvcore.toml check` | 解析并验证配置后退出，不创建存储目录 |

配置文件始终可省略。未提供 `--config` 时，`run` 和 `check` 都构造完整的 `CoreConfig::default()`；所有默认值与下方示例一致。

HTTP Foundation 路由：

| 路径 | 内容 |
|---|---|
| `/` | 无 JavaScript、极少内联 CSS 的自动刷新状态页 |
| `/health/live` | HTTP server 存活状态 |
| `/health/ready` | Runtime 是否 ready |
| `/api/v1/runtime` | JSON Runtime snapshot |
| `/api/v1/profiles` | 安全的 Provider profile/generation snapshot |
| `/api/v1/profiles/{provider}/{profile}/probe` | POST，仅探测已配置的 profile 根地址 |
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

[profiles.danbooru_default]
provider = "danbooru"
profile = "default"
base_url = "https://danbooru.donmai.us/"
user_agent = "fvcore/0.1.0"
allowed_redirect_hosts = []
# cookie_env = "FVCORE_DANBOORU_COOKIE"
```

`run` 会在任何 Runtime actor 或 HTTP listener 启动前创建并规范化四个存储域，在 Data 域取得 `.fvcore.lock` 独占锁，并打开 `Data/fvcore.redb`。四域必须互不相同且不能互相嵌套；同一 Data 域同时只允许一个 Runtime 持有。

Fake operation 只用于在真实 Provider 接入前验证排队、过载、deadline、取消、revision 和事件，不是正式 Provider 功能。事件 journal 有界；cursor 早于最早保留事件时，调用者必须重新查询 snapshot 后再订阅。SSE 慢消费者会收到 `resync_required` 后断开。

Provider 网络只使用配置中的 HTTP(S) origin。底层 transport 只接受相对路径，拒绝绝对 URL、跨 origin 路径逃逸、跨 scheme redirect 和未授权 redirect host；响应体在接收过程中受硬字节上限约束。Cookie 只从 `cookie_env` 指定的环境变量读取，snapshot、日志和配置序列化结果只显示 `has_cookie`，不包含 secret value。Profile 更新会创建新 generation；新请求立即使用新 generation，已经持有旧 generation 的请求继续完成且全程不持有 registry 锁。
