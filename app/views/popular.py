from app.views.gallery_debug import create_gallery_view


def create_view(page):
    """创建热门画廊视图。"""
    return create_gallery_view(
        title="热门",
        subtitle="热门画廊",
        load_fn=lambda client, page_url: client.get_popular(page_url=page_url),
        needs_login=False,
    )(page)
