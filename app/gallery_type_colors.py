import re

import flet as ft


GALLERY_TYPE_COLORS = {
    "DOUJINSHI": ft.Colors.RED,
    "IMAGESET": ft.Colors.BLUE,
    "NONH": ft.Colors.LIGHT_BLUE,
    "GAMECG": ft.Colors.GREEN,
    "ARTISTCG": ft.Colors.YELLOW,
    "MANGA": ft.Colors.ORANGE,
    "COSPLAY": ft.Colors.PURPLE,
    "MISC": ft.Colors.PINK,
    "WESTERN": ft.Colors.LIGHT_GREEN,
    "ASIANPORN": ft.Colors.PURPLE_200,
}

GALLERY_TYPE_LABELS = {
    "DOUJINSHI": "DOUJINSHI",
    "IMAGESET": "IMAGESET",
    "NONH": "NON-H",
    "GAMECG": "GAMECG",
    "ARTISTCG": "ARTISTCG",
    "MANGA": "MANGA",
    "COSPLAY": "COSPLAY",
    "MISC": "MISC",
    "WESTERN": "WESTERN",
    "ASIANPORN": "ASIAN PORN",
}


def normalize_gallery_type(value: str | None) -> str:
    """把 provider 类型名归一化为配色表键名。"""
    return re.sub(r"[^A-Z0-9]", "", (value or "").strip().upper())


def gallery_type_color(value: str | None):
    """返回画廊类型颜色；未知类型回退到当前主题主色。"""
    return GALLERY_TYPE_COLORS.get(normalize_gallery_type(value), ft.Colors.PRIMARY)


def gallery_type_foreground(value: str | None):
    """返回适合类型底色的前景色。"""
    key = normalize_gallery_type(value)
    return ft.Colors.BLACK if key in {"ARTISTCG", "WESTERN", "ASIANPORN"} else ft.Colors.WHITE
