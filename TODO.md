# TODO

- UX 优先级切到整体体验重设计：主题基础采用 Material 3，颜色走设置驱动的自适应/手动色种，后续页面只使用语义色和主题入口。
- 下一步先重做主浏览体验的信息架构：阅读首页、搜索、详情页、查看器、下载/本地画廊之间的动线要比 provider 功能更优先。
- 画廊列表仍需补回分页能力：支持自动加载下一页，并保留手动翻页按钮作为显式控制。

## 下次首要任务：平台存储拆分

### 背景与已确认事实

- 当前配置、数据库、缓存和下载仍主要位于同一个相对 `FletViewer/` 根目录。Windows 开发模式的实际路径已通过启动日志确认：Data=`E:\fletviewer\FletViewer`、Cache=`E:\fletviewer\FletViewer\Cache`、Downloads=`E:\fletviewer\FletViewer\Downloads`、Temp=`E:\fletviewer\FletViewer\Temp`。
- Flet 打包环境会提供 `FLET_APP_STORAGE_DATA` 和 `FLET_APP_STORAGE_TEMP`。前者用于跨启动保留的应用数据，后者用于允许系统清理的缓存/临时数据；普通 `python main.py` 桌面开发环境中两者可以未设置。
- Android 系统设置区分“清除缓存”和“清除数据”。图片、sprite 和可重建索引应进入 application cache；配置、数据库、下载任务、下载中断点和本地画廊不得随“清除缓存”删除。
- Android APK 当前相对路径可能落在 Flet/Serious Python 的应用代码解包目录下。代码包升级时该目录可能被删除重建，因此持久业务数据必须迁移到 `FLET_APP_STORAGE_DATA` 或 `StoragePaths` 返回的 application support/documents 路径。
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

### 下次开始时的执行顺序

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
