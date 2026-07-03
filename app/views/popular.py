from app.views.gallery_list import create_view as make_view


def create_view(page):
    return make_view(
        title="热门",
        subtitle="热门画廊",
        call_fn=lambda c: c.get_popular(),
        needs_login=False,
    )(page)
