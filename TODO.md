# TODO

- **当前首要目标：全面重写纯 Rust、单 crate、可独立运行且可嵌入的 `fvcore`，最终完整替代现有 Python `core/`。**
- `fvcore` 同一 Cargo package 同时产出 library 与 executable；library 实现完整核心方法，executable 读取配置并运行同一 Runtime，不预建 provider/server/adapter 子 crate。
- 当前 Python `core/` 不另行打包，仅作为重写期间的只读行为和 fixture 参考；它不是长期兼容目标，完整决策见 `FVCORE.md`。
- 最终迁移范围覆盖 Python Core 的全部正式业务能力；实现仍按可独立验收的纵向批次推进，避免一次同时写多个未闭环子系统。
- HTTP 控制面始终编译进标准 executable，由 args/配置决定是否启用监听；它与嵌入 API 共用同一 Runtime 和业务方法。
- 配置、统一 Runtime、command/snapshot/event/resource、Provider session generation、有界 operation、内存优先图像链路、EH 持久 Archive、本地 ZIP 阅读/删除/导出、`redb` 画廊登记、全量健康扫描和脱敏配置展示已建立；当前继续完整图像缓存监管。
- Python/Rust 迁移期间禁止双写同一 SQLite、Cache、Downloads 或本地画廊。
- 已终止独立 Flutter UI 与 Flutter + Serious Python bridge 路线；Flet 是当前正式产品 UI，但未来可由其他前端通过 `fvcore` library 或 adapter 取代。
- 已完成的 `core/`、Runtime、Facade 和 JSON-safe DTO 继续作为稳定业务边界，避免页面直接持有 Provider client、网络响应、数据库连接和任务内部对象。
- Flet 缺失的原生能力只通过带 Python wrapper 的小型 Flutter extension 补齐；extension 不得进入 `core/`，且必须为 Web/不支持平台提供 fallback、禁用状态或服务器侧实现。
- UX 优先级切到整体体验重设计：主题基础采用 Material 3，颜色走设置驱动的自适应/手动色种，后续页面只使用语义色和主题入口。
- Flet 产品线后续重做主浏览体验的信息架构：阅读首页、搜索、详情页、查看器、下载/本地画廊之间保持连续动线；`fvcore` 已提供不暴露 Archive 路径的本地 ZIP 分页与单页 resource，后续前端只包装该公开语义。
- Flet 画廊列表仍需补回自动加载下一页，并保留手动翻页、失败重试和当前页反馈；Rust WebUI 的 EH seek cursor 手动分页已经完成，不等同于 Flet 产品分页验收。
- 存储可靠性完成后增加受限的“存储浏览器”页面：仅浏览 Data/Cache/Downloads/Temp 四域，支持路径、大小、mtime、JSON/文本预览、ZIP 文件列表、缓存/临时文件维护和导出诊断；不得允许路径逃逸，Android 外部文件继续通过 FilePicker/SAF 交换，Web 端明确展示的是服务器文件而非浏览器设备文件。

## 当前产品与未来 Core

- 当前 Flet 同时承担桌面、Android 和 Web UI；Web 可部署到 NAS/server，让用户通过浏览器远程使用同一应用实例。
- `app/` 是当前 Flet 前端和 composition root，负责页面、主题、导航、平台能力、路径注入和 UI 更新；不再以“逐步被独立 Flutter UI 替换”为目标。
- 当前 `core/` 在过渡期继续独占尚未切换的真实存储；每项能力验收后将所有权切至 Rust，最终 Python Core 完整退役。
- 新 `fvcore/` 是纯 Rust 单 crate Core，不依赖 Flet、Flutter、Python、Bevy 或具体前端；可执行入口和嵌入 API 共用同一 Runtime 与业务实现。
- Web/NAS 中的配置、Cookie、缓存、下载和本地画廊均属于服务器，不代表浏览器设备本地状态；文件交换使用上传、下载或文件选择流程。
- 当前 Web/NAS 首先面向可信网络中的单用户或共享实例。调试 WebUI 默认允许 LAN 访问且配置页按测试阶段要求明文回显/持久化 Provider secret；若开放到不可信网络，必须先明确用户隔离、凭据所有权和任务可见性，并由反向代理提供 TLS、认证和访问控制。
- Flutter extension 仅用于 Flet API 无法可靠覆盖的原生能力，例如未来的大文件 SAF 流或特定系统集成；优先使用 Flet 内建跨平台 API，不为普通业务逻辑编写 Dart 副本。
- 原 Flutter + Serious Python 路线中的独立 shell、Python package 和图片 bridge 均不再是项目任务；未来控制传输或前端只包装 `fvcore` 的公开 command/snapshot/event/resource，不复制业务。

## fvcore 下一批

| 状态 | 工作 | 验收点 |
|---|---|---|
| 已完成 | 单 crate library/executable、基础依赖与检查 | format、全部 target check/test、clippy `-D warnings` 通过 |
| 已完成 | 严格配置、稳定错误、Runtime ID、snapshot | Runtime 只读取 executable 同级必需 `config.json`，`run/web` 分配资源前完整验证；`run` 不挂载 WebUI，`web` 强制启用 listener + WebUI；无参数 `check-config/create-config` 与运行命令统一使用 executable 同级配置，唯一 staging 安全生成，默认拒绝覆盖，显式 `--override` 通过锁和恢复副本重置默认值并恢复中断事务 |
| 已完成 | `CoreRuntime`、`CoreHandle` 与集成 HTTP | 有界命令队列、协作关闭、health/status 路由通过真实 loopback 测试 |
| 已完成 | 四域存储、实例锁与 `redb` schema v2 | v1 原地迁移；第二 Runtime 被拒绝，关闭后可重新取得同一 Data 域；画廊登记只保存 ID 与受管直接子目录名 |
| 已完成 | Command/Event/Operation 模型 | 状态机、deadline、取消、overload、revision、event cursor/SSE 和 fake operation 测试 |
| 已完成 | Provider profile/session generation 与共享网络 Foundation | Cookie 环境注入、UA、代理、连接池、受限 redirect、响应上限和旧 generation 自然释放 |
| 已完成 | Provider 限流与两大 Booru 查询闭环 | Generation 级并发/启动间隔；Danbooru JSON 与 Gelbooru JSON DAPI 搜索、详情、fixture、稳定错误和 HTTP 路由 |
| 已完成 | EH 浏览、指定页原图、持久 Archive 与本地画廊消费 | EH 主页/详情/缩略图、标准 E-Hentai 专用 `api.e-hentai.org/api.php`、showkey/mpvkey 指定页共享 ImageService fetch；Original/Resample 显式付费提交、签名 URL 隔离、单并发流式 ZIP、Range 续传、`cost_unknown` 防重放；Archive revision 接入统一 event journal；完成 ZIP 通过 staging 幂等提交为本地画廊并提取安全封面；H@H 仅展示 |
| 已完成 | 已知 MD5 的 Booru original Fetch 主链路 | Danbooru/Gelbooru metadata -> memory -> disk -> shared network -> length/magic/MD5 验证 -> immutable resource；operation 进度、独立取消和 HTTP bytes 已贯通 |
| 已完成 | 可选内嵌调试 WebUI | 无 Node.js 的服务端渲染 Dashboard、EH 主页/详情/缩略图、Booru 搜索/详情、Pixiv 详情、operation 列表/详情、Fetch/取消和结果图片；Dashboard 和活动 operation 页面按状态自动刷新，listener 与 WebUI 可分别开关 |
| 已完成 | 未知 MD5 alias 与 Pixiv 详情主链路 | `ResourceKey -> ContentMd5` 持久 alias、有界异步 cache writer、关闭 drain、Pixiv AJAX 详情/多页 metadata、Referer 与 original page operation |
| 已完成 | EH Gallery 详情与缩略图 | 从 `/ui/eh` 条目进入详情；固定标题、标签、上传者、页数、评分、评论、版本链和缩略图 fixture；嵌入 API、JSON 和 WebUI 共用同一 EH profile generation |
| 已完成 | EH 指定页原图阅读链路 | 解析 showkey/mpvkey 和单页 image key，按需获取指定页原图并接入 `ImageService`、operation、resource API 和 WebUI；不将逐页 fetch 用作批量下载 |
| 已完成 | EH Archive 提交与流式持久下载 | 提交 Original/Resample、解析并隔离签名 URL，记录获取时间、86400 秒有效期和最大 IP 数 2；流式写入 Downloads、支持取消/Range 恢复，`submitting` 崩溃恢复为 `cost_unknown` 且不自动重放 |
| 已完成 | EH Archive 本地画廊消费 | 读取完成任务，按 `[gid][token] title` 创建本地画廊目录，移动并保留原始文件名和 ZIP bytes，写 `gallery.json`、提取首张安全封面，按 task ID 幂等启动恢复并记录 consumed/consume_error |
| 已完成 | 确定性 ComicInfo 派生 | 安全 ZIP 图片 member 使用无整数溢出的稳定自然排序；旁置 `ComicInfo.xml` 只由唯一原 ZIP 与 `gallery.json` 生成，消费时自动创建，也可通过 Runtime/HTTP 删除和逐字节一致地重建 |
| 已完成 | 本地 ZIP 画廊阅读 API | 稳定 gallery/page ID、自然排序和分页 member snapshot、有界单页解压与 magic MIME；规范化重复名、隐藏/逃逸路径、member 数、单页和总声明大小均受限；`CoreHandle`、JSON metadata、二进制 resource 和本地阅读 WebUI 已贯通，公开结果不含 Archive Path/文件名 |
| 已完成 | 本地画廊统一 resource | 封面和 ZIP 页面共用带 kind 的 resource descriptor、图像预算、并发上限、magic MIME 和二进制安全响应；封面路径限制在画廊目录内，WebUI 列表和详情直接消费 resource URL |
| 已完成 | 本地画廊显式确认删除 | 删除必须先预检并取得五分钟一次性令牌；令牌绑定直接普通文件名与大小清单，文件集合或大小变化即拒绝；阅读/旁置写入/消费/删除共用读写占用，提交先持久化确认清单并隐藏目录，再清除 Archive task 路径；启动仅按 unchanged 清单恢复中断删除，WebUI 必须二次提交确认 |
| 已完成 | 本地画廊导出语义 | `LocalGalleryExport` 固定 64 KiB 有界块、最多两个并发导出并持有共享画廊占用；嵌入 API、HTTP 附件与 WebUI 复用同一流，公开 descriptor 不含服务器 Path，平台嵌入者负责目标文件选择与写入 |
| 已完成 | 本地数据盘点与配置 WebUI | inventory 分类已登记健康/损坏、未登记可导入、格式无效，检查全部 ZIP 页面与 sidecar；显式导入只收 gallery ID；当前生效配置 snapshot 和页面已脱敏 secret、代理值及 URL 凭据 |
| 下一步 | 完整图像缓存监管 | 全局 chunk 级在途预算、Cache snapshot/维护、alias schema/version、staging 清理和更多格式 fixture |
| 后续 | Provider 纵向迁移 | 补齐 EH 搜索/feed、Pixiv 搜索/推荐/关注/收藏/排行、Gelbooru-style/Moebooru 协议族及各 Provider 正式下载能力，最终覆盖 Python Core |

## Core 独立化进度

### 重构进度表

| 阶段 | 状态 | 当前产物 | 下一验收点 |
|---|---|---|---|
| 1. Core 依赖边界 | 已完成 | `app -> core`；`core/` 无 `app`/`flet` import | 持续由依赖扫描守护 |
| 2. 搜索/Feed API | 已完成 | `BackendFacade`、JSON-safe `MediaItemDTO`/`PageResultDTO`、稳定错误 | 后续 Provider 继续复用同一契约 |
| 3. 独立 Runtime | 已完成 | `BackendRuntime` 拥有共享网络会话和 Provider client registry | 持续验证初始化、关闭和恢复 |
| 4. 后端配置契约 | 已完成 | `core/config/` 模型、Repository Protocol、内存仓库、旧 JSON adapter | 继续由 Flet adapter 注入平台存储 |
| 5. 详情 API | API 已完成 | `MediaDetailDTO`、评论/关系 DTO、三 Provider 详情 Facade；EH metadata 已切换 | 图片/Archive 下沉后移除页面最后的 client 访问 |
| 6. EH Archive API | 已完成 | Core Archive 服务、option/task DTO、Runtime manager port；Flet 只提交 archive ID | 后续复用通用任务查询 DTO |
| 7. 下载任务 API | 已完成 | 丰富 `DownloadTaskDTO`、任务 service、Facade 操作；Flet 下载页只消费 DTO | 后续补速度/ETA 和本地画廊跳转字段 |
| 8. 图片任务 API | API 已完成 | `ImageTaskDTO`/result DTO、轮询命令、Runtime 注入；Flet 保留高效本地 adapter | 按 Flet 桌面/Android/Web 性能继续优化 |
| 9. 本地画廊/历史 API | 已完成 | DTO、封面/ZIP 页资源服务、历史 service；Flet 页面只用 Facade | 后续补本地画廊删除/导出命令 |
| 10. Runtime 生命周期 | 已完成 | 幂等 initialize/shutdown、失败重试、executor 重建；Flet 统一装配/退出 | Core-only Runtime 可统一启动/关闭 |
| 11. Flet 产品化 | 进行中 | Core API 已由 Flet 消费，Flet 继续作为正式 UI | 重做主浏览动线、补回分页并完成 Web/NAS 验收 |

### 持续边界

- Flet 页面优先调用稳定 Backend Facade，不直接持有 `EHentaiClient`、`PixivWebClient`、Booru client、`requests.Response`、线程事件或 SQLite 连接。
- `core/` 必须能在不 import `app`、`flet` 或 Flutter extension 包的情况下独立构造和真实调用；平台通过普通回调、Protocol、路径和配置注入。
- EH、Pixiv、Booru 只统一应用服务入口和最小公共 DTO，不强行统一底层协议；provider-specific metadata 必须保留。
- Python Runtime 独占网络会话、Cookie、SQLite、缓存和下载任务；Flet 页面及 Flutter extension 不并行直接操作这些资源。
- 长任务统一为 `start/status/cancel/retry/list` 和稳定任务 DTO；页面不得依赖 manager 内部 Future、线程对象或磁盘实现细节。
- UI 可见错误使用稳定的 `code/message/provider/retryable`，页面不解析中文异常文本决定业务状态。
- Flutter extension 通过 Python wrapper 和窄接口接入 `app/`；Dart 端不得复制 Provider、缓存、下载或数据库业务。

### 已完成基线

- `core/` 已无 `app`/`flet` 反向 import；完整扫描与测试已验证。
- 已新增 `core/api/`：
  - `BackendFacade`
  - `MediaItemDTO`、`PageResultDTO`、`MediaDetailDTO`、评论/关系 DTO
  - `BackendError` 与稳定错误 payload
  - `to_dict()` 结果可直接 JSON 序列化，不泄漏 Provider `raw`
- 已新增 `core/runtime/BackendRuntime`，独立拥有：
  - `BrowserSessionService`
  - EH client 创建
  - Pixiv/Booru client registry、复用、配置签名和失效
  - `BackendFacade`
- `BackendRuntime` 只依赖四个配置 loader 以及可选日志/计时器；不知道配置文件位置和 UI 框架。
- 已用仅 import `core.runtime` 的真实脚本验证 EH、Pixiv、Safebooru 搜索和 JSON-safe 输出。
- Flet 已通过 Facade 调用 EH 搜索、Pixiv 搜索/推荐/关注/排行/收藏及全部 Booru 搜索。
- `app/backend.py` 现在是 Flet composition root；`app/browser_session.py`、`app/pixiv_session.py`、`app/booru_session.py` 仅保留兼容 re-export。
- 已新增 `core/config/`：`BackendConfig`、EH/Pixiv/Booru/Proxy 配置 dataclass、`BackendConfigRepository` Protocol 和内存仓库。
- `app/backend_config.py` 将现有 `Data/config.json` schema 映射到 Core 配置模型，保存后端配置时保留主题、网格等 UI 偏好。
- 设置页通过 Runtime 保存 EH/Pixiv/Booru/Proxy 配置并失效 client，不再调用 Pixiv/Booru session 兼容模块。
- Backend Facade 已提供 EH/Pixiv/Booru 通用详情入口；Provider `raw` 不进入详情 DTO。
- EH 详情缓存 schema 已升级到 v3 并存储 `MediaDetailDTO`；旧 v2 Provider 对象缓存自动失效重拉。
- Flet EH 详情 metadata 网络读取已切到 Facade；缩略图、原图解析和 Archive 仍暂时直接使用共享 client，分别在后续批次下沉。
- 已新增 UI-independent `EHArchiveService`、`ArchiveOptionDTO` 和 `TaskStartedDTO`；下载 manager 通过 Core Protocol/Runtime 注入。
- Flet Archive 页面只调用 `list_eh_archives()` / `start_eh_archive_download()`，不再组装 Referer、gid/token、有效期或 `tag_data`。
- 已新增丰富 `DownloadTaskDTO` 和 `DownloadTaskService`，保留任务进度、业务 gallery token、Archive、有效期、恢复能力、错误和时间字段。
- Flet 下载页只消费 DTO/Facade，不再 import manager、内部 `DownloadTask`、tag_data、下载 URL、headers 或磁盘路径。
- 已新增 `ImageTaskDTO`、`ImageResultDTO` 和 `ImageTaskService`，支持 `start/status/list/cancel/retry/result/remove`，公开结果不含 Future、订阅、Event 或本地 Path。
- Runtime 已可注入 image fetcher；禁图开关在 Core task 入口返回稳定 `images_disabled`，图片结果 DTO 保留 base64 形式用于 JSON-safe 调试和非本地调用。
- Flet 图片控件保留本地 Future/结果泵 adapter，以维持共享请求、最后订阅者取消、批量 UI 更新和防闪烁性能；该 adapter 属于 App 实现，不进入 Core 公开 API。
- 已新增本地画廊/历史 DTO 和 application service；封面、ZIP 页列表与受限单页解压均由 Core 按稳定 gallery ID 执行。
- Flet 本地画廊、ZIP 阅读器和历史页已通过 Facade 获取数据，不再直接扫描目录、读取 SQLite 或把 archive Path 放入页面状态。
- Runtime 统一管理下载、本地画廊和图片执行 service 生命周期；关闭不会触发懒 service 创建，图片 executor 关闭后可在同进程重建。
- Flet `main()` 只调用 `runtime.initialize()`，composition root 统一注册 `runtime.shutdown()`，不再由图片 adapter 单独注册退出回调。
- 当前自动测试基线：`200 tests passed`；测试中的失效 EH 封面 404 是允许失败的旧 smoke probe。

### 已完成批次：后端配置与凭据仓库

1. 已在 `core/config/` 定义 JSON-safe 后端配置模型，覆盖：
   - EH Cookie 与登录开关
   - Pixiv Cookie/User ID
   - Booru API 凭据
   - 代理 mode/URL
2. 已定义小型 `BackendConfigRepository` Protocol；Core Runtime 依赖该接口，不依赖 `app/storage.py`。
3. 已开始将当前混合配置拆为两类所有权：
   - 后端配置：Provider 凭据、代理、下载/缓存业务设置
   - UI 偏好：主题、颜色、网格、窗口、Flet 调试开关
4. 第一版继续兼容现有 `FletViewer/Data/config.json`，不迁移、不打印或丢失真实 Cookie；Flet adapter 负责旧 schema 映射。
5. 凭据保存后通过 Runtime 正式方法失效相关 client；设置页已不再 import Pixiv/Booru session 兼容函数。
6. 已覆盖内存仓库、旧 JSON adapter、默认值、UI 偏好保留、凭据更新和 client 重建测试；损坏 JSON 继续由现有 storage quarantine 测试覆盖。

### 已完成批次：详情 Facade

1. 已新增最小 `MediaDetailDTO`、`CommentDTO` 和 `RelatedMediaDTO`；公共字段 JSON-safe，Provider 差异位于受控 `metadata`。
2. `BackendFacade` 已增加 `get_media_detail` 以及 EH/Pixiv/Booru 专用详情方法，并继续输出稳定 `BackendError`。
3. EH 详情 metadata 已通过 Facade 获取并以 DTO 缓存；Pixiv/Booru 详情 API 已具备，但当前 Flet 尚无对应通用详情页面。
4. 已覆盖三 Provider 映射、评论/版本关系、图片 variants、provider-specific metadata、`raw` 隔离、JSON 序列化和错误码。
5. 未在本批迁移 Archive、缩略图和原图解析，因此 `gallery_detail.py` 仍会为这些职责访问共享 EH client；这是明确的后续边界，不属于详情 DTO 回退。

### 已完成批次：EH Archive 服务

1. Core 已定义 JSON-safe `ArchiveOptionDTO`、`TaskStartedDTO` 和 `EHArchiveService`；不返回 Provider `Archive`、manager task 或 `Path`。
2. Runtime 通过小型 `ArchiveDownloadManager` Protocol 延迟注入下载 manager；Core-only 可使用自有实现或 fake，不依赖 App。
3. `list_eh_archives` 和 `start_eh_archive_download` 已进入 Facade；Flet 只展示 DTO 并提交 gallery URL/archive ID。
4. 保留原始 ZIP、共享 browser session、Referer、有效期 86400 秒、最大 IP 数 2、详情/缩略图快照和现有本地画廊消费契约。
5. 已覆盖 Core-only 列表、H@H 排除、任务 metadata、未知选项、登录错误、DTO JSON 序列化和 Runtime manager 注入测试。

### 已完成批次：下载任务 API

1. 已定义 JSON-safe `DownloadTaskDTO`，包含 task ID、Provider、kind、状态、进度、标题、错误、时间、恢复能力、media 和 expiry。
2. 业务 gallery token、gallery URL、gid 和 Archive 字段明确保留；只隔离签名下载 URL、HTTP headers/Cookie、内部路径、ETag、Future 和 manager 对象。
3. Core service/Facade 已提供 `list_download_tasks`、`get_download_task`、`cancel_download_task`、`retry_download_task`、`delete_download_task`。
4. 未知 task 使用稳定 `task_not_found`；状态继续兼容 `queued/running/completed/failed/cancelled/consumed`。
5. `app/views/downloads.py` 已只消费 DTO/Facade，现有刷新、进度、取消、重试和删除交互保持。
6. 已覆盖 JSON 序列化、丰富业务字段、执行秘密隔离、历史 EH task provider 推导、状态命令和未知 task。

### 已完成批次：图片任务 API 基础

1. 已盘点缩略图和查看器两类语义；缩略图共享同 URL 请求并按订阅取消，查看器原图支持独立任务和协作取消，未强行抹平两者。
2. 已定义 JSON-safe `ImageTaskDTO`/`ImageResultDTO`，提供 `start/status/list/cancel/retry/result/remove`。
3. 图片结果目前使用 base64，包含 MIME、byte length 和 cache 命中；不暴露 cache Path、Future、Event 或订阅对象。
4. 相同 URL 的多个 task ID 共享底层请求；单个 task 取消立即显示 cancelled，仅最后消费者取消时停止底层请求。
5. Runtime 已支持 image fetcher 与禁图策略注入，Core-only fake 验证不依赖 App/Flet。
6. Flet 本地 adapter 继续使用 Future callback + result pump，以维持共享请求、批量更新、防闪烁和低页面 diff；DTO 轮询 API 保留给调试、远程 API 或未来非 UI 消费者。

### 已完成批次：本地画廊与历史 API

1. 已定义 JSON-safe `LocalGalleryDTO`、`LocalGalleryPageDTO`、`LocalResourceDTO` 和 `HistoryItemDTO`；内部 archive/cover Path 不进入 DTO。
2. Core service 通过稳定 `provider:gid:token` ID 提供本地画廊列表/详情、封面、ZIP 页列表和受限单页解压。
3. ZIP 继续限制 member 数量、单页/总大小、重复文件名、隐藏文件和路径逃逸；页面只提交 gallery ID/member ID。
4. 历史 service 输出嵌套 `MediaItemDTO`，支持 record/list/clear，并兼容已有 `Comic` metadata 快照和 GID 去重。
5. Runtime 已支持 manager/repository port 注入；Flet 本地画廊、ZIP 阅读器和历史页均已迁移到 Facade。
6. 本批未增加危险的本地画廊删除；删除/导出需在后续定义确认、任务占用和平台文件交换语义后加入。

### 已完成批次：Runtime 完整生命周期与独立装配

1. `BackendRuntime.initialize()` 按下载、本地画廊顺序幂等启动；初始化异常不标记成功，允许调用方修复后重试。
2. `BackendRuntime.shutdown()` 关闭图片/下载 executor、清理 Provider client，并允许同进程再次 initialize。
3. Flet 图片 adapter 关闭时只处理已创建实例，不因退出创建缓存目录或线程池；关闭后释放 fetcher/coordinator 以支持完整重建。
4. Flet `main()` 已改为统一调用 Runtime 初始化，composition root 统一注册退出回调；本地画廊仍通过模块 import 注册现有 manager port。
5. Runtime lifecycle 测试覆盖幂等启动、失败重试、反序关闭、参数传递和重启；LazyProxy 测试覆盖无副作用检查、释放和重建。
6. 具体 Core service factory 暂不固化；继续由 Flet composition root 根据平台存储路径、日志/通知 callback 和运行模式装配。

### 下一批：Flet 主浏览体验与 Web/NAS

1. 重做首页、搜索、详情、查看器、下载和本地画廊之间的信息架构与返回路径，优先减少重复入口和上下文丢失。
2. 为统一画廊列表补回自动加载下一页，并保留手动翻页、加载失败重试和当前页反馈。
3. 验证同一 Flet 页面在桌面、Android 和 Web 的布局、导航、图片加载与任务状态更新，不为 Web 建第二套前端。
4. 建立 NAS/server smoke：启动、远程浏览、EH 登录、搜索、详情、阅读、下载、本地画廊、重启恢复和服务器文件语义。
5. 明确 Web 单用户/共享实例限制；在实现用户隔离前，不把带共享 Cookie 和任务状态的实例直接暴露到不可信网络。
6. 完成 Android 存储覆盖升级和“清除缓存”真机矩阵，再开始依赖平台文件能力的新功能。

### 后续批次

1. **Provider 产品化**：补齐 Pixiv/Booru 通用详情、阅读和适合各 Provider 协议的下载能力，不强行复用 EH Archive 模型。
2. **平台能力**：优先使用 Flet 内建 API；仅在真实缺口经过桌面/Android/Web 评估后增加带 Python wrapper 的小型 Flutter extension。
3. **Web/NAS 运维**：补充持久路径配置、反向代理示例、诊断导出、备份恢复和明确的安全部署边界。

### 下次开始顺序

1. 运行当前 Flet 桌面 smoke、完整测试、`compileall`、`git diff --check` 和 `core -> app/flet` 依赖扫描，固定回退后的基线。
2. 盘点首页、搜索、详情、查看器、下载和本地画廊的导航入口、返回语义与重复控件，形成最小改版范围。
3. 先实现画廊列表自动加载下一页和手动翻页，再调整跨页面动线，避免同时重写 Provider 协议。
4. 在 NAS/server 上运行 Flet Web smoke，确认服务器存储语义、远程图片、下载恢复和浏览器文件交换限制。
5. 执行 Android 覆盖升级、清除缓存、清除数据和重启矩阵；记录四域实际路径。
6. 只有 Flet 内建能力被实测证明不足时，才为单一平台缺口设计 Flutter extension 和 Python wrapper，并先定义 Web fallback。

### 验收标准

- 删除或不导入 Flet 模块时，可构造 Runtime、读取/保存后端配置并调用三类 Provider。
- Backend API 的公开 DTO 保持可 JSON 序列化，且不含 Cookie value、`raw`、`Path`、Response、Future 或控件。
- Flet 桌面、Android 和 Web 复用同一 Core/Facade；平台 adapter 和 Flutter extension 不重新实现 Provider client registry。
- Flet 行为不回退；凭据保存、Provider 搜索、Pixiv feeds、EH 登录、图片、下载和本地画廊继续工作。
- NAS/Web 实例明确展示服务器存储语义，并在缺少认证或用户隔离时明确限制为可信环境。

## 未来目标：单文件画廊与 CBZ

- 目标模型为“一个画廊一个归档文件”，减少 SD 卡等低性能文件系统中的目录项数量，并方便移动、备份和分享；不要把逐页图片、metadata 和持久缩略图散落为大量并列文件。
- Provider 提供官方归档时保留官方文件：EH Archive 继续保留原始 ZIP，不修改、不重打包、不仅为改扩展名而转成 CBZ。
- Provider 只提供独立图片、且未来允许逐页下载时，由 FletViewer 在 staging 中直接生成单个自包含 CBZ；图片使用固定宽度页码，已压缩图片优先 `ZIP_STORED`，完成校验后原子发布。
- 自建 CBZ 根目录包含 `ComicInfo.xml`（第三方漫画阅读器兼容）和 `gallery.json`（FletViewer/provider 完整 metadata），正文只包含真实画廊页面。
- 本地画廊封面不要求在归档旁持久保存 `thumb.*`；优先从 ZIP/CBZ 的封面 member 读取，并在应用 `Cache` 域维护可删除、可重建的集中式缩略图缓存。具体缩略图策略后续单独设计。
- ZIP/CBZ 阅读必须支持不解压整本的列表与随机单页读取，并继续限制 member 数量、单页/总解压大小、路径穿越、加密归档和损坏 CRC。
- 第一阶段不改变 EH“批量下载只使用 Archive”的约束；逐页打包 CBZ 主要面向未来支持该下载方式的 Booru、Pixiv 或其他 provider。

## 存储可靠性之后

1. 增加最小通知接口和默认 print backend，先接入下载完成/失败、Archive 消费和存储恢复事件；后续再适配 Web、Android、Windows、Linux、Telegram/webhook。
2. 优先完善本地画廊、详情页和本地 ZIP 阅读器，使其复用在线画廊的视觉与 provider-agnostic 阅读模型，并保持垂直模式窗口化加载。
3. 按账户、显示与主题、浏览与阅读、网络与代理、下载、本地画廊、通知、存储与维护、平台、调试重新组织设置页。
4. 在现有 browser_session/transport 上增加统一代理配置，不平行创建第二套网络 singleton；确保 Provider、图片和下载共享代理、Cookie、UA 与连接状态。
5. 增加受四域根目录限制的微型文件管理器/存储浏览器，主要用于 Android、Web/server 和桌面存储诊断；危险删除需确认，Data/Downloads 不提供无保护批量删除。
6. 完成 Linux、Windows、Android、Web/server 的存储、通知、代理、下载恢复和外部文件交换验收。

## 平台存储拆分（代码已落地，待 Android 真机验收）

### 背景与已确认事实

- Phase 1/2 代码已开始落地：`resolve_storage()`、`configure_storage()`、`migrate_legacy_storage()` 会在应用 import 早期执行；Windows 桌面已验证可把旧根目录迁移为 `FletViewer/Data`、`FletViewer/Cache/files`、`FletViewer/Downloads`、`FletViewer/Temp`，并写入 `Data/.storage-layout-v1`。
- 仍需 Android 真机覆盖升级与“清除缓存”验收，不能把桌面迁移成功等同于 Android 完成。
- 迁移前旧布局位于同一个相对 `FletViewer/` 根目录。Windows 开发模式曾确认：旧 Data 文件在根目录、Cache 在 `FletViewer/Cache`、Downloads 在 `FletViewer/Downloads`、Temp 在 `FletViewer/Temp`。
- Flet 打包环境会提供 `FLET_APP_STORAGE_DATA` 和 `FLET_APP_STORAGE_TEMP`。前者用于跨启动保留的应用数据，后者用于允许系统清理的缓存/临时数据；普通 `python main.py` 桌面开发环境中两者可以未设置。
- Android 系统设置区分“清除缓存”和“清除数据”。图片、sprite 和可重建索引应进入 application cache；配置、数据库、下载任务、下载中断点和本地画廊不得随“清除缓存”删除。
- Android APK 当前相对路径可能落在 Flet Android 应用的 Python 代码解包目录下。代码包升级时该目录可能被删除重建，因此持久业务数据必须迁移到 `FLET_APP_STORAGE_DATA` 或 `StoragePaths` 返回的 application support/documents 路径。
- `app/debug_log.py` 已改为写入 `TEMP_DIR/debug_log.md`；`TEMP_DIR` 当前优先取 `FLET_APP_STORAGE_TEMP/Temp`，桌面 fallback 为 `FletViewer/Temp`。日志允许被“清除缓存”或系统临时文件回收删除。
- `app/main.py` 已在启动时用 `print()` 输出平台、Data、Cache、Downloads、Temp，以及两个 Flet 环境变量。路径迁移完成后继续保留这组输出作为桌面/Android smoke 证据。
- Flet 0.85.3 提供 `StoragePaths` service，可查询 application cache/documents/support、downloads、external storage 和 temporary 等平台路径；Web 不支持该 service。
- Flet 提供 `FilePicker` 负责系统文件选择和另存为。Android SAF 结果不应假定为普通 `Path`；`content://` URI、Flet 控件和 `FilePickerFile` 不得进入 `core/`。
- 存储拆分本身不需要 `flet_permission_handler`。应用私有 data/cache、系统 FilePicker/SAF 通常不需要传统存储权限；不要申请 `MANAGE_EXTERNAL_STORAGE`，不要为了导入/导出申请“所有文件访问”。

### 目标存储模型

建立一个普通 Python dataclass，建议位于 `core/storage.py`，不依赖 Flet：

```python
@dataclass(frozen=True, slots=True)
class AppStoragePaths:
    data: Path
    cache: Path
    downloads: Path
    temp: Path
```

各存储域的权威语义：

| 存储域 | 内容 | 是否允许系统随时清理 | 用户是否直接修改 |
|---|---|---:|---:|
| Data | `config.json`、`data.db`、Cookie、下载任务状态、历史、本地画廊索引 | 否 | 第一版只读显示，不允许直接输入路径 |
| Cache | `cache.db`、图片文件、EH sprite base/crop、可重建详情缓存 | 是 | 第一版提供查看、统计、清理；以后可设置容量上限 |
| Downloads | `Downloading/`、断点文件、EH Archive、本地画廊 metadata/封面 | 否 | 第一版只读显示；以后通过平台目录选择和完整迁移流程修改 |
| Temp | 日志、导入 staging、导出 staging、处理中间文件 | 是 | 只显示和清理，不允许直接输入路径 |

桌面 fallback 目标布局：

```text
FletViewer/
├─ Data/
│  ├─ config.json
│  └─ data.db
├─ Cache/
│  ├─ cache.db
│  └─ files/<hash[0:2]>/<hash[2:4]>/<hash.ext>
├─ Downloads/
│  ├─ Downloading/<task_id>/
│  └─ EHArchieve/[gid][token] title/
└─ Temp/
   └─ debug_log.md
```

Android/Flet 目标映射：

| 存储域 | 首选来源 | 建议子目录 |
|---|---|---|
| Data | `FLET_APP_STORAGE_DATA`，必要时用 `StoragePaths.get_application_support_directory()` 校验 | `Data/` |
| Cache | `StoragePaths.get_application_cache_directory()`；低风险过渡可先用 `FLET_APP_STORAGE_TEMP` | `FletViewer/Cache/` 或平台 cache 下独立应用子目录 |
| Downloads | `FLET_APP_STORAGE_DATA` 下的内部受管目录 | `Downloads/` |
| Temp | `FLET_APP_STORAGE_TEMP` 或 `StoragePaths.get_temporary_directory()` | `Temp/` |

注意：内部 `Downloads` 是应用受管下载主副本，不等于 Android 公共 `/storage/emulated/0/Download`。公共导出以后通过 FilePicker/SAF/MediaStore完成，不直接把下载任务工作目录设为公共 Downloads。

### 架构边界

- 新建轻量 `app/platform_storage.py` 或等价模块，负责读取 Flet环境变量、调用 `StoragePaths`、判断平台能力、创建目录以及未来的FilePicker/SAF导入导出。
- `core/` 只接收已解析的普通 `Path`/`AppStoragePaths` 和小型 callback/Protocol；不得 import `app`、`flet`、`flet_permission_handler`，不得保存 `content://` URI冒充普通路径。
- 不建立全能虚拟文件系统，不包装所有 `open()`/`Path` 操作，不引入大型DI容器。平台服务只负责路径与OS文件交换，下载、ZIP解析、缓存算法和数据库仍属于现有core service。
- 当前多个 service在模块import时创建singleton并立即捕获路径。迁移时必须处理初始化顺序：先解析平台路径，再构造或配置 `ImageCacheDB`、`AppDataDB`、`ImageFetcherService`、`DownloadManager` 和 `LocalGalleryManager`。
- 若暂时保留模块singleton，必须提供一次性、线程安全的 `configure(paths)`/延迟初始化，并保证页面创建前完成；不要在已有下载或图片任务运行后切换根目录。
- Web模式不能调用 `StoragePaths`；Web/server继续使用显式环境变量或服务器配置路径，不能把浏览器本地目录当成服务端Path。

### Phase 1：定义路径并拆分新安装布局

1. 新增 `AppStoragePaths` dataclass和统一解析函数，确保整个应用只有一个权威路径对象。
2. 桌面无Flet环境变量时使用 `FLETVIEWER_HOME`（默认 `FletViewer`）作为父目录，并生成 `Data/Cache/Downloads/Temp` 四个子目录。
3. Flet打包环境优先使用 `FLET_APP_STORAGE_DATA` 与 `FLET_APP_STORAGE_TEMP`，确保Android业务数据不再位于Python代码解包目录。
4. 明确 `CONFIG_PATH=paths.data/config.json`、`DATA_DB_PATH=paths.data/data.db`、`CACHE_DB_PATH=paths.cache/cache.db`、`CACHE_FILES_DIR=paths.cache/files`、`DOWNLOADS_DIR=paths.downloads`、`TEMP_DIR=paths.temp`。
5. 保留 `EHArchieve` 历史拼写作为磁盘兼容路径；若以后修正名称，必须单独设计迁移，不在本轮顺手改名。
6. 更新所有app adapter的路径注入：`app/storage.py`、`app/debug_log.py`、`app/image_cache.py`、`app/gallery_cache.py`、`app/download_manager.py`、`app/local_gallery_manager.py`、历史/DB装配以及图片查看器的保存路径。
7. `ensure_dirs()` 必须改成只创建当前目录，不得在每次调用时递归删除`Data`或`Config`。现有 `_remove_legacy_dirs()` 应迁移为有marker、只执行一次的显式迁移步骤。
8. 启动日志继续输出四个绝对路径，并增加“路径来源”：Flet环境变量、`FLETVIEWER_HOME`或StoragePaths，方便真机核对。

Phase 1验收：

| 场景 | 验收结果 |
|---|---|
| Windows `python main.py` | 生成 `FletViewer/Data`、`Cache`、`Downloads`、`Temp`，启动日志为绝对路径 |
| Android首次安装 | Data/Downloads位于稳定application data，Cache/Temp位于系统可清理目录 |
| 普通重启/手机重启 | 配置、DB、任务、Archive保留 |
| Android清除缓存 | 图片和临时日志可删除；配置、历史、任务、Archive保留；再次浏览自动重建缓存 |
| Android清除数据 | 所有内部数据删除，应用可按首次启动重新初始化 |
| APK覆盖升级且Python代码变化 | 配置、数据库、下载任务和Archive仍保留 |
| 禁图开关关闭 | 不读cache、不发图片请求，只显示占位 |

### Phase 2：一次性迁移现有数据

迁移来源是当前旧布局：

```text
FletViewer/config.json
FletViewer/data.db
FletViewer/cache.db
FletViewer/Cache/<hash shards>
FletViewer/Downloads/
FletViewer/Temp/debug_log.md
```

迁移目标：

| 旧路径 | 新路径 |
|---|---|
| `FletViewer/config.json` | `Data/config.json` |
| `FletViewer/data.db` | `Data/data.db` |
| `FletViewer/cache.db` | `Cache/cache.db` |
| `FletViewer/Cache/<hash shards>` | `Cache/files/<hash shards>` |
| `FletViewer/Downloads/*` | `Downloads/*`；若父目录相同则不移动 |
| 旧根目录`debug_log.md` | 不迁移，可删除或保留为遗留文件；新日志只写Temp |

迁移约束：

1. 在任何DB、图片fetcher、download manager启动前执行迁移。
2. 使用明确的schema/version或marker，例如 `Data/.storage-layout-v1`；只有完成全部关键步骤后才写marker。
3. 目标已存在时不盲目覆盖。配置和DB优先保留目标；必要时记录冲突并停止迁移，不能合并两个SQLite文件。
4. 同盘优先原子移动；跨磁盘/Android不同存储域使用“复制到临时目标 -> flush/close -> 校验大小或DB可打开 -> 原子rename -> 删除源”。
5. Cache迁移失败可以丢弃并重建；Data和Downloads迁移失败必须保留源文件并报告，不得静默删除。
6. 迁移下载目录前确认没有运行任务；应用启动迁移发生在manager初始化前，因此理论上无活跃worker。
7. SQLite迁移前处理 `-wal`/`-shm` 文件；确保没有打开连接，并在目标位置执行完整性smoke。
8. Archive目录迁移后更新`data.db.local_galleries`和下载task payload中的绝对路径，或优先将持久记录改为相对Downloads路径，避免未来再次迁移时失效。
9. 图片cache index保存filename而非绝对路径的现有设计应保留，这样只需迁移cache根目录。
10. 迁移过程只记录路径和结果，不记录Cookie value/token或敏感header。

Phase 2验收：

| 数据 | 验收方式 |
|---|---|
| 配置/Cookie | 旧设置与登录状态保留，日志不打印值 |
| `data.db` | 历史、下载任务、本地画廊列表可读 |
| `cache.db` | 索引可打开，已有图片命中；迁移失败时可安全重建 |
| 图片文件 | hash分片路径与索引一致，stale repair仍工作 |
| 下载中任务 | `.part`和进度保留，启动恢复规则不变 |
| 完成Archive | ZIP、`gallery.json`、thumb保留，本地ZIP阅读正常 |
| 重复启动 | marker存在时不再次移动/删除文件 |
| 迁移中模拟失败 | 源Data/Downloads完整保留，可再次尝试或明确提示 |

### Phase 3：设置页“存储”入口

第一版只提供安全、可解释的入口，不允许用户手填任意路径：

| 设置项 | 第一版行为 | 后续行为 |
|---|---|---|
| Data | 显示绝对路径、用途和占用；提供“导出备份”预留 | 不建议允许直接修改，未来做备份/恢复 |
| Cache | 显示路径、占用、文件数；提供“清除缓存” | 增加容量上限和自动淘汰策略 |
| Downloads | 显示内部受管路径、占用和任务/画廊数量；显示“选择目录（尚未实现）”入口 | Desktop目录选择；Android SAF tree或app-specific external目录，并执行完整迁移 |
| Temp | 显示路径、占用；提供“清理临时文件/日志” | 保持平台管理，不允许改路径 |
| 默认导出位置 | 先显示“每次询问” | 以后支持系统Downloads或用户授权位置 |

设置页约束：

- 路径文本应可选择/复制；Android私有路径对普通文件管理器不可见，UI要明确说明。
- 清除Cache前停止/协调图片fetch任务，不能在文件正在写入时直接删目录；清理后重建cache目录和DB，并使相关view cache失效。
- 清理Temp不得影响下载中的`.part`，因此下载工作目录不得放在Temp。
- 修改Downloads不能只是保存一个字符串：必须检查空间、暂停下载、迁移现有Archive和`.part`、更新DB路径、失败回滚。该能力放到后续，不在第一版伪实现。
- Android SAF返回的`content://`不能保存成普通Path后交给core；若实现长期目录授权，需要专门adapter和persisted URI permission。

### Phase 4：系统文件导入/导出

使用Flet `FilePicker`建立用户文件交换，不改变内部受管下载主副本：

1. “导入ZIP”：App层调用FilePicker；Desktop可获得真实path后复制到Temp staging，Android/Web用`with_data=True`物化为Temp文件，再交给core校验ZIP和导入本地画廊。
2. Android/Web第一版只支持有明确大小上限的小ZIP，避免数百MB Archive整文件跨Flet通道进入内存；建议先限制32或64MiB并明确提示。
3. “导出Archive/图片”：Desktop由save dialog返回目标Path后流式复制；Android/Web小文件可用`save_file(src_bytes=...)`。
4. 大Archive导入/导出后续使用Android SAF原生输入/输出流或MediaStore，必须分块传输并报告进度，不能`read_bytes()`整个1GiB文件。
5. 系统选择器取消属于正常结果，不显示错误，不留下staging文件。
6. 损坏ZIP、空间不足、权限被撤销时清理临时文件并显示可恢复错误，不污染本地画廊DB。

### 权限策略

- 第一阶段存储拆分、应用私有Data/Cache/Downloads/Temp不需要新增Android权限。
- FilePicker/SAF由用户明确选择文件或位置，通常不需要`READ_EXTERNAL_STORAGE`、`WRITE_EXTERNAL_STORAGE`或`READ_MEDIA_IMAGES`。
- 不申请`MANAGE_EXTERNAL_STORAGE`，FletViewer不是文件管理器；Google Play对“所有文件访问”有严格限制。
- `flet_permission_handler`只在未来真正需要相机、媒体库扫描等运行时权限时引入。引入前确认Android wheel/plugin打包、桌面/Web降级和manifest配置。
- 若未来实现用户授权的长期SAF目录，使用persistable URI permission，并在权限撤销后提供重新授权，不转换为伪Path。

### 测试与真机矩阵

自动测试至少覆盖：

- 无Flet环境变量时桌面路径解析为统一父目录下的四个子目录。
- 设置`FLET_APP_STORAGE_DATA/TEMP`时Data/Downloads与Cache/Temp分离。
- 新布局首次创建、重复创建幂等。
- 旧配置、DB、cache和Downloads迁移成功。
- 目标已存在、复制失败、空间不足、SQLite WAL存在等失败路径不删除源数据。
- 迁移marker只在完整成功后写入。
- Cache目录被删除后应用可重建，Data/Downloads不受影响。
- Temp日志目录不存在时logger可创建；目录被清理后下次启动可恢复。
- 下载和本地画廊manager接收新路径后状态恢复、Archive消费和ZIP阅读正常。

Android正式APK手工测试：

1. 首次安装，截图/记录启动print中的四个绝对路径和环境变量。
2. 保存设置、产生历史、缓存图片、创建下载任务、完成一个小Archive。
3. 强停并重启，确认全部保留。
4. 在系统设置点击“清除缓存”，确认Cache/Temp删除或缩小，Data/Downloads保留；再次浏览自动重建缩略图。
5. 构建代码发生变化的新APK并`adb install -r -d`覆盖安装，确认配置、历史、任务和Archive保留。
6. 重启手机后复测本地画廊和ZIP阅读。
7. 点击“清除数据”，确认应用回到首次启动且无损坏状态。
8. 卸载后重装，确认内部数据按Android语义删除；未来导出到公共位置的文件应保留。

### 禁止事项与风险提醒

- 不要继续使用`Path.cwd()`或Flet Python代码解包目录作为持久业务根目录。
- 不要把图片cache放进Data，也不要把下载中的`.part`或Archive放进Temp/Cache。
- 不要把`StoragePaths.get_downloads_directory()`返回值直接当作Android可任意写的普通公共目录；Scoped Storage下优先FilePicker/SAF/MediaStore。
- 不要在路径迁移中使用无回滚的`shutil.rmtree()`或先删源后复制。
- 不要在service worker运行期间切换路径；初始化和迁移必须发生在所有manager/executor启动之前。
- 不要把平台URI、Flet service或权限handler引入core。
- 不要为了“统一”同时重构下载模型、缓存数据库和Provider协议；路径拆分优先小改、可迁移、可验证。
- `cache.db`虽然可重建，但其中若未来加入不可重建信息，必须拆表或迁入Data，不能依赖系统cache持久性。

### Android 验收继续顺序

1. 检查当前工作树和本TODO，确认缩略图并发修复、下载页三Provider Tab、默认瀑布流、Temp日志和启动路径print仍在。
2. 读取`app/storage.py`以及所有路径常量调用点，建立完整路径消费者清单。
3. 新增`AppStoragePaths`与纯函数路径解析测试，先不迁移真实文件。
4. 调整`app/storage.py`为四域常量/访问器，并修复`ensure_dirs()`的删除副作用。
5. 实现一次性migration和marker，先用临时目录自动测试，再针对当前桌面`FletViewer/`做真实迁移。
6. 延迟/重配各模块singleton，确保迁移发生在DB和executor初始化前。
7. 更新设置页存储只读面板和Cache/Temp清理操作。
8. 运行所有图片并发测试、compileall、下载/本地画廊smoke。
9. 构建并侧载Android APK，执行覆盖升级和清缓存矩阵。
10. 存储稳定后，再开始FilePicker小ZIP导入/导出；大文件SAF放到独立后续任务。
