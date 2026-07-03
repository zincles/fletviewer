import json
import os
from pathlib import Path

ROOT_DIR = Path(os.environ.get("FLETVIEWER_HOME", "FletViewer"))
CONFIG_DIR = ROOT_DIR / "Config"
EH_CONFIG_PATH = CONFIG_DIR / "EHArchieve.json"

EH_CONFIG_KEYS = ("ipb_member_id", "ipb_pass_hash", "igneous", "star")


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


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
