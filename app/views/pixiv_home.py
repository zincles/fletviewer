from app.views.pixiv_pages import create_home_view


def create_view(page):
    """兼容旧入口：Pixiv 主页。"""
    return create_home_view(page)
