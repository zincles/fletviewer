# FletViewer

FletViewer 是跨平台 Anime Provider 浏览、阅读和下载工具。当前 Flutter GUI 明确标记为 **实验性 GUI**，功能和平台支持仍在持续迁移验证中。

## 目标架构

项目正在迁移为：

Flutter desktop / Android -> flutter_rust_bridge -> 进程内 fvcore Runtime
Flutter Web / NAS -> HTTP / SSE / resource -> fvcore executable

- `fvcore/`：纯 Rust 业务核心和独立 executable，负责 Provider、认证、网络、图片、缓存、下载、本地画廊、历史和存储；desktop/Android 通过 `flutter_rust_bridge` 嵌入它，Web/NAS 使用其 HTTP 控制面。
- `frontend/`：实验性的 Flutter 前端；desktop 默认在应用进程内启动唯一 `fvcore Runtime`，已接入 EH 搜索、首页封面、详情、页面索引和 reader 的真实纵向链路，本地画廊、Web、Android 和部分设置能力仍有占位内容。
- `app/`、`core/`、根 `main.py`：待退役 Python/Flet 迁移源，仅用于 fixture、行为对照和临时基线，不再继续产品化。

当前进度与下一步见 `TODO.md`，Rust Core 架构与迁移不变量见 `FVCORE.md`。

## 启动桌面应用

```bash
./start.sh
```

`start.sh` 每次都会执行 `flutter build linux --release`，再运行 release bundle；该构建经由 `cargokit` 同步编译 FRB 的 Rust library，因此无需手动执行 `cargo build` 或 `flutter build`。应用在同一进程创建唯一 `fvcore Runtime`，不会额外启动 `fvcore web` 或 loopback sidecar。该入口当前仅支持 Linux desktop。

- Rust API 变更后先运行 `./codegen.sh` 重新生成 FRB 桥代码；`start.sh` 启动前会校验两侧 content hash，不同步会拒绝启动。
- 应用对 `SIGTERM` 不响应（已知行为）；重复启动前若提示"已有实例正在运行"，请关闭旧实例或使用 `./start.sh --restart`（仅清理本应用同名进程）。

## Rust Core 开发

```bash
cd fvcore
cargo build
cargo run -- create-config
cargo run -- check-config
cargo run -- run
```

调试 HTTP 控制面与服务端 WebUI：

```bash
cargo run -- web
```

调试 WebUI 没有内置认证，只允许在可信网络使用；公开部署前必须由反向代理提供 TLS、认证和访问控制。

## 遗留 Python/Flet 基线

遗留产品仍可按 `pyproject.toml` 运行，但它不是目标架构，也不再新增产品能力。迁移完成后将删除 Python/Flet 入口、依赖和代码。
