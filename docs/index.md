# FletViewer 文档索引

本目录用于存放 FletViewer 自身的设计、决策和开发参考。官方 Flet 文档的本地副本位于 [`flet/`](flet/index.md)，其目录结构保持与 `E:/flet/website/docs/` 一致，便于后续同步和查找。

## 版本与使用原则

- 项目当前锁定 `flet==0.85.3`，以根目录 [`pyproject.toml`](../pyproject.toml) 为准。
- `docs/flet/` 是从本地 Flet 网站源码复制的完整参考，可能包含高于 0.85.3 的 API、命令和行为。采用新 API 前先确认其所属 Flet 版本，并在本项目安装的版本中实际验证。
- 本项目运行目标为 Windows、Linux、Android、Web 和 Server。平台差异、二进制依赖和构建约束先看 [`AGENTS.md`](../AGENTS.md)，再查官方发布文档。
- `docs/flet/` 中保留了网站使用的 MDX 组件、绝对资源路径和站点链接；它是源码参考副本，不保证作为独立 Markdown 网站直接渲染。
- 新的项目文档直接放在 `docs/` 下；不要写入 `docs/flet/`，以便后续整体同步官方文档。

## 快速入口

| 需求 | 优先查阅 | 本项目提示 |
|---|---|---|
| 了解 Flet、安装、创建或运行应用 | [官方首页](flet/index.md)、[安装](flet/getting-started/installation.md)、[创建应用](flet/getting-started/create-flet-app.md)、[运行与热重载](flet/getting-started/running-app.md) | 根入口是 `main.py`，实际装配入口为 `app/main.py`。Web 开发使用 `flet run --web --recursive`，不要在自动化工具中启动阻塞的 Web 服务。 |
| 找某个控件或属性 | [`flet/controls/`](flet/controls/)、[类型总览](flet/types/index.md) | 控件目录由网站生成分类入口，本地副本可从具体控件页面开始；再查关联类型页面，不要按旧 Flutter/Flet 记忆猜测参数名。 |
| 选择页面布局 | [Container](flet/controls/container.md)、[Row](flet/controls/row.md)、[Column](flet/controls/column.md)、[Stack](flet/controls/stack.md)、[ResponsiveRow](flet/controls/responsiverow.md)、[SafeArea](flet/controls/safearea.md) | 保持现有页面的视觉语言和自适应策略；移动端与桌面端都要验证。 |
| 构建大列表、图库或瀑布流 | [Large Lists](flet/cookbook/large-lists.md)、[ListView](flet/controls/listview.md)、[GridView](flet/controls/gridview.md) | 避免一次创建整本真实图片或大量卡片；使用分页、窗口化和分批更新。 |
| 显示图片、预览原图 | [Image](flet/controls/image.md)、[InteractiveViewer](flet/controls/interactiveviewer.md)、[RawImage](flet/controls/rawimage.md) | 必须遵守 `AGENTS.md` 的 `async_image`、`image_src_for_page()` 和图片开关规则；不要把本地路径或裸 bytes 直接作为跨 Web 的通用图片方案。 |
| 标签页、导航栏、抽屉 | [Tabs](flet/controls/tabs/index.md)、[Tab](flet/controls/tab.md)、[TabBar](flet/controls/tabbar.md)、[TabBarView](flet/controls/tabbarview.md)、[NavigationBar](flet/controls/navigationbar/index.md) | 当前项目 Tab 内容使用 `TabBarView`；`ft.Tab` 使用 `label=`。 |
| 对话框、底部面板和临时提示 | [AlertDialog](flet/controls/alertdialog.md)、[BottomSheet](flet/controls/bottomsheet.md)、[SnackBar](flet/controls/snackbar.md)、[声明式对话框](flet/cookbook/declarative-dialogs.md) | 现有 Dialog 按 `dialog.open = True`、`page.show_dialog(dialog)`、`page.pop_dialog()` 使用；提示优先复用 `app/toast.py`。 |
| 路由、返回和深层链接 | [Navigation and Routing](flet/cookbook/navigation-and-routing.md)、[Router](flet/cookbook/router.md)、[Page](flet/controls/page.md)、[View](flet/controls/view.md)、[TemplateRoute](flet/types/templateroute.md) | 由统一导航封装维护 `page.route`、history 和 `page.views` 同步；业务页不要直接散落操作 `page.views`。 |
| 后台 IO、并发和 UI 刷新 | [Async apps](flet/cookbook/async-apps.md)、[Page](flet/controls/page.md)、[Subprocess](flet/cookbook/subprocess.md)、[Multiprocessing](flet/cookbook/multiprocessing.md) | 控件树或属性在事件处理器外变更后必须刷新；涉及 UI 的后台工作用 `page.run_thread()`，并以 `app.ui_update.request_update()` 刷新。纯 IO 不直接操作控件。 |
| 文件、路径和本地持久化 | [Read and Write Files](flet/cookbook/read-and-write-files.md)、[FilePicker](flet/services/filepicker.md)、[StoragePaths](flet/services/storagepaths.md)、[SharedPreferences](flet/services/sharedpreferences.md)、[Client Storage](flet/cookbook/client-storage.md) | 存储分域仍在迁移；业务路径不要依赖旧的 `FletViewer/` 相对目录，当前决策见 [`TODO.md`](../TODO.md)。 |
| 权限、分享、URL 和安全存储 | [PermissionHandler](flet/services/permissionhandler/index.md)、[Share](flet/services/share.md)、[UrlLauncher](flet/services/urllauncher.md)、[SecureStorage](flet/services/securestorage/index.md) | 增加平台能力前先确认 Android/iOS 配置、Web 降级与隐私影响。 |
| 主题、颜色、字体和无障碍 | [Theming](flet/cookbook/theming.md)、[Colors](flet/cookbook/colors.md)、[Fonts](flet/cookbook/fonts.md)、[Accessibility](flet/cookbook/accessibility.md) | 主题逻辑集中于 `app/theme.py`；新控件应继承既有配色、密度和语义策略。 |
| 资源、动画、拖放和快捷键 | [Assets](flet/cookbook/assets.md)、[Animations](flet/cookbook/animations.md)、[Drag and Drop](flet/cookbook/drag-and-drop.md)、[Keyboard Shortcuts](flet/cookbook/keyboard-shortcuts.md) | 打包资源必须放在配置允许的路径，并检查所有目标平台。 |
| 编写 UI 集成测试 | [Integration testing](flet/getting-started/integration-testing.md)、[flet test](flet/cli/flet-test.md)、[测试类型](flet/types/testing/flettestapp.md) | 现有单元测试在 `tests/`；新增 UI 集成测试应为目标控件设置稳定 `key`，交互后等待 `pump_and_settle()`。 |
| 创建 Flutter 扩展 | [Creating an Extension](flet/extend/user-extensions.md)、[内置扩展](flet/extend/built-in-extensions.md)、[LayoutControl](flet/controls/layoutcontrol.md)、[DialogControl](flet/controls/dialogcontrol.md)、[Service](flet/controls/service.md) | 扩展位于 `extensions/`。Python 与 Dart 两端必须使用一致默认值；改 Flutter/Dart 后需重新构建，单改 Python 通常可直接运行。 |
| 查询命令行命令 | [CLI 总览](flet/cli/index.md)、[flet run](flet/cli/flet-run.md)、[flet build](flet/cli/flet-build.md)、[flet clean](flet/cli/flet-clean.md)、[设备与模拟器](flet/cli/flet-devices.md) | 构建或清理前阅读命令页与项目配置；不要把构建产物加入版本控制。 |
| 打包 Windows/Linux/macOS | [发布总览](flet/publish/index.md)、[Windows](flet/publish/windows.md)、[Linux](flet/publish/linux.md)、[macOS](flet/publish/macos.md) | `pyproject.toml` 的 `[tool.flet.app]` 定义入口和排除项，改动时要防止将 `tmp/`、缓存或构建产物打入包内。 |
| 打包 Android | [Android 发布](flet/publish/android.md)、[Android/iOS 二进制包](flet/reference/binary-packages-android-ios.md) | 先遵守 `AGENTS.md` 中固定的 Flutter、SDK、ABI 与签名约束。非纯 Python 依赖必须先确认 Android wheel 或构建路径。 |
| 发布 Web 或 Server | [Web 发布](flet/publish/web/index.md)、[动态网站](flet/publish/web/dynamic-website/index.md)、[静态网站](flet/publish/web/static-website/index.md)、[FastAPI API](flet/fastapi/fastapi.md) | Web 端不能读取服务器本地图片路径；静态 Web 的 Pyodide 不支持常规线程，异步设计需额外验证。 |
| 处理版本升级与弃用 | [发行说明](flet/updates/release-notes.md)、[破坏性变更](flet/updates/breaking-changes/index.md)、[兼容性策略](flet/updates/compatibility-policy.md) | 升级 Flet 前先阅读跨越版本的变更，特别检查 Android 构建、存储目录、协议和已弃用控件 API。 |

## 当前项目的高频主题

### UI 线程与刷新

1. 先查 [Async apps](flet/cookbook/async-apps.md) 了解同步 handler、异步 handler、协程和后台任务。
2. 再查 `AGENTS.md` 的“UI 线程 / 更新”规则，它是本项目的强制约束。
3. 代码实现优先查看 `app/ui_update.py`、`app/image_results.py` 和 `app/image_progress.py` 的既有做法。
4. 不在纯 IO 线程直接修改 Flet 控件；后台任务的异常必须记录 traceback。

### 路由、View 栈与持久 Tab

1. 先查 [Navigation and Routing](flet/cookbook/navigation-and-routing.md) 了解 `page.route`、`page.views`、`on_route_change` 与 `on_view_pop` 的关系。
2. 本项目的统一入口在 `app/navigation.py`；阅读后再调整 `app/main.py` 或页面跳转逻辑。
3. 修改后至少验证页面内跳转、系统返回、浏览器 Back/Forward、深层链接和刷新后的状态。

### 图库、图片与性能

1. 大量卡片优先查 [Large Lists](flet/cookbook/large-lists.md)、`ListView` 和 `GridView` 文档。
2. 再遵守 `AGENTS.md` 的“图像与缓存”“页面 / 视图”规则，特别是窗口化、缓存和 Web 图片来源。
3. 现有图库统一入口为 `app/views/gallery_debug.py:create_gallery_view(...)`；不要新建绕过既有卡片/JSON 设置的列表实现。

### Flutter 扩展实验

1. 从 [Creating an Extension](flet/extend/user-extensions.md) 开始；需要实验时按官方模板在 `extensions/` 下重新创建独立扩展包。
2. 可视控件继承 `LayoutControl` 并由 Dart `LayoutControl(...)` 包装；弹出控件继承 `DialogControl`；服务继承 `Service` 并在 Dart 中注册服务。
3. Python dataclass 默认属性没有显式修改时不会传给 Flutter，Dart 读取时必须给出同值默认值。
4. 新增第三方 Flutter 包前检查 Windows、Linux、Android 的可用性，尤其避免将 native/Rust/C 依赖直接引入 Android 核心路径。

### 多平台发布

1. 项目打包配置在 [`pyproject.toml`](../pyproject.toml)，Flet 的完整配置语义见 [发布总览](flet/publish/index.md)。
2. `flet build` 会打包项目文件，排除配置是安全边界的一部分；调整目录或新增实验文件后检查 `[tool.flet.app].exclude`。
3. Android 构建前先检查 [Android 发布](flet/publish/android.md) 与 `AGENTS.md` 的 Android 小节；正式上架必须配置签名，默认 debug key 只适用于本地测试。
4. Web 与静态 Web 的运行模型不同；涉及本地文件、线程、二进制依赖、网络会话时都要单独验证。

## 全量官方分类入口

| 分类 | 入口 | 内容 |
|---|---|---|
| 入门 | [flet/getting-started/](flet/getting-started/) | 安装、创建、运行、测试和移动设备测试。 |
| 教程 | [flet/tutorials/](flet/tutorials/) | Calculator、ToDo、Chat、Solitaire。 |
| Cookbook | [flet/cookbook/](flet/cookbook/) | 常见工程实践、布局、状态、异步、存储、认证和日志。 |
| 控件 API | [`flet/controls/`](flet/controls/) | 所有内置控件、扩展控件及其属性；这是网站生成的分类入口，本地副本可从目录内的具体控件页面开始查阅。 |
| 服务 API | [flet/services/](flet/services/) | 文件选择、权限、存储、设备传感器、分享等平台服务。 |
| 类型 API | [flet/types/](flet/types/) | 枚举、事件、样式、主题、测试和基础类型。 |
| CLI | [flet/cli/](flet/cli/) | `flet create`、`run`、`build`、`publish`、`test` 等命令。 |
| 发布 | [flet/publish/](flet/publish/) | 桌面、Android、iOS、动态 Web 和静态 Web。 |
| 扩展 | [flet/extend/](flet/extend/) | 自定义 Flutter 扩展与内置扩展。 |
| FastAPI | [flet/fastapi/fastapi.md](flet/fastapi/fastapi.md) | Flet 与 FastAPI 集成。 |
| Flet Studio | [flet/studio/](flet/studio/) | Flet Studio 使用文档。 |
| 更新 | [flet/updates/](flet/updates/) | 发行说明、弃用和破坏性变更。 |
| 历史归档 | [flet/archive/](flet/archive/) | 旧版或归档内容，仅在维护旧实现时参考。 |

## 维护本索引

- 新增项目设计、运行手册、实验结论或迁移记录时，在 `docs/` 根目录或适当的项目子目录创建文档，并在此页补充入口。
- 更新官方副本时，以 `E:/flet/website/docs/` 整体覆盖 `docs/flet/`，不要混入项目内容；完成后核对文件数量并复查本页链接。
- 需要升级 Flet 时，先更新 `pyproject.toml` 中版本，再依据 [发行说明](flet/updates/release-notes.md) 和 [破坏性变更](flet/updates/breaking-changes/index.md) 建立迁移与验证清单。
