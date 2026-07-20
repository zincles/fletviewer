# fvcore

`fvcore` 是 FletViewer 的纯 Rust 业务核心。需要 Rust 1.85 或更高版本。

在本目录中创建开发配置：

```bash
cargo build
cargo run -- create-config target/debug
cargo run -- check-config target/debug/config.json
```

运行核心：

```bash
cargo run -- run
```

运行核心并启用 HTTP 控制面与 WebUI：

```bash
cargo run -- web
```

查看中文帮助：

```bash
cargo run -- help
```
