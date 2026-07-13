from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ViewerState:
    """UI-independent navigation and request generations for an image viewer."""

    item_count: int
    index: int = 0
    mode: str = "paged"
    alive: bool = False
    paged_generation: int = 0
    vertical_generation: int = 0
    overlay_generation: int = 0
    last_overlay_activity: float = 0.0
    current_url: str = ""
    current_path: Path | None = None
    current_data: bytes | None = None
    current_mime: str = ""

    def __post_init__(self) -> None:
        self.item_count = max(0, self.item_count)
        self.index = self.clamp_index(self.index)
        if self.mode not in ("paged", "vertical"):
            self.mode = "paged"

    def clamp_index(self, index: int) -> int:
        if self.item_count == 0:
            return 0
        return max(0, min(index, self.item_count - 1))

    def set_index(self, index: int) -> int:
        self.index = self.clamp_index(index)
        return self.index

    def move(self, delta: int) -> bool:
        next_index = self.index + delta
        if not 0 <= next_index < self.item_count:
            return False
        self.index = next_index
        return True

    def clear_current_image(self) -> None:
        self.current_url = ""
        self.current_path = None
        self.current_data = None
        self.current_mime = ""

    def start_paged_request(self) -> int:
        self.paged_generation += 1
        return self.paged_generation

    def enter_paged(self) -> None:
        self.mode = "paged"
        self.vertical_generation += 1

    def enter_vertical(self) -> int:
        self.mode = "vertical"
        self.paged_generation += 1
        self.vertical_generation += 1
        return self.vertical_generation

    def stop(self) -> None:
        self.alive = False
        self.paged_generation += 1
        self.vertical_generation += 1
        self.overlay_generation += 1
        self.current_data = None

    def index_for_scroll(self, offsets: list[int], pixels: float) -> int:
        index = 0
        for candidate, top in enumerate(offsets):
            if top > pixels:
                break
            index = candidate
        return self.set_index(index)

    def vertical_window(
        self,
        offsets: list[int],
        heights: list[int],
        pixels: float,
        viewport: float,
        *,
        buffer: float,
        adjacent_pages: int,
    ) -> set[int]:
        if self.item_count == 0:
            return set()
        start = max(0.0, pixels - buffer)
        end = pixels + max(viewport, 600.0) + buffer
        visible: set[int] = set()
        for index, (top, height) in enumerate(zip(offsets, heights)):
            if top + height < start:
                continue
            if top > end:
                break
            visible.add(index)
        visible.update(
            range(
                max(0, self.index - adjacent_pages),
                min(self.item_count, self.index + adjacent_pages + 1),
            )
        )
        return visible
