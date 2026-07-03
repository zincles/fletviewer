from app.views.gallery_list import create_view as make_view


def create_view(page):
    return make_view(
        title="排行榜",
        subtitle="排行榜 — 昨日",
        call_fn=lambda c: c.get_toplist(option="15-yesterday"),
        needs_login=False,
    )(page)
