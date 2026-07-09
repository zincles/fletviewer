import flet as ft

from app.storage import get_theme_color, get_theme_mode


COLOR_SEEDS = {
    "teal": "#006A60",
    "blue": "#006CBA",
    "green": "#386A20",
    "rose": "#BA1A1A",
    "amber": "#7A5900",
    "violet": "#6750A4",
}

ADAPTIVE_LIGHT_SEEDS = {
    "android": "#006A60",
    "ios": "#006CBA",
    "mac": "#006CBA",
    "windows": "#006CBA",
    "linux": "#386A20",
    "web": "#006A60",
}
ADAPTIVE_DARK_SEEDS = {
    "android": "#8CCDBF",
    "ios": "#A9C7FF",
    "mac": "#A9C7FF",
    "windows": "#A9C7FF",
    "linux": "#A6D785",
    "web": "#8CCDBF",
}


def _theme_mode_value(mode: str) -> ft.ThemeMode:
    if mode == "light":
        return ft.ThemeMode.LIGHT
    if mode == "dark":
        return ft.ThemeMode.DARK
    return ft.ThemeMode.SYSTEM


def _platform_key(page: ft.Page) -> str:
    if page.web:
        return "web"
    value = str(getattr(page, "platform", "") or "").lower()
    if "android" in value:
        return "android"
    if "ios" in value:
        return "ios"
    if "mac" in value or "darwin" in value:
        return "mac"
    if "windows" in value:
        return "windows"
    if "linux" in value:
        return "linux"
    return "web"


def _seed_for(page: ft.Page, dark: bool) -> str:
    color = get_theme_color()
    if color != "adaptive":
        return COLOR_SEEDS.get(color, COLOR_SEEDS["teal"])
    platform = _platform_key(page)
    seeds = ADAPTIVE_DARK_SEEDS if dark else ADAPTIVE_LIGHT_SEEDS
    return seeds.get(platform, seeds["web"])


def _page_transitions() -> ft.PageTransitionsTheme:
    return ft.PageTransitionsTheme(android=ft.PageTransitionTheme.PREDICTIVE)


def _build_theme(page: ft.Page, dark: bool) -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=_seed_for(page, dark),
        use_material3=True,
        scaffold_bgcolor=ft.Colors.SURFACE,
        page_transitions=_page_transitions(),
    )


def apply_app_theme(page: ft.Page, update: bool = False) -> None:
    """Apply the app-wide Material 3 theme from persisted settings."""
    mode = get_theme_mode()
    page.theme_mode = _theme_mode_value(mode)
    page.theme = _build_theme(page, dark=False)
    page.dark_theme = _build_theme(page, dark=True)
    page.bgcolor = ft.Colors.SURFACE
    if update:
        page.update()


def refresh_adaptive_theme_on_brightness_change(page: ft.Page) -> None:
    """Refresh adaptive color when the host reports a system brightness change."""
    if get_theme_color() == "adaptive":
        apply_app_theme(page, update=True)
