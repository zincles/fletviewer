from app.views.gallery_cards import create_gallery_cards_view


def create_view(page):
    return create_gallery_cards_view(
        title="主页",
        subtitle="最新画廊",
        load_fn=lambda client, page_url: client.get_latest(page_url=page_url),
        needs_login=False,
    )(page)
