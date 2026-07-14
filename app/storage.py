import json
import os
from datetime import datetime
from pathlib import Path

from core.atomic_file import atomic_write_json
from core.storage import AppStoragePaths, StorageLayout

ROOT_DIR = Path(os.environ.get("FLETVIEWER_HOME", "FletViewer"))
TEMP_DIR = Path(os.environ.get("FLET_APP_STORAGE_TEMP") or ROOT_DIR / "Temp")
CONFIG_DIR = ROOT_DIR / "Config"
EH_CONFIG_PATH = CONFIG_DIR / "EHArchieve.json"
APP_CONFIG_PATH = CONFIG_DIR / "AppConfig.json"
CACHE_DB_PATH = ROOT_DIR / "cache.db"
DATA_DB_PATH = ROOT_DIR / "data.db"
CACHE_FILES_DIR = ROOT_DIR / "Cache"
CONFIG_PATH = ROOT_DIR / "config.json"
DOWNLOADS_DIR = ROOT_DIR / "Downloads"
DOWNLOADING_DIR = DOWNLOADS_DIR / "Downloading"
EH_ARCHIVE_DIR = DOWNLOADS_DIR / "EHArchieve"
LEGACY_DATA_DIR = ROOT_DIR / "Data"
GALLERY_CACHE_DIR = ROOT_DIR / "Data" / "GalleryCache"
IMAGE_CACHE_DIR = ROOT_DIR / "Data" / "ImageCache"
IMAGE_CACHE_FILES_DIR = IMAGE_CACHE_DIR / "files"
IMAGE_CACHE_DB_PATH = CACHE_DB_PATH
IMAGE_CACHE_LEGACY_INDEX_PATH = IMAGE_CACHE_DIR / "index.json"

_storage_layout = StorageLayout(
    paths=AppStoragePaths(
        data=ROOT_DIR,
        cache=ROOT_DIR,
        downloads=DOWNLOADS_DIR,
        temp=TEMP_DIR,
    ),
    config_file=CONFIG_PATH,
    data_db=DATA_DB_PATH,
    cache_db=CACHE_DB_PATH,
    cache_files=CACHE_FILES_DIR,
    downloading_dir=DOWNLOADING_DIR,
    eh_archive_dir=EH_ARCHIVE_DIR,
    debug_log_file=TEMP_DIR / "debug_log.md",
    import_staging_dir=TEMP_DIR / "import",
    export_staging_dir=TEMP_DIR / "export",
)

EH_CONFIG_KEYS = ("ipb_member_id", "ipb_pass_hash", "igneous", "star")
BOORU_CONFIG_DEFAULTS = {"gelbooru_user_id": "", "gelbooru_api_key": ""}
PIXIV_CONFIG_DEFAULTS = {"user_id": "", "cookie": ""}
APP_CONFIG_DEFAULTS = {
    "enable_login": True,
    "load_images": True,
    "show_error_toasts": True,
    "show_task_debug_overlay": True,
    "enable_file_manager_panel": False,
    "enable_debug_panel": False,
    "render_gallery_cards": True,
    "theme_mode": "system",
    "theme_color": "adaptive",
    "image_viewer_mode": "paged",
    "gallery_grid_columns": 5,
    "gallery_detail_preview_rows": 3,
    "gallery_view_mode": "masonry",
    "show_gallery_page_count": True,
    "show_gallery_info": True,
    "debug_show_cover_dimensions": False,
    "debug_force_gallery_favorite": False,
    "debug_force_gallery_downloaded": False,
    "debug_force_gallery_update": False,
    "image_grid_target_width": 220,
    "linux_builtin_title_bar": False,
    "linux_prefer_wayland_window_backend": False,
    "proxy_mode": "disabled",
    "proxy_url": "",
    "active_provider": "ehentai",
    "active_booru_provider": "gelbooru",
}
IMAGE_VIEWER_MODES = {"paged", "vertical"}
THEME_MODES = {"system", "light", "dark"}
THEME_COLORS = {"adaptive", "teal", "blue", "green", "rose", "amber", "violet"}
GALLERY_VIEW_MODES = {"card", "list", "masonry"}
CONFIG_DEFAULTS = {
    "eh": {k: "" for k in EH_CONFIG_KEYS},
    "booru": dict(BOORU_CONFIG_DEFAULTS),
    "pixiv": dict(PIXIV_CONFIG_DEFAULTS),
    "app": dict(APP_CONFIG_DEFAULTS),
}


def configure_storage(layout: StorageLayout) -> None:
    """设置本次启动使用的存储布局；必须在存储服务初始化前调用。"""
    global _storage_layout
    _storage_layout = layout


def get_storage_layout() -> StorageLayout:
    return _storage_layout


def ensure_dirs():
    """确保基础目录存在。旧布局只能由显式迁移流程处理。"""
    get_storage_layout().paths.data.mkdir(parents=True, exist_ok=True)


def ensure_temp_dirs() -> None:
    """确保可随系统缓存清理的临时目录存在。"""
    get_storage_layout().paths.temp.mkdir(parents=True, exist_ok=True)


def ensure_download_dirs():
    """确保下载系统需要的目录存在。"""
    layout = get_storage_layout()
    layout.paths.downloads.mkdir(parents=True, exist_ok=True)
    layout.downloading_dir.mkdir(parents=True, exist_ok=True)
    layout.eh_archive_dir.mkdir(parents=True, exist_ok=True)


def ensure_gallery_cache_dirs():
    """确保画廊详情缓存目录存在。"""
    get_storage_layout().paths.cache.mkdir(parents=True, exist_ok=True)


def ensure_image_cache_dirs():
    """确保图片缓存目录存在。"""
    layout = get_storage_layout()
    layout.paths.cache.mkdir(parents=True, exist_ok=True)
    layout.cache_files.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict:
    config_path = get_storage_layout().config_file
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeError, TypeError, ValueError):
            _quarantine_config(config_path)
            return {key: dict(value) for key, value in CONFIG_DEFAULTS.items()}
        if isinstance(data, dict):
            try:
                return {
                    "eh": {**CONFIG_DEFAULTS["eh"], **dict(data.get("eh") or {})},
                    "booru": {**CONFIG_DEFAULTS["booru"], **dict(data.get("booru") or {})},
                    "pixiv": {**CONFIG_DEFAULTS["pixiv"], **dict(data.get("pixiv") or {})},
                    "app": {**CONFIG_DEFAULTS["app"], **dict(data.get("app") or {})},
                }
            except (TypeError, ValueError):
                _quarantine_config(config_path)
        else:
            _quarantine_config(config_path)
    return {key: dict(value) for key, value in CONFIG_DEFAULTS.items()}


def _quarantine_config(config_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = config_path.with_name(f"{config_path.name}.corrupt-{stamp}")
    config_path.replace(target)
    return target


def _save_config(data: dict) -> None:
    ensure_dirs()
    config_path = get_storage_layout().config_file
    payload = {
        "eh": {**CONFIG_DEFAULTS["eh"], **dict(data.get("eh") or {})},
        "booru": {**CONFIG_DEFAULTS["booru"], **dict(data.get("booru") or {})},
        "pixiv": {**CONFIG_DEFAULTS["pixiv"], **dict(data.get("pixiv") or {})},
        "app": {**CONFIG_DEFAULTS["app"], **dict(data.get("app") or {})},
    }
    atomic_write_json(config_path, payload)


def load_eh_config() -> dict:
    """读取 EH Cookie 凭据配置；不存在时返回空字段。"""
    return _load_config()["eh"]


def save_eh_config(cfg: dict) -> None:
    """保存 EH Cookie 凭据配置。"""
    data = _load_config()
    data["eh"] = {**CONFIG_DEFAULTS["eh"], **cfg}
    _save_config(data)


def load_booru_config() -> dict:
    return _load_config()["booru"]


def save_booru_config(cfg: dict) -> None:
    data = _load_config()
    data["booru"] = {**BOORU_CONFIG_DEFAULTS, **cfg}
    _save_config(data)


def load_pixiv_config() -> dict:
    """读取 Pixiv 网页会话凭据。"""
    return _load_config()["pixiv"]


def save_pixiv_config(cfg: dict) -> None:
    """保存用户从已登录浏览器复制的 Pixiv Cookie。"""
    data = _load_config()
    data["pixiv"] = {**PIXIV_CONFIG_DEFAULTS, **cfg}
    _save_config(data)


def load_app_config() -> dict:
    """读取应用配置，并与默认值合并以兼容新增配置项。"""
    return _load_config()["app"]


def save_app_config(cfg: dict) -> None:
    """保存应用配置；会补齐默认字段。"""
    data = _load_config()
    data["app"] = {**APP_CONFIG_DEFAULTS, **cfg}
    _save_config(data)


def should_load_images() -> bool:
    """返回当前是否允许加载图片资源。"""
    return bool(load_app_config().get("load_images", True))


def should_render_gallery_cards() -> bool:
    """返回画廊列表是否使用卡片模式；False 时使用 JSON 调试模式。"""
    return bool(load_app_config().get("render_gallery_cards", True))


def should_show_error_toasts() -> bool:
    """返回错误发生时是否显示底部轻量提示。"""
    return bool(load_app_config().get("show_error_toasts", True))


def should_show_task_debug_overlay() -> bool:
    """返回是否显示任务调试浮层。"""
    return bool(load_app_config().get("show_task_debug_overlay", True))


def should_enable_file_manager_panel() -> bool:
    """返回是否在底栏显示文件管理器附加面板。"""
    return bool(load_app_config().get("enable_file_manager_panel", False))


def should_enable_debug_panel() -> bool:
    """返回是否在底栏显示调试附加面板。"""
    return bool(load_app_config().get("enable_debug_panel", False))


def get_theme_mode() -> str:
    """读取界面明暗模式，并对非法值回退到跟随系统。"""
    mode = str(load_app_config().get("theme_mode", "system"))
    return mode if mode in THEME_MODES else "system"


def get_theme_color() -> str:
    """读取 Material 3 色彩风格，并对非法值回退到自适应。"""
    color = str(load_app_config().get("theme_color", "adaptive"))
    return color if color in THEME_COLORS else "adaptive"


def get_image_viewer_mode() -> str:
    """读取默认图像查看器模式，并对非法值回退到 paged。"""
    mode = str(load_app_config().get("image_viewer_mode", "paged"))
    return mode if mode in IMAGE_VIEWER_MODES else "paged"


def get_image_grid_target_width() -> int:
    """读取图片网格参考宽度，并限制在合理范围内。"""
    try:
        value = int(load_app_config().get("image_grid_target_width", 220))
    except (TypeError, ValueError):
        value = 220
    return max(140, min(420, value))


def get_gallery_grid_columns() -> int:
    """读取画廊浏览器列数，并限制在合理范围内。"""
    try:
        value = int(load_app_config().get("gallery_grid_columns", 5))
    except (TypeError, ValueError):
        value = 5
    return max(2, min(10, value))


def get_gallery_detail_preview_rows() -> int | None:
    """读取详情页初始缩略图行数；None 表示显示全部。"""
    value = load_app_config().get("gallery_detail_preview_rows", 3)
    if value == "all":
        return None
    try:
        rows = int(value)
    except (TypeError, ValueError):
        rows = 3
    return rows if rows in {2, 3, 4} else 3


def get_gallery_view_mode() -> str:
    """读取画廊浏览模式；旧 waterfall 值兼容为等高卡片模式。"""
    mode = str(load_app_config().get("gallery_view_mode", "masonry"))
    if mode == "waterfall":
        return "card"
    return mode if mode in GALLERY_VIEW_MODES else "masonry"


def should_show_gallery_page_count() -> bool:
    """返回画廊卡片是否显示页数。"""
    return bool(load_app_config().get("show_gallery_page_count", True))


def should_show_gallery_info() -> bool:
    """返回画廊卡片是否显示底部标题和元信息。"""
    return bool(load_app_config().get("show_gallery_info", True))


def should_debug_show_cover_dimensions() -> bool:
    """返回是否在画廊封面显示解析到的尺寸。"""
    return bool(load_app_config().get("debug_show_cover_dimensions", False))


def should_debug_force_gallery_favorite() -> bool:
    return bool(load_app_config().get("debug_force_gallery_favorite", False))


def should_debug_force_gallery_downloaded() -> bool:
    return bool(load_app_config().get("debug_force_gallery_downloaded", False))


def should_debug_force_gallery_update() -> bool:
    return bool(load_app_config().get("debug_force_gallery_update", False))


def should_use_linux_builtin_title_bar() -> bool:
    """返回 Linux 桌面端是否使用应用内标题栏。"""
    return bool(load_app_config().get("linux_builtin_title_bar", False))


def should_prefer_linux_wayland_window_backend() -> bool:
    """返回 Linux 桌面端是否优先使用 Wayland 后端。"""
    return bool(load_app_config().get("linux_prefer_wayland_window_backend", False))
