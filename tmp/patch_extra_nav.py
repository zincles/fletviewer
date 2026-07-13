from pathlib import Path

path = Path("app/main.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        """        if indicator is not None:
            indicator.left = bottom_nav_indexes.get(value, 0) * 71
""",
        """        if indicator is not None:
            indicator.left = nav_state["bottom_nav_indexes"].get(value, 0) * 71
""",
    ),
    (
        """            target_index = section_indexes.get(value, 0)
""",
        """            target_index = nav_state["section_indexes"].get(value, 0)
""",
    ),
    (
        """        try:
            target_index = [PAGES[idx][0] for idx in READING_PAGE_INDEXES].index(label)
        except ValueError:
            return
        if tabs.selected_index != target_index:
""",
        """        pages = nav_state["pages"]
        reading_indexes = nav_state["reading_indexes"]
        try:
            target_index = [pages[idx][0] for idx in reading_indexes].index(label)
        except ValueError:
            return
        if tabs.selected_index != target_index:
""",
    ),
    (
        """    def set_reading_tab_content(label: str, control: ft.Control) -> None:
        \"\"\"让阅读 Tab 持续持有自己的控件树，切换时不卸载和重绘。\"\"\"
        try:
            target_index = [PAGES[idx][0] for idx in READING_PAGE_INDEXES].index(label)
        except ValueError:
            return
""",
        """    def set_reading_tab_content(label: str, control: ft.Control) -> None:
        \"\"\"让阅读 Tab 持续持有自己的控件树，切换时不卸载和重绘。\"\"\"
        pages = nav_state["pages"]
        reading_indexes = nav_state["reading_indexes"]
        try:
            target_index = [pages[idx][0] for idx in reading_indexes].index(label)
        except ValueError:
            return
""",
    ),
    (
        """    def render(idx):
        if idx is None or idx < 0 or idx >= len(PAGES):
            log_debug("导航", f"忽略无效导航索引 索引={idx}")
            return
        started_at = time.perf_counter()
        result_pump.prioritize_navigation()
        label, subtitle, icon, view_fn = PAGES[idx]
""",
        """    def render(idx):
        pages = nav_state["pages"]
        if idx is None or idx < 0 or idx >= len(pages):
            log_debug("导航", f"忽略无效导航索引 索引={idx}")
            return
        started_at = time.perf_counter()
        result_pump.prioritize_navigation()
        label, subtitle, icon, view_fn = pages[idx]
""",
    ),
    (
        """        if label in {"文件", "调试"} and label in section_indexes:
""",
        """        if label in {"文件", "调试"} and label in nav_state["section_indexes"]:
""",
    ),
    (
        """    def render_label(label: str):
        for idx, (page_label, _subtitle, _icon, _view_fn) in enumerate(PAGES):
            if page_label == label:
                render(idx)
                return
        log_debug("导航", f"忽略无效导航标签 标签={label}")
""",
        """    def render_label(label: str):
        for idx, (page_label, _subtitle, _icon, _view_fn) in enumerate(nav_state["pages"]):
            if page_label == label:
                render(idx)
                return
        log_debug("导航", f"忽略无效导航标签 标签={label}")
""",
    ),
    (
        """    if "文件" in extra_sections:
        bottom_nav_items.append(bottom_nav_segment("文件", ft.Icons.FOLDER_OPEN, "文件"))
    if "调试" in extra_sections:
        bottom_nav_items.append(bottom_nav_segment("调试", ft.Icons.BUG_REPORT, "调试"))
""",
        """    if "文件" in nav_state["extra_sections"]:
        bottom_nav_items.append(bottom_nav_segment("文件", ft.Icons.FOLDER_OPEN, "文件"))
    if "调试" in nav_state["extra_sections"]:
        bottom_nav_items.append(bottom_nav_segment("调试", ft.Icons.BUG_REPORT, "调试"))
""",
    ),
    (
        """        selected_index = int(getattr(e.control, "selected_index", 0) or 0)
        if selected_index < 0 or selected_index >= len(root_section_order):
            render_label("主页")
            return
        section = root_section_order[selected_index]
""",
        """        selected_index = int(getattr(e.control, "selected_index", 0) or 0)
        order = nav_state["root_section_order"]
        if selected_index < 0 or selected_index >= len(order):
            render_label("主页")
            return
        section = order[selected_index]
""",
    ),
    (
        """        if selected_index < 0 or selected_index >= len(READING_PAGE_INDEXES):
            return
        render(READING_PAGE_INDEXES[selected_index])
""",
        """        reading_indexes = nav_state["reading_indexes"]
        if selected_index < 0 or selected_index >= len(reading_indexes):
            return
        render(reading_indexes[selected_index])
""",
    ),
    (
        """    reading_tab_pages[:] = [ft.Container(expand=True, padding=ft.Padding(0, 8, 0, 0)) for _idx in READING_PAGE_INDEXES]
""",
        """    reading_tab_pages[:] = [ft.Container(expand=True, padding=ft.Padding(0, 8, 0, 0)) for _idx in nav_state["reading_indexes"]]
""",
    ),
    (
        """        tabs=[ft.Tab(label=PAGES[idx][0]) for idx in READING_PAGE_INDEXES],
""",
        """        tabs=[ft.Tab(label=nav_state["pages"][idx][0]) for idx in nav_state["reading_indexes"]],
""",
    ),
    (
        """        length=len(READING_PAGE_INDEXES),
""",
        """        length=len(nav_state["reading_indexes"]),
""",
    ),
    (
        """    root_tab_controls = [reading_section, local_section, downloads_section]
    for key in extra_sections:
        root_tab_controls.append(extra_sections_map[key])
    root_tab_controls.append(settings_section)
""",
        """    root_tab_controls = [reading_section, local_section, downloads_section]
    for key in nav_state["extra_sections"]:
        root_tab_controls.append(extra_sections_map[key])
    root_tab_controls.append(settings_section)
""",
    ),
    (
        """    body = ft.Stack(
        controls=[
            ft.Row(
                [
                    root_tabs,
                ],
                expand=True,
            ),
            bottom_nav_host,
        ],
        expand=True,
    )
""",
        """    root_tabs_row = ft.Row([root_tabs], expand=True)
    root_tabs_row_ref = {"value": root_tabs_row}
    body = ft.Stack(
        controls=[
            root_tabs_row,
            bottom_nav_host,
        ],
        expand=True,
    )
""",
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit(f"missing block:\n{old[:120]}")
    text = text.replace(old, new, 1)

marker = '    root_tabs_ref["value"] = root_tabs\n'
if "rebuild_extra_sections" not in text:
    if marker not in text:
        raise SystemExit("root_tabs_ref marker missing")
    insert = marker + '''
    def rebuild_extra_sections(*, update: bool = True) -> None:
        """根据设置立即重建底栏附加面板和根分区。"""
        nonlocal PAGES, READING_PAGE_INDEXES, root_section_order, section_indexes, bottom_nav_indexes, root_tabs
        previous = bottom_nav_state.get("value") or "阅读"
        nav_state["extra_sections"] = _enabled_extra_sections()
        refresh_nav_maps()
        PAGES = nav_state["pages"]
        READING_PAGE_INDEXES = nav_state["reading_indexes"]
        root_section_order = nav_state["root_section_order"]
        section_indexes = nav_state["section_indexes"]
        bottom_nav_indexes = nav_state["bottom_nav_indexes"]

        bottom_nav_segments.clear()
        items = [
            bottom_nav_segment("阅读", ft.Icons.PUBLIC, "主页"),
            bottom_nav_segment("本地", ft.Icons.FOLDER, "本地画廊"),
            bottom_nav_segment("下载", ft.Icons.DOWNLOAD, "下载"),
        ]
        if "文件" in nav_state["extra_sections"]:
            items.append(bottom_nav_segment("文件", ft.Icons.FOLDER_OPEN, "文件"))
        if "调试" in nav_state["extra_sections"]:
            items.append(bottom_nav_segment("调试", ft.Icons.BUG_REPORT, "调试"))
        items.append(bottom_nav_segment("设置", ft.Icons.SETTINGS, "设置"))
        width = max(1, len(items)) * 71
        bottom_nav.content = ft.Stack(
            [
                bottom_nav_indicator,
                ft.Row(items, alignment=ft.MainAxisAlignment.CENTER, spacing=3, tight=True),
            ],
            width=width,
            height=54,
        )

        controls = [reading_section, local_section, downloads_section]
        for key in nav_state["extra_sections"]:
            controls.append(extra_sections_map[key])
        controls.append(settings_section)
        selected = previous if previous in nav_state["section_indexes"] else "设置"
        root_tabs = ft.Tabs(
            content=ft.TabBarView(controls=controls, expand=True),
            length=len(controls),
            selected_index=nav_state["section_indexes"].get(selected, 0),
            animation_duration=180,
            on_change=on_root_tabs_change,
            expand=True,
        )
        root_tabs_ref["value"] = root_tabs
        row = root_tabs_row_ref.get("value")
        if row is not None:
            row.controls = [root_tabs]
        if previous not in nav_state["section_indexes"]:
            bottom_nav_state["value"] = "设置"
        set_bottom_nav(bottom_nav_state["value"])
        if update:
            request_update(page)

    page.fletviewer_rebuild_extra_sections = rebuild_extra_sections
'''
    text = text.replace(marker, insert, 1)

path.write_text(text, encoding="utf-8")
print("ok")
