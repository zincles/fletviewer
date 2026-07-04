# FletViewer 下载系统 TODO

## 目标

为 FletViewer 实现完整的画廊下载系统。

EH 只允许 Archive Download（归档下载），不允许逐页下载（会导致 503 Forbidden）。
下载产物为 EH 提供的 ZIP + 我们自己的 metadata JSON，不解压图像，不重命名压缩包。

下载系统由两个单例组成：

- `DownloadManager`：负责下载大型文件、任务列表、状态、tag、事件通知
- `LocalGalleryManager`：负责消费已完成下载任务、创建本地画廊目录、写 metadata、移动 ZIP、提取 cover、扫描已有画廊

---

## 依赖

### 需要新增

```
pathvalidate    # 文件名/路径非法字符清洗
Pillow          # 已安装，用于 ZIP 内提取 cover 时的图片格式判断（如需要）
```

在 `pyproject.toml` 的 `dependencies` 中加入 `pathvalidate`。

### 已有可复用

```
requests        # 下载用，复用 browser_session 的 Session/cookie/UA
Pillow (PIL)    # 已安装，image_fetcher 已在用
```

---

## 目录结构

### 下载中目录

```
FletViewer/
  Downloads/
    Downloading/
      <task_id>/
        task.json          # 任务状态
        payload.part       # 下载中的临时文件（支持断点续传）
        payload.zip        # 下载完成后的最终文件（rename 自 .part）
```

### EH Archive 本地画廊目录

```
FletViewer/
  Downloads/
    EHArchieve/
      [<GID>][<TOKEN>] <SanitizedGalleryTitle>/
        gallery.json       # 完整 metadata（包装结构体）
        thumb.<ext>        # 从 ZIP 提取的第一张图片作为封面
        <remote_archive_filename>.zip   # EH 原始文件名，不重命名
```

### 全局任务索引

```
FletViewer/
  Data/
    Downloads/
      tasks.json           # 全局任务列表（轻量索引）
```

---

## 数据结构

### DownloadTask（task.json）

```json
{
  "id": "uuid4",
  "kind": "large_file",
  "status": "queued | running | completed | failed | cancelled | consumed",
  "url": "https://...",
  "method": "GET",
  "headers": {
    "Referer": "https://e-hentai.org/"
  },
  "tags": ["eh_archive"],
  "tag_data": {
    "provider": "ehentai",
    "gallery_url": "https://e-hentai.org/g/4029680/2515592bd6/",
    "gid": "4029680",
    "token": "2515592bd6",
    "archive_id": "0",
    "archive_title": "Original",
    "archive_description": "Cost: 5 Credits, Size: 120 MB",
    "download_url_acquired_at": "2026-07-04T09:30:00+08:00",
    "download_url_valid_seconds": 86400,
    "max_ip_count": 2,
    "gallery_details": {},
    "thumbnails_result": {}
  },
  "filename": "remote_filename.zip",
  "temp_dir": "Downloads/Downloading/<task_id>",
  "part_path": "Downloads/Downloading/<task_id>/payload.part",
  "final_path": "Downloads/Downloading/<task_id>/payload.zip",
  "bytes_total": 123456789,
  "bytes_done": 0,
  "created_at": "...",
  "started_at": "...",
  "completed_at": "...",
  "updated_at": "...",
  "error": null,
  "resume": {
    "supported": true,
    "etag": "...",
    "last_modified": "...",
    "accept_ranges": "bytes"
  }
}
```

### gallery.json（本地画廊包装结构体）

```json
{
  "schema_version": 1,
  "provider": "ehentai",
  "storage_method": "eh_archive_zip",
  "source": {
    "gid": "4029680",
    "token": "2515592bd6",
    "gallery_url": "https://e-hentai.org/g/4029680/2515592bd6/",
    "domain": "e-hentai.org"
  },
  "gallery": {
    "...": "ComicDetails dataclass asdict"
  },
  "thumbnails": {
    "...": "ThumbnailsResult dataclass asdict（含 items: list[ThumbnailItem]）"
  },
  "archive": {
    "archive_id": "0",
    "title": "Original",
    "description": "Cost: 5 Credits, Size: 120 MB",
    "download_url": "https://...",
    "download_url_acquired_at": "2026-07-04T09:30:00+08:00",
    "download_completed_at": "2026-07-04T09:35:00+08:00",
    "download_url_valid_seconds": 86400,
    "max_ip_count": 2,
    "filename": "<remote_archive_filename>.zip",
    "bytes_total": 123456789
  },
  "files": {
    "archive": "<remote_archive_filename>.zip",
    "cover": "thumb.webp"
  },
  "created_at": "...",
  "updated_at": "..."
}
```

### tasks.json（全局任务索引）

```json
{
  "tasks": [
    {
      "id": "...",
      "provider": "ehentai",
      "status": "completed",
      "source_url": "...",
      "title": "...",
      "output_dir": "...",
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

---

## 组件一：DownloadManager

### 文件

```
app/download_manager.py
```

### 单例

```python
download_manager = DownloadManager()
```

### 职责

- 创建下载任务
- 下载大型文件到临时目录（流式，支持断点续传）
- 持久化任务状态到 `task.json`
- 维护全局任务索引 `tasks.json`
- 暴露任务列表
- 支持给任务打 tag
- 支持进度统计
- 下载完成后发送事件通知
- 支持失败状态
- 第一版不做暂停，取消可做软取消

### 下载技术方案

使用 `requests` + `browser_session` 共享 Session，流式下载 + HTTP Range 断点续传。

不引入 aria2 / aiohttp / httpx，原因：
- 项目已有 `browser_session`，复用 cookie/UA/Referer 最方便
- Android 打包风险低
- 无额外二进制依赖
- EH Archive 带 GP 限制，不适合激进并发

### 断点续传实现

1. 如果 `payload.part` 已存在，取 `offset = part_path.stat().st_size`
2. 请求头加 `Range: bytes={offset}-`
3. 服务端返回 `206 Partial Content`：追加写入 `payload.part`
4. 服务端返回 `200 OK`：从头覆盖下载（不支持 Range 或 offset 无效）
5. 下载完成：`payload.part` rename 为 `payload.zip`
6. task 状态 `completed`，通知 completion handlers

### 下载流程伪代码

```python
def _download_impl(self, task: DownloadTask):
    offset = 0
    if task.part_path.exists():
        offset = task.part_path.stat().st_size

    headers = dict(task.headers)
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"

    response = browser_session.get(
        task.url,
        headers=headers,
        stream=True,
        timeout=60,
    )

    if offset > 0 and response.status_code == 200:
        # 服务端忽略 Range，从头下载
        offset = 0
        mode = "wb"
    elif response.status_code == 206:
        mode = "ab"
    elif response.status_code == 200:
        mode = "wb"
    else:
        response.raise_for_status()

    task.status = "running"
    task.bytes_total = int(response.headers.get("Content-Length", 0)) + offset
    task.resume.supported = response.headers.get("Accept-Ranges") == "bytes"
    task.resume.etag = response.headers.get("ETag")
    task.resume.last_modified = response.headers.get("Last-Modified")
    self._save_task(task)

    with open(task.part_path, mode) as f:
        for chunk in response.iter_content(chunk_size=1024 * 512):
            if task.cancel_requested:
                task.status = "cancelled"
                self._save_task(task)
                return
            f.write(chunk)
            offset += len(chunk)
            task.bytes_done = offset
            # 节流写 task.json（每 1MB 或每 2 秒）
            if offset % (1024 * 1024) < 1024 * 512:
                self._save_task(task)

    task.part_path.rename(task.final_path)
    task.status = "completed"
    task.completed_at = now()
    self._save_task(task)
    self._notify_completed(task)
```

### 进度更新策略

- 不要每个 chunk 都写 JSON，会拖慢磁盘
- 建议每 1MB 或每 2 秒写一次 `task.json`
- `bytes_done` 内存中实时更新，UI 轮询 `list_tasks()` 拿最新值

### 公开接口

```python
class DownloadManager:
    def create_task(
        self,
        url: str,
        filename: str,
        *,
        tags: list[str] | None = None,
        tag_data: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> DownloadTask

    def start_task(self, task_id: str) -> None
    def cancel_task(self, task_id: str) -> None
    def retry_task(self, task_id: str) -> None
    def delete_task(self, task_id: str) -> None

    def list_tasks() -> list[DownloadTask]
    def get_task(task_id: str) -> DownloadTask | None

    def add_completion_handler(
        self, callback: Callable[[DownloadTask], None]
    ) -> None
```

### 事件通知

```python
download_manager.add_completion_handler(
    local_gallery_manager.handle_download_completed
)
```

回调收到完整 `DownloadTask`。

handler 失败不应该让下载任务变 failed。
LocalGalleryManager 处理成功后，可以把任务标记为 `consumed`。

### 并发控制

- 内部使用 `ThreadPoolExecutor(max_workers=2)` 或更少
- EH Archive 不适合激进并发，建议全局同时下载 1-2 个
- 第一版可以 `max_workers=1`

### 任务恢复

- DownloadManager 启动时扫描 `Downloads/Downloading/*/task.json`
- `running` 状态恢复为 `failed`（避免误重下）
- 用户可点重试重新下载
- `completed` 但未 `consumed` 的任务：尝试重新通知 completion handlers

### browser_session 扩展

当前 `browser_session.get()` 可能没有暴露 `stream=True` 参数。
需要扩展，使其支持流式下载，或者 DownloadManager 直接使用 `browser_session` 的内部 `requests.Session`。

```python
# 方案 A：扩展 browser_session.get() 支持 stream
response = browser_session.get(url, headers=headers, stream=True, timeout=60)

# 方案 B：暴露内部 session
session = browser_session.get_session()
response = session.get(url, headers=headers, stream=True, timeout=60)
```

建议方案 B，因为流式下载场景和普通页面请求不同，不需要额外封装。

---

## 组件二：LocalGalleryManager

### 文件

```
app/local_gallery_manager.py
```

### 单例

```python
local_gallery_manager = LocalGalleryManager()
```

### 职责

- 消费已完成的下载任务（通过 completion handler 回调）
- 创建本地画廊目录
- 清洗目录名（使用 pathvalidate）
- 移动/复制 ZIP 到最终目录
- 写 `gallery.json`
- 从 ZIP 中提取第一张图片作为 `thumb.<ext>`
- 扫描 `Downloads/EHArchieve` 下已有画廊
- 建立本地画廊索引

### handle_download_completed 流程

```python
def handle_download_completed(self, task: DownloadTask):
    if "eh_archive" not in task.tags:
        return  # 不是 EH Archive 下载，跳过

    tag_data = task.tag_data
    gid = tag_data["gid"]
    token = tag_data["token"]
    title = tag_data.get("gallery_details", {}).get("title", "Untitled")

    # 1. 清洗目录名
    folder_name = self._eh_archive_folder_name(gid, token, title)
    gallery_dir = EH_ARCHIVE_DIR / folder_name
    gallery_dir.mkdir(parents=True, exist_ok=True)

    # 2. 移动 ZIP（不重命名，保留远端文件名）
    remote_filename = task.filename or "archive.zip"
    archive_path = gallery_dir / remote_filename
    shutil.move(str(task.final_path), str(archive_path))

    # 3. 提取 cover
    cover_filename = self._extract_cover_from_zip(archive_path, gallery_dir)

    # 4. 写 gallery.json
    metadata = self._build_gallery_metadata(task, archive_path, cover_filename)
    (gallery_dir / "gallery.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 5. 标记任务 consumed
    task.status = "consumed"
    download_manager._save_task(task)

    # 6. 刷新本地画廊索引
    self._refresh_index()
```

### 目录名清洗

```python
from pathvalidate import sanitize_filename

def _eh_archive_folder_name(self, gid: str, token: str, title: str) -> str:
    safe_title = sanitize_filename(title or "Untitled", platform="windows").strip()
    if not safe_title:
        safe_title = "Untitled"
    prefix = f"[{gid}][{token}] "
    # 限制总长度
    max_title_len = max(1, 180 - len(prefix))
    safe_title = safe_title[:max_title_len].rstrip(" .")
    return f"{prefix}{safe_title}"
```

### 从 ZIP 提取 cover

```python
import zipfile

def _extract_cover_from_zip(self, zip_path: Path, output_dir: Path) -> str:
    """从 ZIP 中提取第一张图片作为 thumb.<ext>"""
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(
            name for name in zf.namelist()
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
            and not name.startswith("__MACOSX")
            and not name.startswith(".")
        )
        if not names:
            return ""

        first = names[0]
        data = zf.read(first)

        # 根据 ZIP 内文件扩展名决定 thumb 扩展名
        ext = Path(first).suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        cover_filename = f"thumb{ext}"
        (output_dir / cover_filename).write_bytes(data)
        return cover_filename
```

注意：
- ZIP 内可能有目录前缀，排序用自然排序更好，第一版普通排序也可以
- 过滤 `__MACOSX`、隐藏文件
- 如果 ZIP 读取失败，本地画廊仍可创建，只是没有 cover
- cover 提取失败时 `cover_filename = ""`，gallery.json 中 `"cover": ""`

### 构建 gallery.json

```python
def _build_gallery_metadata(
    self,
    task: DownloadTask,
    archive_path: Path,
    cover_filename: str,
) -> dict:
    tag_data = task.tag_data
    gallery_details = tag_data.get("gallery_details", {})
    thumbnails_result = tag_data.get("thumbnails_result", {})

    return {
        "schema_version": 1,
        "provider": "ehentai",
        "storage_method": "eh_archive_zip",
        "source": {
            "gid": tag_data["gid"],
            "token": tag_data["token"],
            "gallery_url": tag_data["gallery_url"],
            "domain": "e-hentai.org",
        },
        "gallery": gallery_details,
        "thumbnails": thumbnails_result,
        "archive": {
            "archive_id": tag_data.get("archive_id", ""),
            "title": tag_data.get("archive_title", ""),
            "description": tag_data.get("archive_description", ""),
            "download_url": task.url,
            "download_url_acquired_at": tag_data.get("download_url_acquired_at", ""),
            "download_completed_at": task.completed_at or "",
            "download_url_valid_seconds": tag_data.get("download_url_valid_seconds", 86400),
            "max_ip_count": tag_data.get("max_ip_count", 2),
            "filename": archive_path.name,
            "bytes_total": task.bytes_total,
        },
        "files": {
            "archive": archive_path.name,
            "cover": cover_filename,
        },
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
```

### 扫描已有画廊

```python
def scan_local_galleries(self) -> list[LocalGallery]:
    """扫描 Downloads/EHArchieve 下所有已有画廊"""
    galleries = []
    if not EH_ARCHIVE_DIR.exists():
        return galleries

    for entry in EH_ARCHIVE_DIR.iterdir():
        if not entry.is_dir():
            continue
        gallery_json = entry / "gallery.json"
        if not gallery_json.exists():
            continue
        try:
            data = json.loads(gallery_json.read_text(encoding="utf-8"))
            galleries.append(LocalGallery(
                dir_path=entry,
                metadata=data,
            ))
        except Exception as ex:
            log_exception("local_gallery", f"scan failed {entry}: {ex}")

    return galleries
```

### 公开接口

```python
class LocalGalleryManager:
    def handle_download_completed(self, task: DownloadTask) -> None
    def scan_local_galleries(self) -> list[LocalGallery]
    def get_gallery(self, gid: str, token: str) -> LocalGallery | None
    def list_galleries(self) -> list[LocalGallery]
```

---

## 组件三：EH Archive 下载集成

### Provider 现状（已实现）

`lib/provider/ehgrabber.py` 已有：

```python
def get_archives(self, comic_url: str) -> list[Archive]:
    """获取归档下载选项列表"""
    # 返回 Archive(id, title, description) 列表
    # id: '0' = Original, '1' = Resample, 'h@h_xxx' = H@H

def get_archive_download_url(self, comic_url: str, archive_id: str) -> str:
    """获取归档下载的真实 URL"""
    # Original/Resample: POST archiver.php -> 跟随重定向 -> 返回最终 URL
    # H@H: 服务端下载，不返回 URL（暂不支持）
```

### 下载流程

1. 用户在画廊详情页点击「下载 Archive」按钮
2. 确保登录：`browser_session.get_eh_client(require_login=True)`
3. 加载画廊详情：`client.load_comic_info(comic_url)` -> `ComicDetails`
4. 加载第一页缩略图：`client.load_thumbnails(comic_url)` -> `ThumbnailsResult`
5. 获取 archive options：`client.get_archives(comic_url)` -> `list[Archive]`
6. 弹出 dialog 让用户选择 archive option（Original / Resample / H@H）
7. 用户选择后，调用：`client.get_archive_download_url(comic_url, archive_id)` -> URL
8. 从 URL 解析远端文件名（Content-Disposition 或 URL path）
9. 创建 DownloadTask：
   - `url = archive_download_url`
   - `filename = remote_filename`
   - `tags = ["eh_archive"]`
   - `tag_data = { provider, gallery_url, gid, token, archive_id, archive_title, archive_description, download_url_acquired_at, download_url_valid_seconds=86400, max_ip_count=2, gallery_details=asdict(details), thumbnails_result=asdict(thumbs) }`
   - `headers = {"Referer": comic_url}`
10. `download_manager.start_task(task.id)`
11. 下载完成后，DownloadManager 自动通知 LocalGalleryManager
12. LocalGalleryManager 自动创建本地画廊目录

### 远端文件名获取

EH Archive 下载 URL 类似：

```
https://ehgt.org/d/xxxx/xxxx/archive.zip?download=1
```

或者最终重定向后的 HatH URL：

```
https://xxx.hath.network:port/h/.../filename.webp
```

建议从 `Content-Disposition` header 获取文件名：

```python
import re
from urllib.parse import unquote

def parse_filename_from_response(response) -> str:
    cd = response.headers.get("Content-Disposition", "")
    m = re.search(r'filename="?([^";\n]+)"?', cd)
    if m:
        return unquote(m.group(1))
    # fallback: 从 URL path 取
    from urllib.parse import urlsplit
    path = urlsplit(response.url).path
    return path.rsplit("/", 1)[-1] or "archive.zip"
```

也可以在 `get_archive_download_url()` 返回后，先发一个 HEAD 请求拿文件名。
但 EH 的 HEAD 可能不返回 Content-Disposition，所以建议在下载开始后的第一个 response 里取。

### H@H 选项

H@H 选项 (`h@h_xxx`) 是服务端下载到你的 HatH 服务器，不返回下载 URL。
第一版可以：
- UI 上显示 H@H 选项但标记为「不可用」或「仅服务端」
- 或者不显示 H@H 选项
- 只支持 Original / Resample

---

## 组件四：UI

### 画廊详情页：下载按钮

在 `app/views/gallery_detail.py` 中：

- 添加「下载 Archive」按钮
- 点击后异步加载 archive options
- 弹出 dialog 显示 options（Original / Resample，显示 Cost 和 Size）
- 用户选择后创建 DownloadTask
- 显示状态：已加入下载队列

### 下载页

当前 `app/main.py` 的 PAGES 里「下载」是占位页。
需要实现 `app/views/downloads.py`：

- 显示下载任务列表
- 每个任务显示：标题、状态、进度条、bytes_done/bytes_total、速度
- 支持操作：重试、取消、删除
- 定时刷新（page.update 轮询或 Timer）
- 已完成的任务显示「已完成」
- consumed 的任务可以显示「已归档」

### 本地画廊浏览页

后续可做，第一版可以先不做 UI。
`LocalGalleryManager.scan_local_galleries()` 已经能扫描已有画廊。
未来可以做一个页面浏览 `Downloads/EHArchieve` 下的本地画廊。

---

## 实现顺序（建议）

### 阶段一：后端核心组件（不接 UI）

1. [ ] `pyproject.toml` 加入 `pathvalidate` 依赖
2. [ ] 创建 `app/download_manager.py`
   - [ ] DownloadTask dataclass
   - [ ] DownloadManager 单例
   - [ ] create_task / start_task / cancel_task / retry_task / delete_task
   - [ ] list_tasks / get_task
   - [ ] 流式下载 + 断点续传
   - [ ] task.json 持久化
   - [ ] tasks.json 全局索引
   - [ ] add_completion_handler
   - [ ] 启动时恢复任务状态（running -> failed）
   - [ ] 并发控制（ThreadPoolExecutor, max_workers=1 或 2）
   - [ ] browser_session 扩展支持 stream 或暴露内部 session
3. [ ] 创建 `app/local_gallery_manager.py`
   - [ ] LocalGallery dataclass
   - [ ] LocalGalleryManager 单例
   - [ ] handle_download_completed
   - [ ] 目录名清洗（pathvalidate）
   - [ ] 移动 ZIP
   - [ ] 从 ZIP 提取 cover
   - [ ] 写 gallery.json
   - [ ] scan_local_galleries
   - [ ] 注册为 download_manager 的 completion handler
4. [ ] `app/storage.py` 加入下载相关路径常量
   - [ ] DOWNLOADS_DIR = ROOT_DIR / "Downloads"
   - [ ] DOWNLOADING_DIR = DOWNLOADS_DIR / "Downloading"
   - [ ] EH_ARCHIVE_DIR = DOWNLOADS_DIR / "EHArchieve"
   - [ ] DOWNLOADS_DATA_DIR = ROOT_DIR / "Data" / "Downloads"
5. [ ] `app/main.py` 启动时初始化两个单例
6. [ ] 手动构造测试任务验证下载链路

### 阶段二：EH Archive 下载集成

7. [ ] 画廊详情页添加「下载 Archive」按钮
8. [ ] archive option dialog（选择 Original / Resample）
9. [ ] 调用 `get_archive_download_url()` 获取下载 URL
10. [ ] 创建 DownloadTask（带完整 tag_data）
11. [ ] 启动下载任务
12. [ ] 验证下载完成后 LocalGalleryManager 自动创建本地画廊

### 阶段三：下载页 UI

13. [ ] 创建 `app/views/downloads.py`
14. [ ] 任务列表展示
15. [ ] 进度条
16. [ ] 重试/取消/删除按钮
17. [ ] 定时刷新
18. [ ] `app/main.py` 把「下载」页从占位改为真实视图

### 阶段四（可选）：本地画廊浏览

19. [ ] 创建 `app/views/local_galleries.py`
20. [ ] 扫描已有画廊
21. [ ] 显示画廊卡片网格
22. [ ] 点击查看 gallery.json
23. [ ] 查看 ZIP 内图片列表（不解压，只列出文件名）
24. [ ] 查看封面

---

## 注意事项

### EH Archive URL 时效性

- Archive download URL 自支付 GP 后有效 1 天（86400 秒）
- 最多允许 2 个 IP 访问
- 超过 2 个 IP 后返回 410 Gone
- task.json 和 gallery.json 中都要保存 `download_url_acquired_at` 和 `download_url_valid_seconds`
- URL 过期后无法续传，需要重新获取（重新消耗 GP）
- 第一版：URL 过期失败就标记 failed，用户手动重新获取

### 不解压 ZIP

- ZIP 保持在本地画廊目录，不解压
- 不重命名 ZIP，保留远端原始文件名
- 只从 ZIP 中提取第一张图片作为 thumb
- 未来如果需要浏览 ZIP 内图片，用 `zipfile` 按需读取

### 跨平台路径

- Windows: 路径长度 260 字符限制（需启用长路径支持或控制目录名长度）
- Android: 路径由 `FletViewer` 根目录控制，不要假设 `/sdcard`
- 目录名用 `pathvalidate` 清洗，platform="windows"（最严格）

### 下载并发

- EH Archive 带 GP 限制，不适合激进并发
- 建议全局同时下载 1-2 个
- 第一版 `max_workers=1`
- 不做多线程分片下载（对 EH 风险大，收益不明确）

### 进度写盘节流

- 不要每个 chunk 都写 task.json
- 建议每 1MB 或每 2 秒写一次
- bytes_done 内存中实时更新
- UI 轮询 list_tasks() 拿最新值

### 任务恢复

- 启动时扫描 `Downloads/Downloading/*/task.json`
- `running` 恢复为 `failed`（避免误重下）
- `completed` 但未 `consumed`：重新通知 completion handlers
- 用户可点重试重新下载

### browser_session 集成

- 下载必须走 `browser_session`，不能单独新建 requests session
- EH Archive 下载需要 cookie、UA、Referer 一致
- 需要扩展 browser_session 支持 `stream=True` 或暴露内部 session

### LocalGalleryManager 错误处理

- handler 失败不应该让下载任务变 failed
- 处理失败时记录 `consume_error`
- 画廊目录创建失败时，ZIP 保留在 Downloading 目录，不丢失数据

### 封面提取边界情况

- ZIP 内文件排序：第一版普通排序，后续可改自然排序
- 过滤 `__MACOSX`、隐藏文件
- ZIP 读取失败：本地画廊仍可创建，cover 为空
- 第一张图片不是真正封面：可接受，后续可改为从 gallery.cover 下载

---

## 需要确认的问题

- [ ] browser_session 是否需要暴露内部 session 给 DownloadManager？
- [ ] 下载页刷新方式：Timer 轮询还是 Flet 事件？第一版建议 Timer 轮询
- [ ] H@H 选项是否在 UI 显示？第一版建议不显示，只支持 Original/Resample
- [ ] 远端文件名获取时机：HEAD 请求还是下载开始后从 response 取？建议下载开始后取
- [ ] 本地画廊浏览页是否第一版就做？建议不做，先做下载页
