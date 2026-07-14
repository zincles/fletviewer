from dataclasses import field
from typing import Optional

import flet as ft


@ft.control("FletviewerImageReader")
class FletviewerImageReader(ft.LayoutControl):
    """Minimal native image reader with paging and pinch-to-zoom."""

    urls: list[str] = field(default_factory=list)
    initial_index: int = 0
    min_scale: float = 1.0
    max_scale: float = 4.0
    on_change: Optional[ft.ControlEventHandler["FletviewerImageReader"]] = None
