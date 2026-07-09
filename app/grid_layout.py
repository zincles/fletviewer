from app.storage import get_gallery_grid_columns


DEFAULT_WIDTH_DEDUCTION = 200


def runs_count_for_width(
    width: float | int | None,
    *,
    target_width: int | None = None,
    min_columns: int = 2,
    max_columns: int = 10,
    width_deduction: int = DEFAULT_WIDTH_DEDUCTION,
) -> int:
    """根据设置中的画廊列数返回 GridView 应显示的列数。"""
    columns = get_gallery_grid_columns()
    return max(min_columns, min(max_columns, columns))
