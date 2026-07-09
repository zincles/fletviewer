# HACK

- `async_image()` 当前有一层线程启动兜底：优先走 `page.run_thread()`，若 `page.session.connection.loop` 不可用，则退回普通守护线程。
- 触发背景：画廊详情页的后台 worker 在加载完成后会动态替换 `cover_box.content = async_image(...)`；此时若 Flet session/connection 尚未准备好，直接 `page.run_thread()` 会抛出 `AttributeError: 'NoneType' object has no attribute 'loop'`。
- 当前修法位置：`app/controls/async_image.py` 的 `_start_background_task()`。
- 这只是临时稳定性补丁，不是最终线程模型。后续需要统一整理：
  - 哪些异步任务允许在后台线程里直接创建控件
  - 哪些 UI 控件只能在事件线程或已绑定 session 的上下文里创建/替换
  - `page.run_thread()`、普通线程、`request_update(page)` 三者的职责边界
  - 图片加载、详情页加载、查看器加载的并发模型是否要统一到一个更稳固的调度入口
