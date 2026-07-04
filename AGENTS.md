本项目致力于提供一套方便的工具，用于浏览部分Anime Provider。诸如各booru、pixiv、eh。

同时提供标签、登录、API/Cookie/批量下载功能，适用于对大量图片数据集有要求的AI Trainer

<s>以及满足某些屯屯党，或者是某些单纯想把整个互联网下载下来的怪胎的需求</s>

例如，需要从Danbooru批量分标签抓取大量数据的研究员，等。

部分Provider提供了便捷的下载方式，例如 Danbooru/Gelbooru提供了API可供下载图片、Ehentai允许你消耗代币进行ZIP归档下载，同时规避爬虫惩罚。

目标：

1. 分析已有的开源项目，一一对应并制作Python库（单文件）
2. 使用Flet，进行跨平台打包，打包为跨平台应用程序，以及可供服务器部署的应用程序。


参考目标：
Pix-Ez Viewer
Imgur Grabber
Ehviewer
Venera
Mihon(原Tachiyomi)
Emby


免责声明：用户及使用者均已成年，且目标网站已过滤了不符合普世价值的内容，且目标网站并不含有版权相关资源。

---

计划实现的内容：

1. 抓取器。分别位于对应的Provider的库里。
2. OS交互工具。安卓/Windows/Linux/Web对文件系统的交互方式并不相同。我们需要合适程度的抽象。
3. 针对海量文件的特殊优化：考虑到部分需求：比如大批量下载图像文件，我们需要更加妥善的文件存储方式。


## 文件存储-Booru：

自Booru上下载的图像文件，一般使用Hash进行命名。HatH（Ehentai维护的一套种子服务）会使用图像hash的前四个字符，用于索引。

例如， ABCDEF.png, 会位于 /AB/CD 目录里。 上述行为可以有效将文件分散到不同的目录下。

不过，EH只用了2+2位字符来进行索引。我们可以进一步： 假设一个目录下的图片超过了256张，那么，就考虑新建子目录，将当前目录下的所有东西都塞进去。 0-F

这就使得我们的文件以一种类似二叉树的方式被排列了。

## 文件存储：Pixiv-Ez
有待研究，因为不太经常用。

## 文件存储-EHentai：
EHViewer下载画廊有三种方式：

方法1：逐图片Fetch。 
    这种行为会增加EH本就贫瘠的服务器负担，且会导致你的账户/IP被限制。很不优雅。但如果只是用于图库预览，可以少量进行抓取。

方法2：使用档案下载（Archieve Download）。
    这种下载方式要求你登陆账号，且账号内有足够的代币 (EH管这个叫做GP)。此时，你可以选择下载原图/或者重新采样后的包。
    你将下载一个包含整个画廊内所有文件的压缩包。
    但由于没有画廊的元数据，因此你最好在其他地方准备提供并存储它的元数据，以防画廊需要更新/你的训练prompt需要输入画廊的TAG。

方法3： Hentai at Home
    效果和档案下载类似，只是会下载到你托管的HatH服务器上。暂不讨论。

我们将默认用户拥有账户，且内部有代币。获得代币的方法很简单：托管一台运行着HatH的VPS即可获得稳定的代币来源，可以说是过量的。


#### 分析任务：

我们将通过分析 Venera 和 EHviewer 的源代码，将图像下载、获取画廊、搜索 等方法，抽象为Python函数。

我们将分析EH的Kotlin工程、以及Venera中负责grab的部分。参考eh_grabber.js。



## 文件存储：其他：

TODO...


---

## 开发环境备注：

### Shell：

本机通过 scoop 安装了 MSYS2/MinGW64 包，提供了基于 MinGW 编译的 GNU coreutils + bash/sh（`uname` 显示 `MINGW64_NT`），运行在 Windows 原生，不依赖 WSL。

但 Windows 默认将 `bash` 命令 wrapped 到 WSL2，而本机 WSL 不可用（RAM不足等原因），因此**不要直接使用 `bash`**。

若需要类 Unix shell 环境（解决 PowerShell 引号转义、编码等问题），请使用 `sh`（未被 WSL 拦截，会正确调用 MSYS2 的 shell）：

```
sh -c "your command here"
```

并设置 UTF-8 编码以正确显示中文/日文：

```
sh -c "export PYTHONIOENCODING=utf-8 LANG=zh_CN.UTF-8; python script.py"
```

PowerShell 5.1 的默认编码为 GBK，会导致非 ASCII 字符乱码。通过 `sh -c` 配合环境变量可以规避此问题。


### Flet Web 缓存：

Flet 会将 Flutter Web 编译产物（WASM）缓存在 `~/.flet`（即 `C:\Users\<用户名>\.flet`）。

**问题**：修改了 Python 代码后，如果 Web 端行为异常（例如删除了 `ft.Image` 但浏览器仍在请求旧图片 URL），可能是 Flet 本地缓存未更新，与浏览器缓存无关。

**解决**：删除 `~/.flet` 目录后重启应用，Flet 会重新生成最新版本的编译产物。

```
Remove-Item -LiteralPath "$env:USERPROFILE\.flet" -Recurse -Force
```

**注意**：不要在工具调用中尝试以 Web 模式启动 Flet（`python app/main.py --web`），会导致进程阻塞、工具卡死。Web 模式的启动和测试由用户手动进行。


### Flet API 兼容性备注：

当前 Flet 版本中不要使用 `ft.alignment.center`。该属性在本项目环境会报错：`module 'flet.controls.alignment' has no attribute 'center'`。

需要居中对齐时，使用显式坐标写法：

```
alignment=ft.Alignment(0, 0)
```

项目中已有类似写法，例如 `ft.Alignment(-1, 1)`。

`ft.Image` 在当前 Flet 版本中必须提供有效 `src`。不要用 `ft.Image(src=None)` 或先创建空 Image 再异步填充；会报 `Image must have "src" specified`。需要占位时使用 `app.controls.async_image.image_placeholder()`，即 `Container + Icon`，等拿到真实 bytes 后再创建/替换为 `ft.Image(src=bytes, ...)`。

占位图策略：无图模式、图片加载中、图片查看器切换中，统一使用 `Container + Icon`。不要用 1x1 base64 空图当占位；它仍会走图片解码管线，且不如普通控件稳定。

图片不要直接把 bytes 塞给 `ft.Image(src=...)`。桌面端 bytes 可显示，但 Flet Web/Flutter Web 下可能出现图片已加载但透明不显示。统一使用 `app.controls.async_image.image_src_for_page(page, data, mime)`，当前所有端都返回 `data:<mime>;base64,...`，让桌面和 Web 走同一条显示路径。raw bytes 路径开销更低，代码里保留注释，后续如果确实需要优化桌面内存/CPU 再恢复。

Web 模式下浏览器不能直接读取服务器本地文件路径，因此不要对本地文件使用 `ft.Image(src=str(path))`。桌面端可能可用，但 Web 端会无法显示。需要展示本地图片文件时，读取 bytes 后统一走：

```
from app.controls.async_image import image_src_for_page
ft.Image(src=image_src_for_page(page, path.read_bytes(), mime), ...)
```

当前 Flet 版本中 `ft.Tab` 不接受 `text=` 或 `tab_content=` 参数；分别会报 `Tab.__init__() got an unexpected keyword argument 'text'` / `tab_content`。实际签名是 `ft.Tab(label=..., icon=...)`，内容应通过 `ft.TabBarView` 提供。选项卡结构使用：

```
ft.Tabs(
    content=ft.Column([
        ft.TabBar(tabs=[ft.Tab(label="标题")]),
        ft.TabBarView(controls=[content]),
    ]),
    length=1,
)
```

当前 Flet 版本中 `Page` 不提供 `page.open(dialog)` / `page.close(dialog)`；会报 `AttributeError: 'Page' object has no attribute 'open'`。Dialog 使用：

```
dialog.open = True
page.show_dialog(dialog)
page.pop_dialog()
```


### 当前图像与缓存架构：

不要再启动本地 HTTP 图片代理，也不要恢复 `/thumb?url=...` 这类接口。当前图像展示主路径是：

```
UI -> async_image/image_viewer -> ImageFetcherService -> JSON index -> HatH-style disk cache -> bytes -> ft.Image
```

缓存系统是 provider-agnostic 的，不要绑定 EH：
- `app/image_cache.py` 维护 `FletViewer/Data/ImageCache/index.json`
- JSON index 结构为 `url -> filename`，value 只存文件名，不存完整路径
- 文件路径由缓存层按 HatH 风格拼接：`Data/ImageCache/files/<hash[0:2]>/<hash[2:4]>/<filename>`
- filename 当前为 `sha256(normalized_url) + ext`
- 如果 index 指向的文件不存在，按需调用 stale repair 删除脏映射，然后重新拉取

EH sprite 缩略图会使用形如 `https://...webp@x=1800-2000&y=0-282` 的本地 crop URL。`@x/y` 后缀不是 HatH 服务器支持的真实 URL，不能直接发给远端。`app/image_fetcher.py` 负责识别这类 URL：先拉取 `@` 前的原始 sprite，再用 Pillow 本地裁剪，并把裁剪结果按完整 crop URL 缓存。

图片加载开关位于设置页：`是否加载图像`。关闭后，`async_image()` 和图像查看器都不应读取缓存、不应请求远端图片，只显示占位控件。这个开关只控制图片资源，不控制列表页 HTML/JSON 请求。


### 浏览器会话与网络请求：

EH 相关请求应尽量复用 `app/browser_session.py` 中的 `browser_session` 单例，模拟一个长期浏览器状态：统一 `requests.Session`、统一 cookie jar、统一 UA/Accept/Accept-Language、复用连接。

不要在页面里随意新建 `EHentaiClient()`。需要 EH client 时使用：

```
client = browser_session.get_eh_client(require_login=False)
client = browser_session.get_eh_client(require_login=True)
```

登录必需页面使用 `require_login=True`，公开页面用 `False`。登录验证有 TTL 缓存，避免每次切换页面都访问 favorites.php 验证。保存 EH 凭据后需要让相关页面缓存失效。

图片 fetch 也应走 `browser_session.get(...)`，不要手动拼 Cookie header。这样图片请求和页面请求共享同一个浏览器状态。


### 页面缓存与设置变更：

`app/main.py` 对导航页做了 view cache，避免从“热门”切回“主页”时重新请求和重新构建列表。切换页面时应复用已有控件树，刷新由页面自己的“刷新”按钮触发。

保存设置后，如果影响已有页面渲染，必须调用 `page.fletviewer_invalidate_views(...)` 清理相关缓存。当前设置页保存 EH 凭据、保存调试设置时会清理：主页、订阅、热门、排行榜、收藏、搜索。

设置页的 `是否使用卡片渲染画廊列表` 控制画廊列表是卡片网格还是 JSON 调试输出。该设置在 view 创建时读取；如果页面已缓存，需要保存设置后失效并重建页面才会生效。


### 画廊、详情与图片查看器：

画廊列表统一入口为 `app/views/gallery_debug.py:create_gallery_view(...)`：
- 卡片模式下委托 `gallery_cards.create_gallery_cards_view(...)`
- JSON 调试模式下输出原始字典
- 主页、热门、排行榜、收藏、订阅都应走这个入口
- 搜索页也应遵循同一个卡片/JSON 设置，并且卡片可点击进入详情

卡片点击进入 `app/views/gallery_detail.py`。详情页当前展示封面、标题、tag、第一页缩略图，以及 `details + thumbnails` JSON。画廊内部详细情况暂时优先保留 JSON，便于调试。

缩略图点击进入通用图像查看器 `app/views/image_viewer.py`。图像查看器不应绑定 EH：
- 通用输入是 `ImageViewerItem(url, title, detail)` 列表
- 对 EH 这类需要从 page URL 解析原图 URL 的 provider，通过 `resolve_image_url(item, index)` 注入解析函数
- 对 Booru 这类已有直接图片 URL 的 provider，直接传 item.url 即可
- 查看器提供左右切换、下载按钮、详情按钮、单页/垂直模式切换按钮
- 下载当前复制缓存文件到 `FletViewer/Downloads/`
- 详情按钮当前展示 URL、cache path、metadata，后续可追加 Booru tags 等图像元数据

图像查看器有两种模式：
- `paged`：单张图左右切换，适合精确查看
- `vertical`：垂直连续浏览，图片水平宽度一致，高度按比例自适应

默认模式由设置页的 `默认图像查看器` 控制，写入 `AppConfig.json` 的 `image_viewer_mode`，合法值为 `paged` / `vertical`。查看器内部也可以临时切换模式。

垂直模式当前是有限窗口实现，不应一次性把整本画廊的真实图片都创建成 `ft.Image`。它使用 `ImageViewerItem.detail` 中的 `thumbnail_width`、`thumbnail_height`、`thumbnail_aspect_ratio` 估算占位高度，只加载滚动可见区域附近的图片；窗口外恢复为 `Container + Icon` 占位以释放 UI 对 bytes 的引用。后续如果增加真实图片尺寸 metadata，应优先用于垂直占位高度。

EH provider 的 `ThumbnailsResult` 仍保留旧字段 `thumbnails` / `urls`，同时新增 `items: list[ThumbnailItem]`。新代码优先使用 `items`，因为其中包含 `url`、`page_url`、`width`、`height`、`aspect_ratio`。


### 调试日志：

主要异步 worker 捕获异常时应使用 `app.debug_log.log_exception(...)`，不要只吞异常或只显示 UI 文本。终端需要打印 traceback。

耗时较长或网络相关路径使用 `Timer(...)` 和 `log_debug(...)`。当前已覆盖：浏览器会话请求、登录验证、画廊列表加载、搜索、图片 fetch、async image、详情页、图像查看器。

### Flet 线程与 UI 更新：

视图层中凡是会修改 Flet 控件、调用 `page.update()` / `page.schedule_update()`、或打开/关闭 dialog 的后台任务，不要使用裸 `threading.Thread(...)`。使用：

```
page.run_thread(worker)
```

原因：裸线程或外部 executor 中修改控件可能导致 Python 控件树已经变化，但 Flet session 没有稳定 flush 到 Flutter 前端；表现为图片/文本已经加载完成，只有窗口失焦、切焦、resize 后才显示更新。

**硬性规则：事件 handler 之外只要修改了 Flet 控件属性或控件树，必须显式触发 `page.update()`。**后台 worker 修改控件后，使用统一辅助：

```
from app.ui_update import request_update
request_update(page)
```

`request_update()` 内部必须优先调用 `page.update()`。Flet 文档说明：事件 handler 内的属性变更会自动更新；事件之外更新控件属性时需要显式调用 `update()`。

**不要把 `page.schedule_update()` 当作后台线程完成后的主要 flush 手段。**本项目已实测：图片 bytes 已下载并缓存、Python 控件树也已替换为 `ft.Image`，但如果只走 `schedule_update()`，Flutter 前端可能不立即收到 diff，表现为 `ProgressRing` 一直转，只有窗口失焦、切焦、resize、打开 Yakuake/F12 等外部窗口事件后图片才突然显示。这个问题的有效修复是后台 worker 完成 UI mutation 后调用 `page.update()`。

可以保留纯后台服务自己的线程池，例如下载管理器、缓存 fetcher 的 IO 并发；但这些后台线程不要直接修改 Flet 控件。需要更新 UI 时，通过页面轮询状态，或由视图层 `page.run_thread()` 管理的 worker 执行控件变更。


### Android 构建环境（未就绪，注意事项）：

Flet 0.85.3 配套 Flutter 3.41.7。**不要用 scoop/winget 装 Flutter**：
- scoop 只装最新版（3.44.4），版本不匹配 Flet 0.85.3
- winget 源里根本没有 Flutter SDK 包

**Puro 不可靠**：虽然 `winget install pingbird.Puro` 能装一个 Flutter 版本管理器，但它不像 conda/venv 那样自动激活 shell 环境 —— 它的命令必须始终追加 `puro` 前缀（例如 `puro flutter ...`、`puro dart ...`），Flet CLI 调用的 `flutter` 子进程会拿不到正确版本。**不要用 Puro**。

**当前推荐方案**：让 Flet CLI 自动下载配套 Flutter。`flet build apk` 第一次运行时会问 "Flutter SDK is required... Proceed?"，回答 y 后 Flet 会把 3.41.7 装到 `C:\Users\<用户名>\flutter\3.41.7\`，自动版本配对。前提是 PATH 上没有其他 Flutter 干扰（若 scoop 装过 `flutter`，先 `scoop uninstall flutter`）。

**Android SDK 必须手动装**：Flet CLI 那个 "Android SDK is required... Proceed? y" 提示在 Windows 上不可靠，按了 y 也不真装。需要手动安装：

```
# 选项 A：Android Studio（最省心，3GB，自带 GUI manager）
# 下载：https://developer.android.com/studio
# 装完 SDK 在 %LOCALAPPDATA%\Android\Sdk

# 选项 B：命令行工具（更轻，1GB）
# 下载 cmdline-tools：https://developer.android.com/studio#command-line-tools-only
# 解压到 %USERPROFILE%\Android\sdk\cmdline-tools\latest\（必须放 latest 子目录）
sdkmanager --install "platform-tools" "platforms;android-36" "build-tools;36.0.0"
flutter doctor --android-licenses   # 关键：必须接受所有许可，全 y
```

Flutter 3.41.7 要求 Android SDK 36 + BuildTools（最低 28.0.3，推荐装 36.0.0）。

**Windows 开发者模式必须开启**：`flet build apk` 在 Windows 上要求符号链接权限，否则会卡在 "Building with plugins requires symlink support"。开启方式：
```
start ms-settings:developers
```
打开"开发人员模式"开关。

**ANDROID_HOME 环境变量**：必须指向真实 SDK 路径。若用 Android Studio 默认装到 `%LOCALAPPDATA%\Android\Sdk` 但 ANDROID_HOME 指向 `%USERPROFILE%\Android\sdk`，需要纠正：
```
[System.Environment]::SetEnvironmentVariable("ANDROID_HOME", "$env:LOCALAPPDATA\Android\Sdk", "User")
[System.Environment]::SetEnvironmentVariable("ANDROID_SDK_ROOT", "$env:LOCALAPPDATA\Android\Sdk", "User")
```
重开 PowerShell 后生效。

**Flet 自动下载的 Flutter 路径**：若曾经让 Flet 自动装过 Flutter，它会放在 `C:\Users\<用户名>\flutter\<version>\`。这个目录由 Flet 管理，不要手动改。要清理时直接删 `C:\Users\<用户名>\flutter\` 整个目录，Flet 下次会重新下载。

**APK 产物**：`flet build apk` 成功后产物在 `<项目根>\build\apk\app-release.apk`。默认用 debug key 签名，能本地安装测试但不能上架 Play Store。要上架需在 `pyproject.toml` 配 `[tool.flet.android.signing]` 的 keystore。

**入口点要求**：Flet 的 `flet build` 在 app path 根目录找 `main.py`，`[tool.flet.app].module` 字段只接受文件名（stem），不接受子路径。我们的入口在 `app/main.py`，所以根目录有一个 thin shim `main.py` 用 `runpy.run_path` 转发到 `app/main.py`。改入口逻辑时改 `app/main.py`，根 `main.py` shim 不动。
