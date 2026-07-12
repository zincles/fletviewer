import re
import threading
import zipfile
from pathlib import Path

import flet as ft

from core.image.fetcher import ImageFetchCancelled
from app.views.image_viewer import ImageViewerItem, ViewerImageResult, create_view as create_image_viewer


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_MAX_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_IMAGE_MEMBERS = 100_000
_MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024 * 1024


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _is_image_member(name: str) -> bool:
    path = Path(name)
    return (
        "__MACOSX" not in path.parts
        and not any(part.startswith(".") for part in path.parts)
        and name.lower().endswith(_IMAGE_EXTS)
    )


def _mime_for_name(name: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(Path(name).suffix.lower(), "application/octet-stream")


def _list_images(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        images = [info for info in archive.infolist() if not info.is_dir() and _is_image_member(info.filename)]
        if len(images) > _MAX_IMAGE_MEMBERS:
            raise ValueError(f"归档图片数量过多：{len(images)}")
        total_size = sum(info.file_size for info in images)
        if total_size > _MAX_TOTAL_IMAGE_BYTES:
            raise ValueError(f"归档声明的图片总大小过大：{total_size} bytes")
        names = [info.filename for info in sorted(images, key=lambda info: _natural_key(info.filename))]
        if len(names) != len(set(names)):
            raise ValueError("归档包含重复的图片文件名")
        return names


def _read_member(zip_path: Path, member: str, cancel_event: threading.Event | None = None) -> bytes:
    with zipfile.ZipFile(zip_path) as archive:
        info = archive.getinfo(member)
        if info.file_size > _MAX_MEMBER_BYTES:
            raise ValueError(f"图片过大，拒绝解压: {info.file_size} bytes")
        chunks: list[bytes] = []
        bytes_read = 0
        with archive.open(info) as source:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImageFetchCancelled("图像加载已取消")
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read > _MAX_MEMBER_BYTES:
                    raise ValueError(f"图片实际解压大小过大: {bytes_read} bytes")
                chunks.append(chunk)
        return b"".join(chunks)


def create_view(page: ft.Page, zip_path: Path, title_text: str, on_back) -> ft.Control:
    try:
        members = _list_images(zip_path) if zip_path.is_file() else []
    except (OSError, ValueError, zipfile.BadZipFile):
        members = []
    items = [
        ImageViewerItem(
            url=f"zip://{zip_path.name}/{member}",
            title=f"{title_text} #{index + 1}",
            detail={"provider": "local_zip", "archive": str(zip_path), "member": member},
        )
        for index, member in enumerate(members)
    ]

    def load_image(item: ImageViewerItem, _index: int, cancel_event: threading.Event) -> ViewerImageResult:
        member = str(item.detail["member"])
        return ViewerImageResult(
            data=_read_member(zip_path, member, cancel_event),
            mime=_mime_for_name(member),
            url=item.url,
        )

    return create_image_viewer(page, items, 0, on_back, load_image=load_image)
