from app.storage import get_image_grid_target_width


DEFAULT_WIDTH_DEDUCTION = 200


def runs_count_for_width(
    width: float | int | None,
    *,
    target_width: int | None = None,
    min_columns: int = 2,
    max_columns: int = 10,
    width_deduction: int = DEFAULT_WIDTH_DEDUCTION,
) -> int:
    """根据窗口宽度和参考卡片宽度计算 GridView 应显示的列数。"""
    target = target_width or get_image_grid_target_width()
    available = max(float(target) * min_columns, float(width or 1280) - width_deduction)
    columns = round(available / target)
    return max(min_columns, min(max_columns, columns))
