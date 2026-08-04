# FletViewer

FletViewer 是跨平台 Anime Provider 浏览、阅读和下载工具。当前 Flutter GUI 明确标记为 **实验性 GUI**，功能和平台支持仍在持续迁移验证中。

## 目标架构

项目正在迁移为：

```text
Flutter UI -> HTTP/SSE/resource -> fvcore Runtime
```

- `fvcore/`：纯 Rust 业务核心和独立 executable，负责 Provider、认证、网络、图片、缓存、下载、本地画廊、历史和存储。
- `frontend/`：实验性的 Flutter 前端；当前仅覆盖最小纵向客户端，浏览、本地画廊和部分设置能力仍有占位内容。
- `app/`、`core/`、根 `main.py`：待退役 Python/Flet 迁移源，仅用于 fixture、行为对照和临时基线，不再继续产品化。

当前进度与下一步见 `TODO.md`，Rust Core 架构与迁移不变量见 `FVCORE.md`。

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
