import flet as ft
import asyncio


async def main(page: ft.Page):
    page.title = "FletViewer — 存储系统测试"
    page.padding = 40
    page.scroll = ft.ScrollMode.AUTO

    log = ft.Column(spacing=4)

    def add_log(text):
        log.controls.append(ft.Text(text, selectable=True))
        page.update()

    # --- SharedPreferences ---
    sp = page.shared_preferences
    add_log(f"SharedPreferences 类型: {type(sp).__name__}")

    await sp.set("test_key", "你好，Flet！")
    val = await sp.get("test_key")
    add_log(f"SP 读写: test_key = {val!r}")

    exists = await sp.contains_key("test_key")
    add_log(f"SP contains_key: {exists}")

    await sp.set("counter", 42)
    add_log(f"SP counter = {await sp.get('counter')}")

    keys = await sp.get_keys("")
    add_log(f"SP 所有键: {keys}")

    # --- StoragePaths ---
    sp_paths = page.storage_paths
    add_log(f"\nStoragePaths 类型: {type(sp_paths).__name__}")
    add_log(f"当前平台: {page.platform}")
    add_log(f"是否 Web: {page.web}")

    if not page.web:
        try:
            cache = await sp_paths.get_application_cache_directory()
            add_log(f"缓存目录: {cache}")
        except Exception as e:
            add_log(f"缓存目录: <{e}>")

        try:
            docs = await sp_paths.get_application_documents_directory()
            add_log(f"文档目录: {docs}")
        except Exception as e:
            add_log(f"文档目录: <{e}>")

        try:
            support = await sp_paths.get_application_support_directory()
            add_log(f"支持目录: {support}")
        except Exception as e:
            add_log(f"支持目录: <{e}>")

        try:
            downloads = await sp_paths.get_downloads_directory()
            add_log(f"下载目录: {downloads}")
        except Exception as e:
            add_log(f"下载目录: <{e}>")

        try:
            temp = await sp_paths.get_temporary_directory()
            add_log(f"临时目录: {temp}")
        except Exception as e:
            add_log(f"临时目录: <{e}>")

        # 平台特有
        if page.platform == ft.PagePlatform.ANDROID:
            try:
                ext = await sp_paths.get_external_storage_directory()
                add_log(f"外部存储: {ext}")
            except Exception as e:
                add_log(f"外部存储: <{e}>")
    else:
        add_log("Web 模式: StoragePaths 不可用")

    page.add(
        ft.Text("存储系统测试", size=24, weight=ft.FontWeight.BOLD),
        ft.Container(
            content=log,
            padding=20,
            border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
        ),
    )


if __name__ == "__main__":
    ft.run(main)
