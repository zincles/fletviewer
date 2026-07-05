from app.views.gallery_debug import create_gallery_view


def create_view(page):
    """创建订阅/关注画廊视图。"""
    return create_gallery_view(
        title="订阅",
        subtitle="关注的标签画廊（需登录）",
        load_fn=lambda client, page_url: client.get_watched(page_url=page_url),
        needs_login=True,
    )(page)
