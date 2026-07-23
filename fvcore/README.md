# fvcore

`fvcore` 是 FletViewer 的纯 Rust 业务核心。需要 Rust 1.85 或更高版本。

在本目录中创建开发配置：

```bash
cargo build
cargo run -- create-config
cargo run -- check-config
```

这些无参数命令与 `run` / `web` 使用同一份 `target/debug/config.json`。如需离线管理其他位置，可显式传入目录或文件。

`create-config` 默认拒绝覆盖已有配置。只有确定要丢弃所有旧值并重置为完整默认配置时，才执行 `cargo run -- create-config --override`；指定目录时使用 `cargo run -- create-config /path/to/directory --override`。该选项不合并旧字段，覆盖使用配置锁和恢复副本安全发布，中断后的下一次配置操作会先完成恢复。

运行核心：

```bash
cargo run -- run
```

运行核心并启用 HTTP 控制面与 WebUI：

```bash
cargo run -- web
```

调试 WebUI 没有认证，`control.allow_lan` 默认开启，因此默认可从可信局域网访问。配置页会按当前测试阶段要求明文显示 Cookie、API user 和 API key，并安全写回 executable 同级 `config.json`；任何能访问面板的人都能读取和修改这些凭据。关闭“允许局域网访问”并重启后会强制仅监听 loopback；不要把该面板直接暴露到不可信网络或公网。

查看中文帮助：

```bash
cargo run -- help
```
