from app.views.gallery_list import create_view as make_view


def create_view(page):
    return make_view(
        title="订阅",
        subtitle="关注的标签画廊（需登录）",
        call_fn=lambda c: c.get_watched(),
        needs_login=True,
    )(page)
