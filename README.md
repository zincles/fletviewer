# FletViewer

FletViewer 是使用 Flet 构建的跨平台 Anime Provider 浏览、阅读和下载工具。目前正式主线以 EHentai 为主，Booru、Pixiv 和 challenge backend 尚在实验或预留阶段。

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
| Booru下载 | 页面预留，Provider尚未正式接入 |
| Pixiv下载 | 页面预留，Provider尚未正式接入 |
| Android平台存储拆分 | 下一项工作，详见`TODO.md` |

## 项目结构

| 路径 | 职责 |
|---|---|
| `app/` | Flet UI、页面、主题、导航和应用装配 |
| `core/` | Provider、网络、缓存、数据库、图片和下载核心 |
| `tests/` | 自动化和smoke测试 |
| `tmp/` | Booru、challenge和其他隔离实验，不进入正式应用 |
| `FletViewer/` | 桌面开发运行数据，打包时排除 |

依赖方向固定为：

```text
app -> core
```

`core/` 不依赖Flet或`app/`。

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

安装 Web 可选依赖：

```bash
python -m pip install -e ".[web]"
```

然后运行：

```bash
python scripts/dev_web.py
```

默认地址：

```text
http://localhost:8765
```

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

Android持久数据、系统缓存和下载目录的正式拆分尚未完成。不要把当前Android内部路径视为稳定格式；详细迁移设计和验收矩阵见`TODO.md`。

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
| `docs/flet/index.md` | Flet 官方文档本地副本入口 |
| `tmp/README.md` | 隔离实验区说明 |
