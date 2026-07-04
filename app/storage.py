import json
import os
from pathlib import Path

ROOT_DIR = Path(os.environ.get("FLETVIEWER_HOME", "FletViewer"))
CONFIG_DIR = ROOT_DIR / "Config"
EH_CONFIG_PATH = CONFIG_DIR / "EHArchieve.json"
APP_CONFIG_PATH = CONFIG_DIR / "AppConfig.json"
DOWNLOADS_DIR = ROOT_DIR / "Downloads"
DOWNLOADING_DIR = DOWNLOADS_DIR / "Downloading"
EH_ARCHIVE_DIR = DOWNLOADS_DIR / "EHArchieve"
DOWNLOADS_DATA_DIR = ROOT_DIR / "Data" / "Downloads"
DOWNLOAD_TASKS_INDEX_PATH = DOWNLOADS_DATA_DIR / "tasks.json"
GALLERY_CACHE_DIR = ROOT_DIR / "Data" / "GalleryCache"

EH_CONFIG_KEYS = ("ipb_member_id", "ipb_pass_hash", "igneous", "star")
APP_CONFIG_DEFAULTS = {
    "enable_login": True,
    "load_images": True,
    "render_gallery_cards": True,
    "image_viewer_mode": "paged",
    "image_grid_target_width": 220,
    "linux_builtin_title_bar": False,
    "linux_prefer_wayland_window_backend": False,
}
IMAGE_VIEWER_MODES = {"paged", "vertical"}


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def ensure_download_dirs():
    ensure_dirs()
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADING_DIR.mkdir(parents=True, exist_ok=True)
    EH_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DATA_DIR.mkdir(parents=True, exist_ok=True)


def ensure_gallery_cache_dirs():
    ensure_dirs()
    GALLERY_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_eh_config() -> dict:
    ensure_dirs()
    if EH_CONFIG_PATH.exists():
        with open(EH_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {k: "" for k in EH_CONFIG_KEYS}


def save_eh_config(cfg: dict) -> None:
    ensure_dirs()
    with open(EH_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def load_app_config() -> dict:
    ensure_dirs()
    if APP_CONFIG_PATH.exists():
        with open(APP_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {**APP_CONFIG_DEFAULTS, **data}
    return dict(APP_CONFIG_DEFAULTS)


def save_app_config(cfg: dict) -> None:
    ensure_dirs()
    data = {**APP_CONFIG_DEFAULTS, **cfg}
    with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def should_load_images() -> bool:
    return bool(load_app_config().get("load_images", True))


def should_render_gallery_cards() -> bool:
    return bool(load_app_config().get("render_gallery_cards", True))


def get_image_viewer_mode() -> str:
    mode = str(load_app_config().get("image_viewer_mode", "paged"))
    return mode if mode in IMAGE_VIEWER_MODES else "paged"


def get_image_grid_target_width() -> int:
    try:
        value = int(load_app_config().get("image_grid_target_width", 220))
    except (TypeError, ValueError):
        value = 220
    return max(140, min(420, value))


def should_use_linux_builtin_title_bar() -> bool:
    return bool(load_app_config().get("linux_builtin_title_bar", False))


def should_prefer_linux_wayland_window_backend() -> bool:
    return bool(load_app_config().get("linux_prefer_wayland_window_backend", False))
