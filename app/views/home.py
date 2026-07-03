from app.views.gallery_list import create_view as make_view


def create_view(page):
    return make_view(
        title="主页",
        subtitle="最新画廊",
        call_fn=lambda c: c.get_latest(),
        needs_login=False,
    )(page)
