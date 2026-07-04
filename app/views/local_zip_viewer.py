import re
import zipfile
from pathlib import Path

import flet as ft

from app.controls.async_image import image_placeholder, image_src_for_page
from app.debug_log import log_exception
from app.ui_update import request_update


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _is_image_member(name: str) -> bool:
    path = Path(name)
    if any(part.startswith(".") for part in path.parts):
        return False
    if "__MACOSX" in path.parts:
        return False
    return name.lower().endswith(_IMAGE_EXTS)


def _mime_for_name(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")


def _list_images(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return sorted(
            (info.filename for info in zf.infolist() if not info.is_dir() and _is_image_member(info.filename)),
            key=_natural_key,
        )


def _read_member(zip_path: Path, member: str) -> bytes:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(member)


def create_view(page: ft.Page, zip_path: Path, title_text: str, on_back) -> ft.Control:
    members = _list_images(zip_path) if zip_path.exists() else []
    state = {"index": 0, "generation": 0}

    title = ft.Text(title_text, size=18, weight=ft.FontWeight.W_500, selectable=True, expand=True)
    status = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    image_box = ft.Container(content=image_placeholder(loading=True), expand=True, alignment=ft.Alignment(0, 0))
    prev_btn = ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, tooltip="上一张")
    next_btn = ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, tooltip="下一张")

    def update_nav():
        prev_btn.disabled = state["index"] <= 0
        next_btn.disabled = state["index"] >= len(members) - 1

    def load_current(update: bool = True):
        state["generation"] += 1
        generation = state["generation"]
        if not members:
            status.value = "ZIP 内没有可读图片"
            image_box.content = image_placeholder()
            update_nav()
            if update:
                page.update()
            return

        idx = state["index"]
        member = members[idx]
        status.value = f"读取中... {idx + 1}/{len(members)} · {member}"
        image_box.content = image_placeholder(loading=True)
        update_nav()
        if update:
            page.update()

        def worker():
            try:
                data = _read_member(zip_path, member)
                if generation != state["generation"]:
                    return
                image_box.content = ft.Image(
                    src=image_src_for_page(page, data, _mime_for_name(member)),
                    fit=ft.BoxFit.CONTAIN,
                    expand=True,
                )
                status.value = f"{idx + 1}/{len(members)} · {member} · {len(data)} bytes"
            except Exception as ex:
                status.value = f"读取失败: {ex}"
                image_box.content = image_placeholder()
                log_exception("local_zip", f"read failed {zip_path} member={member}: {ex}")
            finally:
                request_update(page)

        page.run_thread(worker)

    def move(delta: int):
        next_index = state["index"] + delta
        if 0 <= next_index < len(members):
            state["index"] = next_index
            load_current()

    prev_btn.on_click = lambda e: move(-1)
    next_btn.on_click = lambda e: move(1)

    load_current(update=False)

    return ft.Column(
        [
            ft.Row(
                [
                    ft.Button("返回", icon=ft.Icons.ARROW_BACK, on_click=lambda e: on_back()),
                    title,
                    ft.Row([prev_btn, next_btn], spacing=4),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            status,
            image_box,
        ],
        spacing=8,
        expand=True,
    )
