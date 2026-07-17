# FletViewer

FletViewer 当前是使用 Python + Flet 构建的跨平台 Anime Provider 浏览、阅读和下载工具，目标包括 Windows、Linux、Android，以及部署在 NAS/server 后通过浏览器远程使用的 Web 模式。目前产品主线以 EHentai 为主；Booru、Pixiv 已接入部分 Core API 和页面，但完整阅读/下载闭环仍在建设，challenge backend 仍处于隔离实验阶段。

## 架构方向

- Flet 是当前可用前端，但不再被视为永久架构约束；未来前端可以通过 Rust library、Web API 或窄 C API 使用同一核心。
- 新建的 `fvcore/` 是未来业务核心，必须保持纯 Rust；当前 Python `core/` 继续作为已跑通的产品实现和 Rust 迁移行为基线，不另行打包成 Python `fvcore`。
- `fvcore` 固定为单一 Cargo crate，同一 package 同时提供可嵌入 library 和可独立运行的 executable；内部实现 Provider、共享会话、图像、缓存、下载、任务和统一 Runtime。
- 当前 Rust 迁移只覆盖 EH 官方 Archive 下载及 Pixiv/Booru 单图；ZIP/CBZ 阅读、自建 CBZ、前端接入和 Camoufox/challenge 路线暂停。
- 不恢复 Flutter + Serious Python bridge；当前 Flet 缺失的原生能力仍可通过带 Python wrapper 的 Flutter extension 补充，但该扩展不属于 `fvcore`。
- Web/NAS 是一等部署目标；Web 页面看到的配置、缓存、下载和本地画廊属于服务器，浏览器设备文件只能通过上传、下载和文件选择流程交换。

## 当前能力

| 模块 | 状态 |
|---|---|
| EH 首页、热门、排行榜、收藏、订阅和搜索 | 已实现 |
| 卡片、列表和瀑布流浏览 | 已实现，默认瀑布流 |
| 画廊详情、缩略图和图片查看器 | 已实现 |
| 分页/垂直阅读 | 已实现第一版 |
| 图片异步加载、磁盘缓存和EH sprite crop | 已实现 |
| EH Archive下载、断点续传和任务恢复 | 已实现第一版 |
| 本地画廊和ZIP阅读 | 已实现 |
| 浏览历史 | 已实现 |
| Booru | 搜索和详情 Core API 已接入；完整页面与下载尚未完成 |
| Pixiv | 搜索、推荐、关注、排行、收藏和详情 Core API 已接入；完整阅读与下载尚未完成 |
| Android平台存储拆分 | 代码已落地，待覆盖升级、清除缓存等真机验收，详见`TODO.md` |

## 项目结构

| 路径 | 职责 |
|---|---|
| `app/` | Flet UI、页面、主题、导航和应用装配 |
| `core/` | 当前已跑通的 Python Core，也是 Rust 行为参考实现 |
| `fvcore/` | 新的纯 Rust 单 crate Core，同时产出 library 与可执行程序 |
| `tests/` | 自动化和smoke测试 |
| `tmp/` | Booru、challenge和其他隔离实验，不进入正式应用 |
| `FletViewer/` | 桌面开发运行数据，打包时排除 |

依赖方向固定为：

```text
app -> core
```

`core/` 不依赖Flet或`app/`。

`fvcore` 的架构决策、现有 Python Core 分析、并发模型和迁移顺序见 [`FVCORE.md`](FVCORE.md)。

## Windows / Linux

需要Python 3.10或更高版本。

安装项目及桌面端依赖：

```bash
python -m pip install -e .
```

运行桌面应用：

```bash
python main.py
```

## Web 服务

Web 模式可以部署在 NAS 或其他常驻服务器，用户从桌面或移动浏览器远程访问同一个 FletViewer 实例。当前按可信环境中的单用户/共享服务器状态设计；在局域网外暴露前，应由反向代理提供 TLS、认证和访问控制。

安装 Web 可选依赖：

```bash
python -m pip install -e ".[web]"
```

然后使用 Flet 的标准 Web 启动命令运行：

```bash
flet run --web --recursive
```

如需固定端口：

```bash
flet run --web --recursive --port 8765
```

Web 模式中的 `Data`、`Cache`、`Downloads` 和 `Temp` 都位于服务器。浏览器不能直接访问服务器本地路径，也不能把浏览器设备目录当作 Core `Path`；远程文件交换必须走上传、下载或浏览器文件选择能力。

## Android APK

安装依赖并准备好 Android SDK 后，在项目根目录运行：

```bash
flet build apk
```

构建产物位于：

```text
build/apk/app-release.apk
```

侧载到已启用USB调试的Android设备：

```bash
adb install -r -d build/apk/app-release.apk
```

Flet 0.85.3要求Flutter 3.41.7。首次构建可由Flet自动安装匹配版本；Android SDK需要SDK 36、Build Tools 36.0.0，并接受对应SDK/NDK许可。

## 数据与缓存

当前桌面开发数据默认位于：

```text
FletViewer/
```

启动时会打印Data、Cache、Downloads和Temp的实际绝对路径。日志现写入`Temp/debug_log.md`。

平台存储四域拆分和桌面迁移代码已落地，但 Android 覆盖升级、清除缓存、清除数据和重启场景尚未完成真机验收。验收通过前不要把当前 Android 内部路径视为稳定格式；详细迁移设计和验收矩阵见`TODO.md`。

## 验证

运行当前自动化测试：

```bash
python -m unittest -v tests.test_async_image tests.test_image_fetcher
```

执行Python编译检查：

```bash
python -m compileall -q app core tests
```

## 文档

| 文件 | 内容 |
|---|---|
| `README.md` | 当前能力、运行和构建入口 |
| `TODO.md` | 当前决策、下一步及平台存储实施方案 |
| `AGENTS.md` | 长期架构边界、平台约束和协作规则 |
| `FVCORE.md` | 纯 Rust Core 架构决策、并发模型和迁移基线 |
| `docs/flet/index.md` | Flet 官方文档本地副本入口 |
| `tmp/README.md` | 隔离实验区说明 |
