# FletViewer Experimental GUI

这是 FletViewer 的实验性 Flutter GUI，当前用于验证 `fvcore` 进程内 Runtime 和最小纵向客户端链路。

当前仍未完成：

- 本地画廊 inventory、详情和阅读
- Web、Android 以及完整平台生命周期验收

当前已完成第一条 EH 浏览纵向链路：真实 Rust 搜索、详情/标签/评论、页面索引、reader operation 轮询和 MD5 resource 图片读取。

Rust Core 的正式能力和迁移状态见仓库根目录的 `README.md`、`TODO.md` 和 `FVCORE.md`。
