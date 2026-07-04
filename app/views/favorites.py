from app.views.gallery_debug import create_gallery_view


def create_view(page):
    return create_gallery_view(
        title="收藏",
        subtitle="E-Hentai 收藏列表",
        load_fn=lambda client, page_url: client.get_favorites(page_url=page_url),
        needs_login=True,
    )(page)
