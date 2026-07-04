from app.views.gallery_cards import create_gallery_cards_view


def create_view(page):
    return create_gallery_cards_view(
        title="收藏",
        subtitle="E-Hentai 收藏列表",
        load_fn=lambda client, page_url: client.get_favorites(page_url=page_url),
        needs_login=True,
    )(page)
