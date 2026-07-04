from app.views.gallery_cards import create_gallery_cards_view


def create_view(page):
    return create_gallery_cards_view(
        title="排行榜",
        subtitle="排行榜 — 昨日",
        load_fn=lambda client, page_url: client.search(page_url=page_url)
        if page_url
        else client.get_toplist(option="15-yesterday"),
        needs_login=False,
    )(page)
