from pathlib import Path

path = Path("app/main.py")
text = path.read_text(encoding="utf-8")

anchor = '''    bottom_nav_for_page = {
        "本地画廊": "本地",
        "下载": "下载",
        "文件": "文件",
        "调试": "调试",
        "设置": "设置",
    }

    def set_bottom_nav(value: str):
'''
insert = '''    bottom_nav_for_page = {
        "本地画廊": "本地",
        "下载": "下载",
        "文件": "文件",
        "调试": "调试",
        "设置": "设置",
    }
    bottom_nav_metrics = {"count": 4, "item_width": 68, "spacing": 3, "stride": 71}

    def bottom_nav_layout(count: int) -> tuple[int, int, int]:
        """按钮多时收缩宽度和间距，避免底栏溢出。"""
        count = max(1, int(count))
        if count <= 4:
            item_width, spacing = 68, 3
        elif count == 5:
            item_width, spacing = 58, 2
        else:
            item_width, spacing = 50, 1
        stride = item_width + spacing
        bottom_nav_metrics.update(count=count, item_width=item_width, spacing=spacing, stride=stride)
        return item_width, spacing, stride

    def set_bottom_nav(value: str):
'''
if anchor not in text:
    raise SystemExit("anchor missing")
text = text.replace(anchor, insert, 1)

text = text.replace(
    '            indicator.left = nav_state["bottom_nav_indexes"].get(value, 0) * 71\n',
    '            indicator.left = nav_state["bottom_nav_indexes"].get(value, 0) * bottom_nav_metrics["stride"]\n',
    1,
)

old = '''    def bottom_nav_segment(label: str, icon, target: str) -> ft.Container:
        selected = label == bottom_nav_state["value"]
        color = ft.Colors.ON_PRIMARY if selected else ft.Colors.ON_SURFACE_VARIANT
        segment = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, size=20, color=color),
                    ft.Text(
                        label,
                        size=11,
                        weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                        color=color,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=1,
            ),
            width=68,
            height=54,
'''
new = '''    def bottom_nav_segment(label: str, icon, target: str) -> ft.Container:
        selected = label == bottom_nav_state["value"]
        color = ft.Colors.ON_PRIMARY if selected else ft.Colors.ON_SURFACE_VARIANT
        item_width = bottom_nav_metrics["item_width"]
        segment = ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, size=18 if item_width < 56 else 20, color=color),
                    ft.Text(
                        label,
                        size=10 if item_width < 56 else 11,
                        weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                        color=color,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=1,
            ),
            width=item_width,
            height=54,
'''
if old not in text:
    raise SystemExit("segment block missing")
text = text.replace(old, new, 1)

text = text.replace(
    '''    bottom_nav_indicator = ft.Container(
        width=68,
        height=54,
''',
    '''    bottom_nav_indicator = ft.Container(
        width=bottom_nav_metrics["item_width"],
        height=54,
''',
    1,
)

old = '''    bottom_nav_items = [
        bottom_nav_segment("阅读", ft.Icons.PUBLIC, "主页"),
        bottom_nav_segment("本地", ft.Icons.FOLDER, "本地画廊"),
        bottom_nav_segment("下载", ft.Icons.DOWNLOAD, "下载"),
    ]
    if "文件" in nav_state["extra_sections"]:
        bottom_nav_items.append(bottom_nav_segment("文件", ft.Icons.FOLDER_OPEN, "文件"))
    if "调试" in nav_state["extra_sections"]:
        bottom_nav_items.append(bottom_nav_segment("调试", ft.Icons.BUG_REPORT, "调试"))
    bottom_nav_items.append(bottom_nav_segment("设置", ft.Icons.SETTINGS, "设置"))
    bottom_nav_width = max(1, len(bottom_nav_items)) * 71
    bottom_nav = ft.Container(
        content=ft.Stack(
            [
                bottom_nav_indicator,
                ft.Row(
                    bottom_nav_items,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=3,
                    tight=True,
                ),
            ],
            width=bottom_nav_width,
            height=54,
        ),
'''
new = '''    planned_count = 4 + len(nav_state["extra_sections"])
    item_width, spacing, stride = bottom_nav_layout(planned_count)
    bottom_nav_indicator.width = item_width
    bottom_nav_items = [
        bottom_nav_segment("阅读", ft.Icons.PUBLIC, "主页"),
        bottom_nav_segment("本地", ft.Icons.FOLDER, "本地画廊"),
        bottom_nav_segment("下载", ft.Icons.DOWNLOAD, "下载"),
    ]
    if "文件" in nav_state["extra_sections"]:
        bottom_nav_items.append(bottom_nav_segment("文件", ft.Icons.FOLDER_OPEN, "文件"))
    if "调试" in nav_state["extra_sections"]:
        bottom_nav_items.append(bottom_nav_segment("调试", ft.Icons.BUG_REPORT, "调试"))
    bottom_nav_items.append(bottom_nav_segment("设置", ft.Icons.SETTINGS, "设置"))
    bottom_nav_width = max(1, len(bottom_nav_items)) * stride - spacing
    bottom_nav = ft.Container(
        content=ft.Stack(
            [
                bottom_nav_indicator,
                ft.Row(
                    bottom_nav_items,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=spacing,
                    tight=True,
                ),
            ],
            width=bottom_nav_width,
            height=54,
        ),
'''
if old not in text:
    raise SystemExit("initial bottom nav missing")
text = text.replace(old, new, 1)

old = '''        bottom_nav_segments.clear()
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
'''
new = '''        bottom_nav_segments.clear()
        planned = 4 + len(nav_state["extra_sections"])
        item_width, spacing, stride = bottom_nav_layout(planned)
        bottom_nav_indicator.width = item_width
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
        width = max(1, len(items)) * stride - spacing
        bottom_nav.content = ft.Stack(
            [
                bottom_nav_indicator,
                ft.Row(items, alignment=ft.MainAxisAlignment.CENTER, spacing=spacing, tight=True),
            ],
            width=width,
            height=54,
        )
'''
if old not in text:
    raise SystemExit("rebuild bottom nav missing")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("ok")
