# fvcore

`fvcore` 是 FletViewer 及其他调用者共用的纯 Rust 业务核心。它既可根据配置独立运行，也可作为 Rust library 嵌入其他程序。

当前 crate 仅建立独立编译和版本边界。后续实现顺序、并发约束、外部接口和 Python 参考实现迁移策略见仓库根目录的 [`FVCORE.md`](../FVCORE.md)。

约束：

- `fvcore` 只包含 Rust，不嵌入或调用 Python、Dart、JavaScript 等业务实现。
- `fvcore` 长期保持一个 Cargo crate；同一 package 提供 `lib.rs` 的嵌入 API 和 `main.rs` 的可运行 Core，不预先拆 provider/server/adapter crate。
- Core 不依赖 Flet、Flutter、Bevy 或具体前端；本轮不实现任何前端、binding、WASM 或 challenge backend。
- 可以引入支持 Windows、Linux、Android 和 server 的成熟 Rust 依赖；引入前检查目标平台、维护状态、许可证、安全公告和 feature 范围。
- 默认禁止 `unsafe`；如未来确有不可替代需求，必须先修改架构决策并记录安全不变量。
- 当前业务范围是 EH 官方 Archive 下载、Pixiv 单图和 Booru API 单图；ZIP/CBZ 阅读与自建 CBZ 暂停。
