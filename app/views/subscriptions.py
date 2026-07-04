from app.views.gallery_cards import create_gallery_cards_view


def create_view(page):
    return create_gallery_cards_view(
        title="订阅",
        subtitle="关注的标签画廊（需登录）",
        load_fn=lambda client, page_url: client.get_watched(page_url=page_url),
        needs_login=True,
    )(page)
