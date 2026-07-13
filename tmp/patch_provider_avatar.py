from pathlib import Path

path = Path("app/main.py")
text = path.read_text(encoding="utf-8")

if "pixiv_home" not in text:
    text = text.replace(
        "from app.views.home import create_view as home_view\n",
        "from app.views.home import create_view as home_view\nfrom app.views.pixiv_home import create_view as pixiv_home_view\n",
        1,
    )

start = text.find("    def show_account_summary(e=None) -> None:")
end = text.find("    reading_top_row = ft.Container(")
if start < 0 or end < 0:
    raise SystemExit(f"blocks missing start={start} end={end}")

# include reading_top_row old definition until its closing pattern before top_bar
end2 = text.find("    top_bar = ft.Container(", end)
if end2 < 0:
    raise SystemExit("top_bar missing")

new_block = '''    active_provider = {"value": "ehentai"}

    def provider_label(provider: str | None = None) -> str:
        key = provider or active_provider["value"]
        return {
            "ehentai": "E-Hentai",
            "pixiv": "Pixiv",
            "exhentai": "ExHentai",
            "booru": "Booru",
        }.get(key, key)

    def apply_provider(provider: str, *, update: bool = True) -> None:
        """切换阅读 Provider，并刷新主页内容。"""
        if provider not in {"ehentai", "pixiv"}:
            return
        if active_provider["value"] == provider and update:
            try:
                page.pop_dialog()
            except Exception:
                pass
            return
        active_provider["value"] = provider
        home_idx = next((idx for idx, item in enumerate(nav_state["pages"]) if item[0] == "主页"), 0)
        home_key = f"page:{home_idx}"
        if provider == "pixiv":
            view_cache[home_key] = pixiv_home_view(page)
            if top_search_hint_ref.get("value") is not None:
                top_search_hint_ref["value"].value = "搜索 Pixiv（即将支持）"
        else:
            view_cache.pop(home_key, None)
            if top_search_hint_ref.get("value") is not None:
                top_search_hint_ref["value"].value = "搜索 E-Hentai"
        account_avatar_button.tooltip = f"账户与平台 · 当前 {provider_label(provider)}"
        try:
            page.pop_dialog()
        except Exception:
            pass
        render_label("主页")
        if update:
            request_update(page)

    def show_account_summary(e=None) -> None:
        """账户摘要 + Provider 切换入口。"""
        logged_in = browser_session.login_status_level() in {"ok", "pending"}
        value = "待同步" if logged_in else "--"
        current = active_provider["value"]

        def metric(label: str, icon) -> ft.Control:
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(icon, size=20, color=ft.Colors.PRIMARY),
                        ft.Text(value, size=16, weight=ft.FontWeight.BOLD),
                        ft.Text(label, size=11, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
                    ],
                    spacing=4,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                width=112,
                padding=10,
                border_radius=14,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            )

        def provider_tile(key: str, title: str, subtitle: str, icon, *, enabled: bool = True) -> ft.Control:
            selected = current == key
            return ft.ListTile(
                leading=ft.Icon(icon, color=ft.Colors.PRIMARY if selected else None),
                title=ft.Text(title),
                subtitle=ft.Text(
                    "当前平台" if selected else subtitle,
                    color=ft.Colors.PRIMARY if selected else ft.Colors.ON_SURFACE_VARIANT,
                ),
                trailing=ft.Icon(ft.Icons.CHECK, color=ft.Colors.PRIMARY) if selected else None,
                selected=selected,
                disabled=not enabled,
                on_click=(lambda e, provider=key: apply_provider(provider)) if enabled else None,
            )

        # TODO: 在 core provider 增加账户资产接口，填充 GP、Credit、HatH 和每周免费归档配额。
        dialog = ft.AlertDialog(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [ft.IconButton(ft.Icons.CLOSE, tooltip="关闭", on_click=lambda event: page.pop_dialog())],
                            alignment=ft.MainAxisAlignment.START,
                        ),
                        ft.Container(
                            content=ft.Icon(ft.Icons.PERSON, size=54, color=ft.Colors.ON_PRIMARY_CONTAINER),
                            width=96,
                            height=96,
                            border_radius=999,
                            bgcolor=ft.Colors.PRIMARY_CONTAINER,
                            alignment=ft.Alignment(0, 0),
                        ),
                        ft.Text(
                            browser_session.login_status_text(),
                            size=14,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(f"当前平台：{provider_label(current)}", size=13, weight=ft.FontWeight.W_600),
                        ft.Row(
                            [
                                metric("GP", ft.Icons.PAID),
                                metric("Credit", ft.Icons.ACCOUNT_BALANCE_WALLET),
                                metric("HatH", ft.Icons.DNS),
                                metric("每周免费归档", ft.Icons.INVENTORY_2),
                            ],
                            spacing=8,
                            run_spacing=8,
                            wrap=True,
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        ft.Text(
                            "登录后可查看账户资产。" if not logged_in else "账户资产接口尚未接入。",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Divider(),
                        ft.Text("切换平台", size=14, weight=ft.FontWeight.W_600),
                        provider_tile("ehentai", "E-Hentai", "EH 画廊浏览", ft.Icons.PUBLIC, enabled=True),
                        provider_tile("pixiv", "Pixiv", "主页骨架已就绪", ft.Icons.BRUSH, enabled=True),
                        provider_tile("exhentai", "ExHentai", "尚未实现", ft.Icons.LOCK_OUTLINE, enabled=False),
                        provider_tile("booru", "Booru", "尚未实现", ft.Icons.IMAGE_SEARCH, enabled=False),
                    ],
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=500,
                height=560,
            ),
            content_padding=ft.Padding(8, 8, 8, 20),
        )
        dialog.open = True
        page.show_dialog(dialog)

    account_avatar_button = ft.IconButton(
        icon=ft.Icons.ACCOUNT_CIRCLE,
        tooltip="账户与平台 · 当前 E-Hentai",
        on_click=show_account_summary,
    )

    reading_top_row = ft.Container(
        content=ft.Row(
            [
                top_search_field,
                header_actions,
                account_avatar_button,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=50,
        padding=ft.Padding(8, 4, 8, 4),
        bgcolor=ft.Colors.SURFACE,
    )

'''

text = text[:start] + new_block + text[end2:]

text = text.replace(
    'on_long_press=show_provider_selector if label == "设置" else None,\n',
    "on_long_press=None,\n",
)

needle = '''            if cache_key not in view_cache:
                log_debug("导航", f"创建持久阅读视图 {label}")
                view_cache[cache_key] = view_fn(page) if view_fn is not None else ft.Container(expand=True)
'''
repl = '''            if cache_key not in view_cache:
                log_debug("导航", f"创建持久阅读视图 {label}")
                if label == "主页" and active_provider["value"] == "pixiv":
                    view_cache[cache_key] = pixiv_home_view(page)
                else:
                    view_cache[cache_key] = view_fn(page) if view_fn is not None else ft.Container(expand=True)
'''
if needle not in text:
    raise SystemExit("home create branch missing")
text = text.replace(needle, repl, 1)

# remove leftover references
if "show_provider_selector" in text:
    # allow only if none remain
    count = text.count("show_provider_selector")
    if count:
        print("warning leftover show_provider_selector", count)

if "reading_source_button" in text:
    print("warning leftover reading_source_button")

path.write_text(text, encoding="utf-8")
print("patched")
