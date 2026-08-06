# FletViewer Experimental GUI

这是 FletViewer 的实验性 Flutter GUI；desktop 通过 `flutter_rust_bridge` 在应用进程内启动 `fvcore Runtime`。

从仓库根目录启动：

```bash
./start.sh
```

该脚本每次构建 Linux release bundle 后再运行；FRB Rust library 随 Flutter build 编译。不需要手动执行 `cargo build` 或 `flutter build`，也不需要、也不应并行启动独立 `fvcore` 进程。

当前仍未完成：

- 本地画廊 inventory、详情和阅读
- Web、Android 以及完整平台生命周期验收

当前已完成第一条 EH 浏览纵向链路：真实 Rust 搜索、详情/标签/评论、页面索引、reader operation 轮询和 MD5 resource 图片读取。

Rust Core 的正式能力和迁移状态见仓库根目录的 `README.md`、`TODO.md` 和 `FVCORE.md`。
