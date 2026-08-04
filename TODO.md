# TODO

本文只保留当前决策、最近进度和可执行下一步；长期架构与安全不变量以 `AGENTS.md` 和 `FVCORE.md` 为准，历史实现细节由 Git 保存。

## 目标架构

最终产品是 **Flutter 前端 + 纯 Rust `fvcore` 后端**，Python/Flet 技术栈全部退役：

```text
Flutter desktop / Android -> flutter_rust_bridge -> 进程内 fvcore Runtime
Flutter Web / NAS / CLI -> HTTP + SSE + binary resource/stream -> fvcore executable
```

- Flutter 是唯一目标产品前端；负责 UI、路由、主题、平台生命周期、文件选择、分享和通知。
- `fvcore` 是唯一业务与状态 owner；负责 Provider、认证、网络、图片、缓存、下载、ZIP/CBZ、本地画廊、历史和存储。
- desktop 与 Android 在 Flutter 进程内创建一个长寿命 `CoreRuntime`；Rust 的 Tokio worker 在后台执行任务，Dart 通过 `flutter_rust_bridge` 的异步 API、事件 stream 和二进制资源接口调用，不启动 sidecar、不监听 loopback。
- Web/NAS、CLI 和调试 WebUI 继续使用 `fvcore` executable 的 HTTP/SSE/resource adapter；FRB 与 HTTP 必须调用同一 Rust facade，不得形成两套业务实现。
- Python `app/` / `core/` 只作为迁移源、fixture 和临时行为基线，不再产品化；迁移完成后连同 Flet 入口、依赖、测试和文档副本一起删除。
- Dart 不复制 Rust 业务状态机；同一组 Data、Cache、Downloads、Temp 同时只能有一个 Runtime owner，禁止 Python/Rust 双写或按 Provider/页面局部切换。

## 当前状态

- `fvcore` 已经是可运行后端，不是脚手架：Provider 查询、图像与内容缓存、EH Archive、Booru/Pixiv 持久单图下载、本地 ZIP 画廊、HTTP/SSE/resource 和调试 WebUI 均形成首轮纵向闭环。
- `frontend/` Flutter desktop 工程已存在，并在应用标题中明确标记为实验性 GUI；当前下载页已形成首条 UI 链路，但浏览、本地画廊和设置页仍有占位内容。
- `app/fvcore_sidecar.py` 及 Dart executable launcher 只保留为历史 transport 探针，不再是本地产品路径；完成 FRB 切换后删除。
- 当前阶段是：先用 FRB 在 Linux desktop 跑通进程内 Runtime、snapshot、下载列表/命令、事件和图片 bytes，再复用同一 binding 接 Android arm64。
- 不再安排 Flet 页面重做或“先把 Rust 下载页接回 Flet”的过渡工作。
- 不再安排 Flet 页面重做、分页、主题、Web/NAS UX、Flutter extension 或“先把 Rust 下载页接回 Flet”的过渡工作。

## 最近推进了什么

2026-07-30 至 2026-07-31 的提交是在为独立前端准备 Rust 后端边界：

| 提交 | 结果 | 对目标架构的意义 |
|---|---|---|
| `75ad793`、`90adbc2` | Pixiv 推荐、关注、排行和收藏 feed；executable 支持定时正常关闭 | 补查询面并让真实 Runtime 可自动 smoke |
| `976b2fb` | 只读 `fvcore inspect` CLI | Core-only 诊断工具；明确不是 Flutter transport |
| `abb4027`、`8a57a61` | 17 个现有 Booru 完成搜索、详情和 original fetch；前 12 个支持标签补全 | 完成 Booru 首轮纵向迁移 |
| `35b65e5`、`e3a29ec` | Booru original 与 Pixiv 指定页持久下载，复用 `ImageService` | 生成可由任意前端管理的持久 Downloads 任务 |
| `d4aa3b0`、`a29f3df`、`563f3c2` | 图片下载取消、重试、删除、进度和调试 WebUI | 补齐任务状态机与人工验收面 |
| `798adad` | 图片下载并发、排队和持久队列设硬上限 | 保证独立 Runtime 的资源边界 |
| `1722b09`、`f10ad41` | EH Archive 与图片任务统一为 `DownloadTaskView` 和统一 command | 给 Flutter 提供单一下载契约，而非复制两套任务模型 |
| `2facd87` | sidecar supervisor 验证发现/启动、Runtime/四域身份、复用和 owner shutdown | 验证 executable 作为独立后端的进程边界 |

## 已完成的 Rust 基线

- 单 Cargo crate library/executable、严格同级配置、四域存储、实例锁和 graceful shutdown。
- `CoreRuntime` / `CoreHandle`、command、不可变 snapshot、revision event、resource、取消、deadline 和有界队列。
- Provider profile/session generation，共享连接池、认证、代理、限流、受限 redirect 和响应上限。
- EH 浏览/详情/reader/Archive，17 个 Booru 搜索/详情/original fetch，Pixiv feed/详情/指定页 original fetch。
- 内容 MD5/alias、有界 memory -> disk -> network、共享 fetch、独立取消和异步缓存监管。
- EH Archive、Booru original、Pixiv 指定页持久下载；统一下载 query/command/capability/稳定错误。
- 本地画廊登记、健康盘点、安全 ZIP 阅读、统一 resource、确定性 sidecar、确认删除和有界流式导出。

## Flutter transport v1 冻结（已完成）

### 1. 公开协议与兼容握手

- [x] Runtime snapshot 公开稳定的 `api_protocol_version = 1` 和 Cargo `core_version`；launcher 复用 Runtime 前强制校验协议并拒绝缺失/不兼容版本。
- [x] 协议兼容规则固定：新增 OPTIONAL 响应字段保持 v1；删除、重命名、改变字段类型/语义或破坏路由时提升 protocol version。
- [x] snapshot/API/event 继续禁止泄漏 Cookie、API secret、代理/签名 URL、当前 Pixiv 用户 ID 或服务器绝对路径。
- [x] `/api/v1/contract` 机器可读地固定首条 Flutter 链路的 route/status、SSE envelope/resync、resource header 和稳定错误字段。

### 2. 非空持久任务跨真实进程恢复（已完成）

- [x] 使用临时 executable 副本、同级 `config.json` 和隔离四域；测试不触碰现有 Python 产品存储、外网、真实 Provider 或 Cookie。
- [x] 隔离 fixture 覆盖 running 图片任务、Archive downloading 和 paid submitting 状态；正式 HTTP 统一列表验证 ID、provider/kind、状态、capability、安全输出和时间字段。
- [x] owner 关闭后从同一四域启动新 Runtime，验证任务集合和恢复状态持久保留；`downloading -> failed/retry_supported`，`submitting -> cost_unknown` 且不自动重放。

### 3. 本地嵌入生命周期与打包契约

- [x] 用 `flutter_rust_bridge` 为 Linux desktop 暴露窄 Rust facade；生成代码与必要的 FFI `unsafe` 隔离于 bridge 层，业务模块继续 `forbid(unsafe_code)`。Windows/Android 仍待平台验收。
- [x] Flutter 在 Linux desktop 启动时创建唯一进程内 Runtime，严格校验 protocol/Runtime/四域身份；应用退出时只关闭该 Runtime，并等待 graceful shutdown。
- [x] Linux build 自动产出并打包 Rust library；配置和四域路径由 Flutter 平台层显式传入，不依赖 executable 同级目录或当前工作目录。Windows/Android 打包仍待验收。
- [x] 启动失败返回稳定、脱敏的 domain/bridge error；secret 和服务器绝对路径不得进入 UI 诊断、snapshot 或日志。
- [x] Python `app/fvcore_sidecar.py` 已完成早期 executable 边界验证；它不进入正式客户端。

### 4. 事件一致性契约（已完成）

- [x] event 只作 invalidation；客户端收到 Archive/image task event 后按 ID 查询 `DownloadTaskView`，不从 event 重建权威 registry。
- [x] 客户端按 revision 忽略重复/乱序事件；收到 `resync_required`、cursor 失效或 Runtime ID 变化后重新订阅或全量重拉。
- [x] Rust 自动测试覆盖 stale cursor 显式 `resync_required`；现有 Dart HTTP transport 测试覆盖 envelope 解析、稳定错误和重连入口，FRB stream 必须保持相同语义。

## 当前阶段：Flutter desktop 最小纵向客户端

- [x] 创建 `frontend/` Flutter 工程，目标覆盖 Linux/Windows desktop；不移植旧 Flet 控件树。
- [x] 第一条 UI 链路已显示 Runtime 连接状态、统一下载列表、cancel/retry/delete 和内容 MD5 图片 resource；Flutter GUI 已标记为实验性。
- [x] 接入 FRB build/codegen，在 Linux desktop 启动进程内 `CoreRuntime` 并显示真实 snapshot。
- [x] 将统一下载列表、cancel/retry/delete、event invalidation 和图片 bytes 切到 FRB；本地 loopback client 与 executable launcher 不再是 Linux desktop 默认路径。
- [ ] 把浏览页的第一个 Provider 搜索、详情和 reader 从占位内容替换为真实 Rust 调用。
- [ ] 把本地画廊 inventory/detail/page 从占位内容替换为真实 Rust 调用。
- [x] `flutter analyze`、`flutter test`、Rust gate、Python sidecar probe 和真实 Linux desktop smoke 全部通过。
- [ ] Flutter Web 复用同一 Dart domain model 连接 server `fvcore`；明确服务器存储、反向代理和文件下载语义。
- [ ] Android arm64 打包同一 FRB library，真机验证 private storage、后台/返回键、进程回收和持久任务恢复。

## Python/Flet 退役顺序

1. 按 Provider、图像、缓存、下载、ZIP/CBZ、本地画廊、历史和存储对照 Python fixture，补齐 Rust 尚缺正式行为。
2. Flutter 每完成一条纵向能力，验收其只通过公开 transport 工作；不把 Python Core 作为运行时 fallback。
3. Flutter 覆盖正式产品能力并完成数据迁移后，停止 Python owner，Rust 取得整个四域所有权；失败按完整 Runtime 回滚。
4. 删除 `app/`、`core/`、遗留 tests、根 `main.py`、`pyproject.toml` 中 Python/Flet 产品依赖及 `docs/flet/`，不保留 shim、alias 或 deprecated bridge。

## 暂不做

- 不再继续 Flet 产品功能、UX 重做、分页、Flutter extension 或 Android Flet APK 验收。
- 不把 Rust Core 接回 Flet 下载页，也不写 Python `fvcore` client 作为正式产品层。
- 不创建 Dart Provider parser、下载状态机、缓存数据库或第二套任务 registry。
- 不按 Provider/tab 局部切换存储，不允许 Python/Rust 双写。
- 不实现 Camoufox、Playwright、challenge bypass、WASM、Pixiv 批量/ugoira，或未经 Android 真机证据支持的 JNI/FFI。

## 当前验证命令

Rust 门禁（`fvcore/`）：

```bash
cargo fmt --all -- --check
cargo check --all-targets
cargo test --all-targets
cargo clippy --all-targets -- -D warnings
cargo doc --no-deps
```

Flutter 门禁（`frontend/`）：

```bash
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter build linux
```

当前 executable 进程边界探针（仓库根目录，Flutter launcher 落地后由 Dart 测试替代）：

```bash
python -m unittest -v tests.test_fvcore_sidecar
```

文档或代码修改后：

```bash
git diff --check
```
