# fvcore 架构决策与迁移基线

本文是 `fvcore` 的权威架构记录，用于固定纯 Rust Core 的产品形态、状态所有权、公开接口和当前迁移范围。若其他根目录文档与本文冲突，以本文关于 `fvcore` 的决策为准。

## 结论

- `fvcore` 是纯 Rust、可独立运行、也可被其他 Rust 程序嵌入的完整核心，不包含、不嵌入、不调用 Python、Dart、JavaScript 或其他语言的业务实现。
- `fvcore` 只有一个 Cargo crate；同一 package 同时产出 library 和 `fvcore` executable，不预设 provider、server、CLI、C ABI 或前端子 crate。
- library 实现配置、Runtime、Provider、共享会话、网络、图像、缓存、下载、任务和公开方法；executable 只负责装配并运行同一套 library，不复制业务。
- Core 可像 sing-box/Xray 一样根据配置独立运行；第三方也可以直接构造 `CoreRuntime` 并通过 `CoreHandle` 使用相同能力。
- Core 对使用者提供 command、snapshot、event、resource 四类语义；控制数据结构化，图像和 Archive 等二进制资源不通过 base64 JSON 传输。
- `fvcore` 正在全面重写现有 Python `core/` 的全部业务能力；完成并切换后，Provider、网络、会话、图像、缓存、下载、ZIP/CBZ、本地画廊、历史和存储均由 Rust Core 独占。
- Booru 只使用站点公开 API，不实现 Camoufox、浏览器自动化、Cloudflare bypass、TLS impersonation 或 challenge backend。
- 目标平台是 Windows、Linux、Android 和 server；本轮不支持 WASM。可以引入能覆盖这些目标的成熟 Rust 依赖，不追求零依赖。
- 当前 Python `core/` 仅在重写期间作为只读行为参考和 fixture 来源，不是新架构约束、兼容目标或长期产品实现；迁移采用纵向能力，不逐行翻译，也不允许 Python/Rust 双写真实存储。
- HTTP 控制面是标准 `fvcore` executable 的集成组件，始终参与正式编译；是否监听及监听参数只由配置文件或命令行决定，不使用 Cargo feature 裁剪。

## 产品形态

`fvcore` 是一个 package、一个 crate、两种使用方式：

```text
fvcore/
├─ Cargo.toml
└─ src/
   ├─ lib.rs       # 嵌入 API 与全部核心实现
   ├─ main.rs      # 可独立运行的 fvcore
   ├─ config/
   ├─ runtime/
   ├─ control/
   ├─ provider/
   ├─ net/
   ├─ image/
   ├─ cache/
   ├─ download/
   └─ storage/
```

嵌入模式：

```rust,ignore
let runtime = CoreBuilder::new(config).build().await?;
let core = runtime.handle();
```

独立运行模式：

```text
fvcore run --config fvcore.toml
```

独立程序读取并验证配置、获得存储实例锁、构造唯一 Runtime、恢复任务、按配置或参数决定是否监听集成 HTTP 控制面，并优雅关闭。HTTP handler 只能包装与嵌入者相同的 command、query、snapshot、event 和 resource 方法，不能反向污染 Provider、缓存或下载模块，也不能直接读写内部 registry、数据库或文件。

单 crate 是当前长期约束。内部通过 Rust module 和私有边界组织；不要为了形式上的解耦创建空 crate。只有用户明确改变该决策时才讨论 workspace 拆分。

## 当前 Python 参考实现

当前 `core/` 约 8175 行 Python，已经提供本轮迁移所需的可执行规范：

- `core/provider/ehgrabber.py`：EH 会话、Archive 选项、签名 URL 和错误行为。
- `core/provider/pixiv.py`：Pixiv Web AJAX、Cookie、作品详情和多页 URL。
- `core/provider/booru.py`：Danbooru JSON API、Gelbooru JSON DAPI、Gelbooru-style XML 和 Moebooru 协议。
- `core/net/browser_session.py`：共享 Cookie、UA、代理和连接复用。
- `core/image/fetcher.py`：共享图片请求、订阅取消、进度和缓存写入的现有语义。
- `core/download/manager.py`：任务、Range、恢复、取消、进度和持久化。
- `core/api/archive.py`：EH Archive 的应用服务边界。

Python 已有 Facade/DTO、Runtime 和 UI-independent 边界只在过渡期维持现有产品；Rust 不继承这些接口，也不照搬 Python 线程池、可变任务对象、base64 DTO 或 import 副作用装配。

## Core Runtime

### 单一所有权

一个运行实例通常只有一个 `CoreRuntime`，它是配置、Provider profile、会话、操作、图像缓存、下载任务、存储和后台任务的唯一 owner。外部使用者只持有可克隆的 `CoreHandle`。

```text
CoreRuntime
├─ ConfigManager
├─ SessionRegistry
├─ ProviderRegistry
├─ OperationRegistry
├─ ImageService
├─ DownloadService
├─ CacheService
├─ StorageService
└─ EventHub
```

这不是 Rust `static` 全局单例，也不是一个包住所有工作的 Core-wide 大锁。设计上必须允许测试创建多个完全隔离的 Runtime；两个 Runtime 不得同时拥有同一持久存储根目录。

### Handle 与状态访问

公开 API 使用命令和不可变 snapshot，不暴露内部 HTTP client、Cookie jar、锁、Future、Tokio task、数据库连接、文件句柄或可变任务引用。

```rust,ignore
pub async fn start_image_fetch(&self, request: ImageFetchRequest) -> Result<OperationId, CoreError>;
pub async fn operation_snapshot(&self, id: OperationId) -> Result<OperationSnapshot, CoreError>;
pub async fn start_download(&self, request: DownloadRequest) -> Result<DownloadTaskId, CoreError>;
pub async fn cancel_operation(&self, id: OperationId) -> Result<(), CoreError>;
```

每次状态变化产生单调递增 revision；非法状态转换必须由类型或状态机拒绝。

### 生命周期

初始化顺序：验证四域存储并取得实例锁、加载配置、恢复缓存索引、恢复下载任务、创建 Provider session generation、启动有界 worker，最后进入 ready。

关闭顺序：拒绝新操作、取消临时请求、为持久下载保存恢复点、在 deadline 内 drain 缓存写队列、flush 节流状态、回收所有后台任务并释放会话。

## 公开控制模型

Core 对嵌入者和未来独立进程控制面使用相同业务语义：

- Command：启动 fetch/download、取消、重试、更新配置和关闭。
- Snapshot：读取 Runtime、Provider、Operation、Download 和 Cache 的不可变当前状态。
- Event：接收带 event sequence 和 revision 的状态、进度、完成、失败及会话变化。
- Resource：获取图像 bytes 或流式资源；控制事件只携带 resource descriptor/handle。

事件队列必须有界，慢消费者不能阻塞底层任务。phase 变化立即发布；字节进度按时间或增量节流；完成、失败和取消不能丢失。断线重连必须能先查询 snapshot，再从可用 cursor 继续事件。

## Provider 会话

### Profile 与 generation

会话按 `ProviderProfileKey(provider, profile)` 管理，初期只有 `default` profile，但不能把单账户写死进所有内部 API。

```text
eh/default
pixiv/default
danbooru/default
gelbooru/default
```

每个 profile 共享连接池、认证、代理、限流和登录状态。Cookie、UA、代理或凭据配置变化时创建不可变 client generation：新请求使用新 generation，已运行请求继续持有旧 generation 至完成，旧 generation 无引用后释放。

不得持有 registry/session 锁跨越网络 `.await`。锁只保护短时状态交换，网络请求取得 `Arc<SessionGeneration>` 后独立运行。

### EH

EH 搜索、详情、图片、Archive 选项、签名 URL 和 Archive 下载必须共用同一逻辑会话，统一 Cookie jar、UA、Accept、Accept-Language、代理、连接池、登录验证 TTL、并发和限流状态。Archive 流式响应完整生命周期都持有对应 generation。

公开页面不强制登录；Archive 使用需要已认证 profile。登录状态绑定 generation，不使用脱离配置版本的全局 bool。

### Booru

Danbooru、Gelbooru 和其他 Booru 使用公开 API：

- Danbooru：现代 JSON API，使用 login/API key。
- Gelbooru：JSON DAPI，使用 user_id/API key。
- Safebooru、Rule34 和 Gelbooru-alike：公开 XML/JSON DAPI。
- Moebooru：公开 XML API。

不实现网页抓取 fallback、Camoufox、Playwright、Turnstile、`cf_clearance` 自动获取或 transport fingerprint 伪装。API 的 401/403/429、HTML 非预期响应和认证错误返回稳定错误；Core 不尝试 bypass。

### Pixiv

第一版使用现有行为已经验证的 Web AJAX 和用户导入 Cookie，统一 Cookie、User ID、Referer、连接池和代理。Core 不实现浏览器登录、自动 Cookie 导出或 challenge 处理。

## 图像 Fetch 与缓存

### 目标链路

```text
Provider metadata
  -> memory content cache
  -> disk content cache
  -> shared network fetch into bounded memory
  -> format/length/MD5 verification
  -> publish immutable in-memory resource
  -> optional supervised disk persistence
```

能不做磁盘 I/O 就不做磁盘 I/O。磁盘命中只读取一次并提升到内存；网络未命中优先 fetch 到有界内存，调用者获得不可变共享 bytes 后，磁盘缓存作为可选、异步、受监管的副作用执行。磁盘缓存失败不能把已经成功的图片 fetch 改为失败。

使用 `Bytes`/`Arc<ImageResource>` 等共享不可变数据，避免完整图像在 Core 内重复复制。不得在正式接口中生成 base64。

### 内容 MD5

缓存使用真实图片内容的 128-bit MD5，即 32 个小写十六进制字符，不使用 URL hash 作为最终 blob 名称：

```text
d256310bfab43e08b6422e311cd9b2c9.webp
```

磁盘路径使用两级分片：

```text
Cache/files/d2/56/d256310bfab43e08b6422e311cd9b2c9.webp
```

- Danbooru/Gelbooru 原图 metadata 已给 MD5 时，在 fetch 前按内容 MD5 查内存和磁盘，未命中才访问 CDN，完成后必须校验 expected/actual MD5。
- Provider post MD5 通常只属于 original，不得错误用于 sample/preview。
- Pixiv 或未知摘要资源按稳定 `ResourceKey(provider, media, page, variant)` 合并请求，网络接收时增量计算 MD5，完成后建立 `ResourceKey -> ContentMd5` alias。
- `ContentMd5` 用于内容寻址和 Provider 完整性校验；它不是安全签名。若未来存在更强 Provider checksum，作为独立字段保存。
- 相同内容 MD5 只保留一份内存 bytes 和一份磁盘 blob；发现同摘要但内容验证冲突时拒绝复用并报告稳定错误。

扩展名由 magic bytes、可信 Content-Type、Provider metadata、URL path 依次判定并规范化；至少统一 `.jpeg -> .jpg`，拒绝未经验证的路径字符。相同 bytes 不得因 `.jpeg/.jpg` 别名产生两份 blob。

### 内存预算与请求合并

“内存优先”必须有界：单图大小、全局在途 bytes、内存 cache bytes、并发 fetch 数和等待队列都必须可配置并有硬上限。无 `Content-Length` 时按 chunk 逐步申请预算；超限后停止读取并返回稳定错误。

请求合并优先级：已知 MD5 按 `ContentMd5` 合并，未知 MD5 按 `ResourceKey` 合并。每个调用者拥有独立 operation；一个调用者取消只取消其订阅，最后一个消费者离开才取消底层 transfer。

内存缓存按 byte budget 淘汰，不只按条目数。淘汰仅释放缓存自身引用，活跃调用者持有的 `Arc` 仍然有效。

### 图像进度

图像 fetch 是正式 operation，至少暴露：

```text
queued
resolving
checking_memory
checking_disk
waiting_for_shared_fetch
fetching
verifying
ready_in_memory
cache_write_queued
completed / failed / cancelled
```

Snapshot/event 包含 phase、bytes done、可选 bytes total、来源（memory/disk/network）、共享状态、content MD5、cache persistence 和稳定错误。没有总长度时只报告已接收字节，不伪造百分比。

### 索引与磁盘写入

Runtime 启动时将轻量 alias/index 加载到内存；热路径不为每次命中读取索引文件，不为每次访问同步写 `last_accessed_at`。访问时间和索引更新节流、批量、原子持久化。

网络结果验证后先发布内存资源，再将同一共享 bytes 提交到有界磁盘写队列。写入同一 Cache 域的 staging、flush、原子 rename，最后更新 index。文件缺失执行 stale repair；孤儿 blob 由维护任务清理，不在每次 fetch 中扫描目录。

## 下载系统

### Operation 与持久任务

临时 Provider 请求和图片 fetch 是 operation；用户创建、可恢复且有最终产物的是 download task。两者共享取消、deadline、revision、事件和监管基础，但持久化语义不同。

用户下载 Pixiv/Booru 单图时优先复用 `ImageService` 已有的内存/磁盘/共享网络结果，不能由 DownloadService 再 fetch 一次。正常图片在大小预算内使用内存路径；超大图片允许按明确策略直接流式写 Downloads。

EH Archive 始终流式写磁盘，不将整个 ZIP 放入内存。

### 通用传输

- 分块写 `.part`，使用普通 HTTP Range，不做多线程分片。
- 持久化 ETag、Last-Modified、Accept-Ranges 和 offset；续传使用 If-Range 并严格验证 Content-Range。
- 服务端忽略 Range 返回 200 时从头覆盖，不追加；明确处理 206、416、长度不符、中途断连和服务器变更。
- 进度按约 1 MiB 或 2 秒节流持久化；事件可以更频繁但必须节流。
- 完成后校验、flush 并在同存储域原子发布；取消默认保留可恢复 `.part`，删除任务才清理。

### EH Archive

只支持 EH 官方 Original/Resample Archive；H@H 选项可以展示但不能创建本地下载任务。EH 逐页 fetch 不作为批量下载方案。

- 获得下载并发槽位后才获取签名 URL，避免排队消耗有效期。
- 获取 URL 后立即开始下载，记录 acquired time、通常 86400 秒有效期和最多 2 个 IP 的约束。
- URL 过期第一版返回 `source_expired`，不自动重新获取，避免未经确认再次消耗 GP。
- 若进程在 Archive 提交成本后、可靠保存结果前退出，恢复为成本状态不确定，不自动重放。
- 保留服务器返回的原始 ZIP 和安全化服务器文件名，不解压、不重压、不改 CBZ、不提取封面。
- EH Archive 默认并发 1，配置硬上限 2。

### Pixiv/Booru 单图

- Booru 第一版下载 original；MD5 metadata 属于 original，sample/preview 没有独立摘要时下载后计算。
- Pixiv 请求由 illust ID、page index 和 variant 标识；多页作品每个 task 只下载指定一页。
- 第一版不做 Pixiv 整本批量、作者批量、ugoira、视频转换、Booru tag 批量或 CBZ 打包。
- 用户明确下载的文件属于 Downloads，不因清理 Cache 消失；其命名策略和缓存 blob 名称相互独立。

## 存储与配置

沿用 Data、Cache、Downloads、Temp 四域语义。Core 接收显式路径，验证规范化和所有权，并使用实例锁阻止两个 Core 或 Python/Rust 同时写同一持久域。

Core 提供严格、带 `schema_version` 的配置模型、TOML/JSON 解析和验证，同时允许嵌入者直接构造 Rust struct。未知字段、默认值、敏感字段和迁移策略必须明确。凭据支持环境注入，不能进入公开 snapshot、任务 JSON、缓存键或日志。

WASM 不在本轮目标中；不为了 WASM 牺牲文件系统、线程、网络流和持久下载设计。正式依赖必须支持 Windows、Linux、Android 和 server 目标，并优先选择维护活跃、无不必要 native 运行时、许可兼容的库。

依赖准入至少检查：

- 目标平台和 Android NDK 构建情况。
- 是否要求系统 OpenSSL、浏览器、Python、Node 或其他不可控运行时。
- feature 是否可收紧，是否引入无关协议或 Web framework。
- 安全公告、维护状态、许可证、lockfile 和可复现构建。
- 热路径的复制、分配、阻塞和取消行为。

## 错误与可观测性

公开错误使用稳定 code、provider、retryable 和安全 message，前端/调用者不得解析中文文本决定业务。至少覆盖 invalid input、authentication required、access denied、rate limited、unexpected response、overloaded、deadline exceeded、cancelled、image too large、checksum mismatch、source expired、resume rejected、length mismatch、disk full、I/O 和 parse。

日志和 tracing 记录 operation/task ID、provider、phase、耗时、队列和取消原因；不记录 Cookie value、API key、完整签名 URL、敏感 query/header。后台任务 panic/error 必须被 supervisor 回收并反映到 snapshot/event。

Runtime snapshot 至少公开生命周期、Provider generation/认证状态、活跃/排队操作、内存预算、缓存统计、下载统计和最近失败，但不泄漏凭据。

## 安全边界

- 默认 `#![forbid(unsafe_code)]`；本 crate 不为假设中的未来 binding 预留 unsafe。
- Provider 返回 URL 必须经过 scheme、host/redirect 和凭据传播策略，不能把 Core 变成任意 URL 下载器或 SSRF 代理。
- 外部不能提交任意绝对输出路径；只提交类型化资源和受控目标，Core 在 Storage roots 内解析安全相对路径。
- 图片响应检查 HTTP 状态、长度、Content-Type、magic bytes、大小和 MD5，再进入共享缓存。
- 原子发布使用同域 staging、flush 和 rename；关键 Data/Downloads 操作失败不得先删除源。
- 不允许 Python 与 Rust 同时写同一 SQLite、Cache、Downloads、本地画廊或任务目录；对比测试只读 fixture，写测试使用隔离临时目录。

## 不属于 Core 的能力

- Flet、Flutter、Bevy、Web UI 或其他前端代码。
- Python binding、C ABI、JNI、FFI 或平台 extension。
- 多 crate workspace、provider plugin crate 或空 adapter crate。
- Camoufox、Playwright、浏览器 profile、Cloudflare bypass、Turnstile 和 challenge backend。
- WASM 构建。
- 在 Rust 未达到对应能力的验收标准前切换该能力的真实存储写所有权。

## 迁移顺序

### 阶段 0：修正文档与工程基线

- 固定单 crate、lib+bin、支持平台、依赖准入和不做事项。
- 完成 format、clippy、test、doc、依赖审计和目标平台 compile CI。
- 定义 `CoreError`、ID、时间、revision、secret redaction 和 fixture 目录。

### 阶段 1：配置、Runtime 与控制模型

- `CoreConfig`、TOML/JSON、验证和环境 secret 注入。
- `CoreRuntime`、`CoreHandle`、initialize/shutdown、实例锁和 supervisor。
- Command、Snapshot、Event、Resource 模型及有界事件队列。
- fake operation 验证状态机、取消、deadline、overload、revision 和 shutdown。

### 阶段 2：共享会话和网络基础

- Provider profile/session registry 与 immutable generation。
- 连接池、Cookie、认证、代理、redirect、限流和脱敏。
- 流式响应 lease 必须覆盖完整 body 生命周期。
- fake server 验证重定向、取消、timeout、响应上限和凭据边界。

### 阶段 3：图像、内存与 MD5 缓存

- `ContentMd5`、`ResourceKey`、格式识别和 alias index。
- byte-budgeted memory cache、in-flight 合并和消费者取消。
- memory -> disk -> network 链路、进度 operation 和 `Arc`/`Bytes` 资源。
- 有界异步磁盘持久化、原子发布、stale repair 和维护任务。

### 阶段 4：Booru API 与单图

- 先用 fixture 固定 Danbooru JSON、Gelbooru JSON、Gelbooru-style XML 和 Moebooru XML。
- 先完成 metadata -> known MD5 -> cache -> CDN -> verify 的 original 单图闭环。
- 认证、429、错误响应和 API 差异使用 provider-specific parser，不强行统一协议。

### 阶段 5：Pixiv 单图

- Cookie/User ID session、作品详情和 pages URL。
- 单页/指定页 original fetch、未知 MD5 下载后计算、alias 持久化。
- 不进入批量、ugoira 或 CBZ。

### 阶段 6：持久下载与 EH Archive

- Download task 状态、snapshot、恢复、Range、If-Range、验证和原子发布。
- 图片下载复用 ImageService；Archive 使用磁盘流式传输。
- EH options、Original/Resample、签名 URL、GP/IP/expiry 和成本不确定恢复语义。

### 阶段 7：可执行 Core 与集成 HTTP 控制面

- `fvcore run --config ...`、signal、health、诊断和优雅关闭。
- 标准 executable 始终编译 HTTP 控制面；配置和参数只控制运行时是否监听、监听地址、认证和权限。
- HTTP 提供 command/query/event/resource transport 和极简纯 HTML 状态页；它只包装 Core 方法，不产生第二套业务模型或业务状态。

### 阶段 8：平台验证与所有权切换准备

- Linux 和 Windows 测试/下载 smoke。
- Android NDK 目标编译和 Termux ARM64 Runtime smoke。
- server 长运行、断线、恢复、磁盘不足和压力测试。
- 定义 Python 任务/缓存迁移或隔离策略；未完成前不切换产品路径。

### 阶段 9：完整产品能力与 Python Core 退役

- 迁移 ZIP/CBZ 索引与安全读取、本地画廊、历史、搜索/feed、详情以及各 Provider 的完整阅读和下载能力。
- 每项能力以 fixture、错误、状态、持久化和恢复测试固定行为后，切换为 Rust 唯一 owner。
- 全部验收完成后，`app/` 只通过嵌入 API 或 HTTP 控制面使用 `fvcore`，Python `core/` 不再进入正式运行路径并最终删除。

## 验收标准

- `fvcore` 单 crate 同时可 `cargo build --lib` 和构建可执行程序，不依赖 Python、Flet、Flutter、Bevy、浏览器或外部 Web 运行时；标准 executable 自带 HTTP 控制面实现。
- 标准 executable 始终包含 HTTP 控制面，关闭监听只是不启动服务，不产生缺少控制能力的另一种编译产物。
- Windows、Linux、Android 和 server 所需 target 可编译；WASM 明确不在范围。
- 一个 Runtime 统一拥有 Provider session、操作、内存缓存、磁盘缓存和下载任务；测试可创建多个隔离 Runtime。
- EH 全链路共享同一 profile session generation；配置更新不破坏正在读取的旧响应。
- Booru API 提供 MD5 时缓存命中不访问 CDN；网络结果 MD5 不符绝不入缓存。
- 未知 MD5 图像只 fetch 一次，结果优先在有界内存发布，再可选异步写磁盘。
- 同一内容在内存和磁盘各只有一份；缓存文件名为 32 位小写内容 MD5 加规范化后缀。
- 图像 fetch 的 phase、字节进度、来源、共享状态、结果和失败可通过 snapshot/event 观察。
- EH Archive 保留原始 ZIP、支持取消/恢复/进度，过期不自动重新消耗 GP。
- 所有队列和内存使用有上限；取消、deadline、overload、shutdown 和后台错误有确定行为。
- 控制数据与二进制资源分离，不以 base64 传输正式图像/Archive。
- 测试不读写现有 Python 产品真实 Data/Cache/Downloads，日志不泄漏凭据。
- Rust Core 覆盖现有 Python `core/` 的全部正式业务能力；切换完成后 Python Core 不再承担运行时所有权。

## 当前下一步

| 状态 | 能力 | 当前产物或下一验收点 |
|---|---|---|
| 已完成 | 单 crate library/executable | `lib.rs` 与 `main.rs` 共用同一 Runtime |
| 已完成 | Foundation 依赖与工程检查 | Tokio、Axum、Serde、Clap、Tracing；format/check/test/clippy 已通过 |
| 已完成 | 配置、错误、ID 与 Runtime snapshot | 严格 TOML、稳定错误、UUID v7 Runtime ID、revision 和生命周期 |
| 已完成 | Runtime/Handle 与集成 HTTP | 有界命令队列、协作关闭、health、JSON snapshot 和极简 HTML |
| 已完成 | 存储 Foundation | 四域规范化、Data 实例锁、`redb` schema v1 和存储 snapshot |
| 已完成 | Command/Event/Operation Foundation | Operation ID、状态机、有界 active/queue/retention、deadline、取消、event journal/cursor 和 SSE |
| 已完成 | 共享 session 与网络 Foundation | Reqwest/Rustls、profile generation、代理、同 scheme/allowlist redirect、响应上限、取消和 Cookie 脱敏 |
| 下一步 | Provider 限流与首个 Booru 纵向能力 | Profile 级并发/速率限制、Danbooru fixture、搜索/详情和稳定错误 |
| 后续 | 图像内容缓存 | Bytes、内容 MD5、内存预算、共享 fetch 和异步磁盘持久化 |
