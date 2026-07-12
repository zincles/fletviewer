"""
ehgrabber.py — E-Hentai / ExHentai Python Library

单文件库，提供搜索、标签获取、归档下载、逐页抓取等功能。

移植自 Venera 的 eh_grabber.js。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

EH_CATEGORIES: list[str] = [
    "misc", "doujinshi", "manga", "artist cg",
    "game cg", "image set", "cosplay", "asian porn",
    "non-h", "western",
]

EH_API_EH = "https://api.e-hentai.org/api.php"
EH_API_EX = "https://exhentai.org/api.php"

EH_DOMAIN_EH = "e-hentai.org"
EH_DOMAIN_EX = "exhentai.org"
EH_MAX_GALLERY_PAGES = 2000

# CSS background-position → star rating
STAR_POSITION_MAP: dict[str, float] = {
    "background-position:0px -1px":   5.0,
    "background-position:0px -21px":  4.5,
    "background-position:-16px -1px":  4.0,
    "background-position:-16px -21px": 3.5,
    "background-position:-32px -1px":  3.0,
    "background-position:-32px -21px": 2.5,
    "background-position:-48px -1px":  2.0,
    "background-position:-48px -21px": 1.5,
    "background-position:-64px -1px":  1.0,
    "background-position:-64px -21px": 0.5,
}


def parse_gallery_page_count(text: str | None) -> int:
    """解析 EH 的“874 pages”字段，并拒绝超过协议上限的异常值。"""
    match = re.search(r"(?<!\d)(\d{1,4})\s*pages?\b", text or "", flags=re.IGNORECASE)
    if not match:
        return 0
    page_count = int(match.group(1))
    return page_count if 1 <= page_count <= EH_MAX_GALLERY_PAGES else 0

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class Comic:
    """画廊列表中的条目"""
    id: str               # 完整 URL
    title: str
    cover: str
    sub_title: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""
    stars: float = 0.0
    max_page: int = 0
    language: Optional[str] = None
    type: str = ""
    uploader: str = ""
    cover_width: int = 0
    cover_height: int = 0
    cover_aspect_ratio: float = 0.0

    def __post_init__(self) -> None:
        if not self.cover_aspect_ratio and self.cover_width > 0 and self.cover_height > 0:
            self.cover_aspect_ratio = self.cover_width / self.cover_height


@dataclass
class Comment:
    id: str
    content: str
    time: str
    user_name: str
    score: Optional[int] = None
    vote_status: int = 0  # 1 up, -1 down, 0 none


@dataclass
class GalleryVersion:
    """同一画廊版本链中的其他版本。"""

    url: str
    gid: str = ""
    token: str = ""
    title: str = ""
    posted: str = ""


@dataclass
class ComicDetails:
    """画廊详细信息"""
    id: str
    title: str
    sub_title: Optional[str] = None
    cover: str = ""
    tags: dict[str, list[str]] = field(default_factory=dict)
    stars: float = 0.0
    max_page: int = 0
    is_favorite: bool = False
    folder: Optional[str] = None
    token: Optional[str] = None
    uploader: Optional[str] = None
    upload_time: str = ""
    url: str = ""
    comments: list[Comment] = field(default_factory=list)
    parent: Optional[str] = None
    newer_versions: list[GalleryVersion] = field(default_factory=list)
    visible: str = ""
    language_detail: str = ""
    file_size: str = ""
    favorite_count: int = 0
    rating_count: int = 0


@dataclass
class Archive:
    """归档下载选项"""
    id: str
    title: str
    description: str = ""


@dataclass
class SearchResult:
    """搜索结果"""
    comics: list[Comic] = field(default_factory=list)
    next_url: Optional[str] = None
    prev_url: Optional[str] = None


@dataclass
class ThumbnailItem:
    """画廊页内的单张缩略图信息"""
    url: str
    page_url: str
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0

    def __post_init__(self) -> None:
        if not self.aspect_ratio and self.width and self.height:
            self.aspect_ratio = self.width / self.height


@dataclass
class ParsedThumbnail:
    """从页面 HTML 解析出的缩略图片段，尚未绑定 page_url。"""
    url: str
    width: int = 0
    height: int = 0


@dataclass
class ThumbnailsResult:
    """缩略图页结果"""
    thumbnails: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    items: list[ThumbnailItem] = field(default_factory=list)
    next_page: Optional[str] = None


@dataclass
class ImageLoadResult:
    """单张图片加载结果"""
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    nl: Optional[str] = None


@dataclass
class KeyResult:
    """图片密钥"""
    showkey: Optional[str] = None
    mpvkey: Optional[str] = None
    image_keys: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 主客户端
# ---------------------------------------------------------------------------


class EHentaiClient:
    """E-Hentai / ExHentai 客户端"""

    def __init__(
        self,
        domain: str = EH_DOMAIN_EH,
        session: Optional[requests.Session] = None,
        log_debug: Callable[[str, str], None] | None = None,
    ) -> None:
        self.domain = domain
        self._session = session or requests.Session()
        self._log_debug = log_debug or (lambda _area, _message: None)
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        })

        # API 凭证（从画廊页面提取）
        self.api_key: Optional[str] = None
        self.api_uid: Optional[str] = None

    # -----------------------------------------------------------------------
    # 属性
    # -----------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}"

    @property
    def api_url(self) -> str:
        if self.domain == EH_DOMAIN_EX:
            return EH_API_EX
        return EH_API_EH

    @property
    def is_logged(self) -> bool:
        """通过检查是否有 ipb_member_id cookie 判断登录状态"""
        for cookie in self._session.cookies:
            if cookie.name == "ipb_member_id" and cookie.value:
                return True
        return False

    # -----------------------------------------------------------------------
    # Cookie / 登录
    # -----------------------------------------------------------------------

    def set_cookies_dict(self, cookies: dict[str, str], domain: Optional[str] = None) -> None:
        """批量设置 cookie"""
        dom = domain or f".{self.domain}"
        for name, value in cookies.items():
            self._session.cookies.set(name, value, domain=dom)

    def login_with_cookies(
        self,
        ipb_member_id: str,
        ipb_pass_hash: str,
        igneous: str = "",
        star: str = "",
        verify: bool = True,
    ) -> bool:
        """用 cookie 值登录，返回是否成功"""
        values = [ipb_member_id, ipb_pass_hash, igneous, star]
        if not values[0] or not values[1]:
            return False

        # 为 e-hentai.org 和 exhentai.org 都设置 cookie
        for dom in (".e-hentai.org", ".exhentai.org"):
            for i, name in enumerate(("ipb_member_id", "ipb_pass_hash", "igneous", "star")):
                if values[i]:
                    self._session.cookies.set(name, values[i], domain=dom)

        if not verify:
            return True

        # 验证登录：访问 favorites.php，检查是否真的登录
        resp = self._session.get(
            "https://e-hentai.org/favorites.php", timeout=30
        )
        if resp.status_code != 200:
            return False
        # 未登录时 EH 会重定向到首页或返回很短的页面
        body = resp.text
        if len(body.strip()) < 500:
            return False
        soup = BeautifulSoup(body, "lxml")
        # 多重检查：有收藏文件夹 div.fp，或页面含 "Favorites" 标题
        if soup.select("div.fp"):
            return True
        if soup.select_one("h1") and "avorite" in soup.select_one("h1").get_text():
            return True
        return False

    def logout(self) -> None:
        """清除所有 EH cookie"""
        for dom in ("e-hentai.org", "forums.e-hentai.org", "exhentai.org",
                    ".e-hentai.org", ".exhentai.org"):
            try:
                self._session.cookies.clear(domain=dom)
            except KeyError:
                pass

    # -----------------------------------------------------------------------
    # 工具方法
    # -----------------------------------------------------------------------

    @staticmethod
    def parse_url(url: str) -> tuple[str, str]:
        """从画廊 URL 提取 (gid, token)"""
        segments = url.rstrip("/").split("/")
        return segments[-2], segments[-1]

    @staticmethod
    def _get_stars_from_position(style: str) -> float:
        """解析 CSS background-position → 星级"""
        pos = style.split(";")[0] if ";" in style else style
        return STAR_POSITION_MAP.get(pos, 0.5)

    def _request(self, url: str, **kwargs) -> requests.Response:
        resp = self._session.get(url, **kwargs)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {url}")
        return resp

    def _post(self, url: str, data: Any = None, json_data: Any = None,
              headers: Optional[dict] = None) -> requests.Response:
        return self._session.post(url, data=data, json=json_data, headers=headers)

    # -----------------------------------------------------------------------
    # 搜索 / 画廊列表
    # -----------------------------------------------------------------------

    def search(
        self,
        keyword: Optional[str] = None,
        categories: Optional[list[int]] = None,
        min_stars: Optional[int] = None,
        language: Optional[str] = None,
        page_url: Optional[str] = None,
    ) -> SearchResult:
        """搜索 EH 画廊；提供 page_url 时直接解析翻页 URL。"""
        """
        搜索画廊。

        Args:
            keyword: 搜索关键词（page_url 提供时可省略）
            categories: 要包含的分类索引列表 (0-9)，None 表示全部
            min_stars: 最低星级 (0-5)
            language: 语言 (chinese / english / japanese)
            page_url: 翻页 URL，提供则忽略其他参数
        """
        if page_url:
            return self._get_galleries(page_url)

        if keyword is None:
            keyword = ""

        fcats = 1023
        if categories is not None:
            for c in categories:
                fcats -= 1 << c

        kw = keyword
        if language and "language:" not in kw:
            kw += f" language:{language}"

        params = {"f_search": kw}
        if fcats:
            params["f_cats"] = str(fcats)
        if min_stars is not None:
            params["f_srdd"] = str(min_stars)

        url = f"{self.base_url}/?{urlencode(params)}"
        return self._get_galleries(url)

    def _get_galleries(self, url: str, is_leaderboard: bool = False) -> SearchResult:
        """解析 EH 画廊列表页，兼容 Compact/Thumbnail/Extended/Minimal 多种显示模式。"""
        """
        解析画廊列表页面。

        处理 4 种 EH 显示模式：Compact / Thumbnail / Extended / Minimal
        注意: lxml 不自动插入 <tbody>，因此选择器中不使用 > tbody >
        """
        resp = self._request(url, timeout=30)

        body = resp.text.strip()
        if not body:
            raise RuntimeError("响应为空，可能缺少访问权限")
        if body[0] != "<":
            if "IP" in body:
                raise RuntimeError("你的 IP 已被封禁")
            raise RuntimeError("页面加载失败")

        soup = BeautifulSoup(body, "lxml")
        galleries: list[Comic] = []

        # --- Compact mode: table.itg.gltc ---
        # 结构: td.gl1c.glcat (分类), td.gl2c (封面/星级/时间), td.gl3c.glname (标题/链接/标签), td.gl4c.glhide (上传者/页数)
        table_gltc = soup.select_one("table.itg.gltc")
        if table_gltc:
            for row in table_gltc.select("tr"):
                try:
                    td_gl3c = row.select_one("td.gl3c")
                    if td_gl3c is None or "glname" not in td_gl3c.get("class", []):
                        continue

                    # 标题 + 链接
                    link_elem = td_gl3c.select_one("a")
                    link = link_elem.get("href", "") if link_elem else ""
                    if not link:
                        continue
                    glink = link_elem.select_one("div.glink")
                    title = glink.get_text(strip=True) if glink else ""

                    # 标签
                    tags: list[str] = []
                    language = None
                    for td_tag in td_gl3c.select("div.gt, div.gtl"):
                        tag = td_tag.get("title", "")
                        if tag.startswith("language:"):
                            lang = tag.split(":", 1)[1].strip()
                            if lang != "translated":
                                language = lang
                            continue
                        tags.append(tag)

                    # 分类
                    item_type = ""
                    td_gl1c = row.select_one("td.gl1c")
                    cn_div = td_gl1c.select_one("div.cn") if td_gl1c else None
                    item_type = cn_div.get_text(strip=True) if cn_div else ""

                    # 封面、时间、星级、页数 — 在 td.gl2c 内的 div.glthumb
                    cover = ""
                    cover_width = 0
                    cover_height = 0
                    time_str = ""
                    stars = 0.5
                    td_gl2c = row.select_one("td.gl2c")
                    if td_gl2c:
                        glthumb = td_gl2c.select_one("div.glthumb")
                        if glthumb:
                            # 封面 — lazy load 时 src 是 data: 占位符，真实 URL 在 data-src
                            img = glthumb.select_one("div > img")
                            if img:
                                cover, cover_width, cover_height = self._parse_gallery_cover(img)
                            # info 容器: glthumb > div[1] > [div(类型+时间), div(星级+页数)]
                            info_groups = glthumb.select("div > div")
                            for group in info_groups:
                                for child in group.find_all("div", recursive=False):
                                    cls = child.get("class", [])
                                    txt = child.get_text(strip=True)
                                    if cls == ["ir"]:
                                        stars = self._get_stars_from_position(child.get("style", ""))
                                    elif not cls and re.match(r"\d{4}-\d{2}-\d{2}", txt):
                                        time_str = txt

                    # 上传者、页数 — 在 td.gl4c 的子 div 中
                    uploader = ""
                    pages = 0
                    td_gl4c = row.select_one("td.gl4c")
                    if td_gl4c:
                        info_divs = td_gl4c.find_all("div", recursive=False)
                        first_a = td_gl4c.select_one("a")
                        if first_a:
                            uploader = first_a.get_text(strip=True)
                        pages = parse_gallery_page_count(td_gl4c.get_text(" ", strip=True))

                    galleries.append(Comic(
                        id=link,
                        title=title,
                        sub_title=uploader,
                        cover=cover,
                        tags=tags,
                        description=time_str,
                        stars=stars,
                        max_page=pages,
                        language=language,
                        type=item_type,
                        cover_width=cover_width,
                        cover_height=cover_height,
                    ))
                except Exception:
                    continue

        # --- Thumbnail mode: div.gl1t ---
        if not galleries:
            for item in soup.select("div.gl1t"):
                try:
                    # 标题在 span.glink 或 div.glink 内，链接在 a 标签
                    glink = item.select_one(".glink")
                    title = glink.get_text(strip=True) if glink else "Unknown"
                    link_elem = item.select_one("div.glname a, a[href*='/g/']")
                    link = link_elem.get("href", "") if link_elem else ""

                    type_elem = item.select_one("div.cs, div.cn")
                    item_type = type_elem.get_text(strip=True) if type_elem else ""

                    # 时间和页数在 div.gl5t 内
                    time_str = ""
                    pages = 0
                    gl5t = item.select_one("div.gl5t")
                    if gl5t:
                        for el in gl5t.select("div"):
                            txt = el.get_text(" ", strip=True)
                            cls = el.get("class", [])
                            if cls in [["cs"], ["cs", "ct2"], ["cn"], ["cn", "ct2"]]:
                                continue
                            if "page" in txt.lower():
                                pages = parse_gallery_page_count(txt) or pages
                            elif re.match(r"\d{4}-\d{2}-\d{2}", txt):
                                time_str = txt

                    # 封面在 div.gl3t 内
                    img = item.select_one("div.gl3t img, img")
                    cover = ""
                    cover_width = 0
                    cover_height = 0
                    if img:
                        cover, cover_width, cover_height = self._parse_gallery_cover(img)

                    star_elem = item.select_one("div.ir")
                    stars = self._get_stars_from_position(star_elem.get("style", "") if star_elem else "")

                    # 标签
                    tags: list[str] = []
                    language = None
                    for td_tag in item.select("div.gt, div.gtl"):
                        tag = td_tag.get("title", "")
                        if tag.startswith("language:"):
                            lang = tag.split(":", 1)[1].strip()
                            if lang != "translated":
                                language = lang
                            continue
                        tags.append(tag)

                    galleries.append(Comic(
                        id=link,
                        title=title,
                        cover=cover,
                        description=time_str,
                        stars=stars,
                        max_page=pages,
                        language=language,
                        type=item_type,
                        cover_width=cover_width,
                        cover_height=cover_height,
                    ))
                except Exception:
                    continue

        # --- Extended mode: table.itg.glte ---
        if not galleries:
            table_glte = soup.select_one("table.itg.glte")
            if table_glte:
                for row in table_glte.select("tr"):
                    try:
                        glink = row.select_one("td.gl2e .glink")
                        if not glink:
                            continue
                        title = glink.get_text(strip=True)
                        link_elem = row.select_one("td.gl1e a")
                        link = link_elem.get("href", "") if link_elem else ""

                        type_elem = row.select_one("div.cn, div.cs")
                        item_type = type_elem.get_text(strip=True) if type_elem else ""

                        time_str = pages = 0
                        for el in row.select("div.gl3e > div"):
                            txt = el.get_text(" ", strip=True)
                            if "page" in txt.lower():
                                pages = parse_gallery_page_count(txt) or pages
                            elif ":" in txt or "-" in txt:
                                time_str = txt

                        uploader_elem = row.select_one("div.gl3e a")
                        uploader = uploader_elem.get_text(strip=True) if uploader_elem else ""

                        img = row.select_one("td.gl1e img")
                        cover, cover_width, cover_height = self._parse_gallery_cover(img) if img else ("", 0, 0)

                        star_elem = row.select_one("div.ir")
                        stars = self._get_stars_from_position(star_elem.get("style", "") if star_elem else "")

                        tags: list[str] = []
                        language = None
                        for td_tag in row.select("div.gt, div.gtl"):
                            tag = td_tag.get("title", "")
                            if tag.startswith("language:"):
                                lang = tag.split(":", 1)[1].strip()
                                if lang != "translated":
                                    language = lang
                                continue
                            tags.append(tag)

                        galleries.append(Comic(
                            id=link,
                            title=title,
                            sub_title=uploader,
                            cover=cover,
                            tags=tags,
                            description=time_str,
                            stars=stars,
                            max_page=pages,
                            language=language,
                            type=item_type,
                            cover_width=cover_width,
                            cover_height=cover_height,
                        ))
                    except Exception:
                        continue

        # --- Minimal mode: table.itg.gltm ---
        if not galleries:
            table_gltm = soup.select_one("table.itg.gltm")
            if table_gltm:
                for row in table_gltm.select("tr"):
                    try:
                        link_elem = row.select_one("td.gl3m a")
                        if not link_elem:
                            continue
                        glink = link_elem.select_one("div.glink")
                        title = glink.get_text(strip=True) if glink else "Unknown"
                        link = link_elem.get("href", "")

                        type_elem = row.select_one("div.cs, div.cn")
                        item_type = type_elem.get_text(strip=True) if type_elem else ""

                        time_str = ""
                        for el in row.select("td.gl2m div"):
                            txt = el.get_text(strip=True)
                            if ":" in txt or "-" in txt:
                                time_str = txt
                                break

                        uploader_elem = row.select_one("td.gl5m a")
                        uploader = uploader_elem.get_text(strip=True) if uploader_elem else ""

                        img = row.select_one("td.gl2m img")
                        cover = ""
                        cover_width = 0
                        cover_height = 0
                        if img:
                            cover, cover_width, cover_height = self._parse_gallery_cover(img)

                        star_elem = row.select_one("div.ir")
                        stars = self._get_stars_from_position(star_elem.get("style", "") if star_elem else "")

                        galleries.append(Comic(
                            id=link,
                            title=title,
                            sub_title=uploader,
                            cover=cover,
                            description=time_str,
                            stars=stars,
                            type=item_type,
                            cover_width=cover_width,
                            cover_height=cover_height,
                        ))
                    except Exception:
                        continue

        # 翻页
        next_btn = soup.select_one("a#dnext")
        next_url = next_btn.get("href") if next_btn else None
        if next_url and not next_url.startswith("http"):
            next_url = self.base_url + next_url

        prev_btn = soup.select_one("a#dprev")
        prev_url = prev_btn.get("href") if prev_btn else None
        if prev_url and not prev_url.startswith("http"):
            prev_url = self.base_url + prev_url

        self._log_debug("EH解析", f"画廊列表解析完成 URL={url} 已登录={self.is_logged} 数量={len(galleries)} 有上一页={bool(prev_url)} 有下一页={bool(next_url)}")
        return SearchResult(comics=galleries, next_url=next_url, prev_url=prev_url)

    # -----------------------------------------------------------------------
    # 画廊详细信息 + 标签
    # -----------------------------------------------------------------------

    def load_comic_info(self, url: str) -> ComicDetails:
        """加载画廊详细信息，包括标签、评论、API 凭证等"""
        resp = self._request(url, cookies={"nw": "1"}, timeout=30)
        if not resp.text.strip():
            raise RuntimeError("数据为空，访问被拒绝")

        soup = BeautifulSoup(resp.text, "lxml")

        # --- 标签 ---
        tags: dict[str, list[str]] = {}
        tag_table = soup.select_one("div#taglist > table")
        if tag_table:
            for tr in tag_table.select("tr"):
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                namespace = tds[0].get_text(strip=True).rstrip(":")
                tag_list: list[str] = []
                for a_tag in tds[1].find_all("a", onclick=True):
                    onclick = a_tag["onclick"]
                    # 格式: toggle_tagmenu(id,'namespace:tag',this)
                    m = re.search(r"toggle_tagmenu\(\d+,'([^']+)'", onclick)
                    if m:
                        tag_list.append(m.group(1))
                if namespace:
                    tags[namespace] = tag_list

        # --- 页数 ---
        max_page = 1
        for el in soup.select("td.gdt2"):
            parsed_page_count = parse_gallery_page_count(el.get_text(" ", strip=True))
            if parsed_page_count:
                max_page = parsed_page_count
                break

        # --- 收藏状态 ---
        fav_link = soup.select_one("a#favoritelink")
        is_favorited = True
        if fav_link and "Add to Favorites" in fav_link.get_text(strip=True):
            is_favorited = False

        folder: Optional[str] = None
        if is_favorited:
            fav_div = soup.select_one("div#fav")
            if fav_div and fav_div.get("style"):
                m = re.search(r"background-position:0px -(\d+)px", fav_div.get("style", ""))
                if m:
                    pos = int(m.group(1))
                    folder = str((pos - 2) // 19)

        # --- 封面 URL ---
        cover_div = soup.select_one("div#gleft > div#gd1 > div")
        cover_url = ""
        if cover_div and cover_div.get("style"):
            m = re.search(r"https?://[^\s\"']+\.(?:jpg|jpeg|gif|png|webp)", cover_div["style"])
            if m:
                cover_url = m.group()

        # --- 上传者 ---
        uploader = None
        uploader_el = soup.select_one("#gdn")
        if uploader_el:
            uploader = uploader_el.get_text(strip=True)

        # --- 星级 ---
        stars = 0.0
        rating_label = soup.select_one("#rating_label")
        if rating_label:
            m = re.search(r"[\d.]+", rating_label.get_text(strip=True).split(":")[-1])
            if m:
                stars = float(m.group())

        # --- 分类 ---
        cat_el = soup.select_one("div.cs")
        if cat_el:
            tags["Category"] = [cat_el.get_text(strip=True)]

        if uploader:
            tags["uploader"] = [uploader]

        # --- 上传时间 ---
        time_el = soup.select_one("div#gdd td.gdt2")
        upload_time = time_el.get_text(strip=True) if time_el else ""
        detail_info = self._parse_detail_info_table(soup)
        upload_time = detail_info.get("upload_time") or upload_time

        # --- 从 script 提取 token / apikey / apiuid ---
        token: Optional[str] = None
        for script in soup.find_all("script"):
            if script.string and "var token" in script.string:
                for m in re.finditer(r"var\s+(\w+)\s*=\s*(.*?);", script.string):
                    var_name = m.group(1)
                    var_value = m.group(2)
                    if var_name == "token":
                        token = var_value.strip("\"'")
                    elif var_name == "apikey":
                        self.api_key = var_value.strip("\"'")
                    elif var_name == "apiuid":
                        self.api_uid = var_value.strip("\"'")
                break

        # --- 标题 ---
        title_el = soup.select_one("h1#gn")
        title = title_el.get_text(strip=True) if title_el else ""

        subtitle_el = soup.select_one("h1#gj")
        subtitle = subtitle_el.get_text(strip=True) if subtitle_el else None
        if subtitle and subtitle.strip() == "":
            subtitle = None

        # --- 评论 ---
        comments = self._parse_comments(soup)
        newer_versions = self._parse_newer_versions(soup, resp.text)

        return ComicDetails(
            id=url,
            title=title,
            sub_title=subtitle,
            cover=cover_url,
            tags=tags,
            stars=stars,
            max_page=max_page,
            is_favorite=is_favorited,
            folder=folder,
            token=token,
            uploader=uploader,
            upload_time=upload_time,
            url=url,
            comments=comments,
            parent=detail_info.get("parent"),
            newer_versions=newer_versions,
            visible=detail_info.get("visible", ""),
            language_detail=detail_info.get("language_detail", ""),
            file_size=detail_info.get("file_size", ""),
            favorite_count=int(detail_info.get("favorite_count") or 0),
            rating_count=self._parse_rating_count(soup),
        )

    @staticmethod
    def _parse_detail_info_table(soup: BeautifulSoup) -> dict[str, Any]:
        """解析 EH 详情表中的 Parent/Visible/Size/Favorited 等字段。"""
        result: dict[str, Any] = {}
        for row in soup.select("div#gdd tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            key = cells[0].get_text(strip=True).rstrip(":")
            value_cell = cells[1]
            value = value_cell.get_text(" ", strip=True)
            if key.startswith("Posted"):
                result["upload_time"] = value
            elif key.startswith("Parent"):
                link = value_cell.select_one("a[href]")
                result["parent"] = link.get("href", "") if link else value
            elif key.startswith("Visible"):
                result["visible"] = value
            elif key.startswith("Language"):
                result["language_detail"] = value
            elif key.startswith("File Size"):
                result["file_size"] = value
            elif key.startswith("Favorited"):
                if value == "Never":
                    result["favorite_count"] = 0
                elif value == "Once":
                    result["favorite_count"] = 1
                else:
                    m = re.search(r"[\d,]+", value)
                    result["favorite_count"] = int(m.group().replace(",", "")) if m else 0
        return result

    @classmethod
    def _parse_newer_versions(cls, soup: BeautifulSoup, body: str) -> list[GalleryVersion]:
        """解析 EH 的 newer versions 区块。"""
        container = soup.select_one("div#gnd")
        if not container:
            return []
        dates = re.findall(r", added (.+?)<br\s*/?>", body)
        versions: list[GalleryVersion] = []
        for index, link in enumerate(container.select("a[href]")):
            href = link.get("href", "")
            title = link.get_text(strip=True)
            try:
                gid, token = cls.parse_url(href)
            except Exception:
                gid, token = "", ""
            versions.append(
                GalleryVersion(
                    url=href,
                    gid=str(gid),
                    token=token,
                    title=title,
                    posted=dates[index] if index < len(dates) else "",
                )
            )
        return versions

    @staticmethod
    def _parse_rating_count(soup: BeautifulSoup) -> int:
        """解析评分人数。"""
        rating_count = soup.select_one("#rating_count")
        if not rating_count:
            return 0
        try:
            return int(rating_count.get_text(strip=True).replace(",", ""))
        except ValueError:
            return 0

    # -----------------------------------------------------------------------
    # 评论解析
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_comments(soup: BeautifulSoup) -> list[Comment]:
        comments: list[Comment] = []
        for c in soup.select("div.c1"):
            try:
                name_el = c.select_one("div.c3 > a")
                name = name_el.get_text(strip=True) if name_el else ""

                time_text = "unknown"
                c3 = c.select_one("div.c3")
                if c3:
                    parts = c3.get_text().split("Posted on")
                    if len(parts) > 1:
                        time_text = parts[1].split("by")[0].strip()

                content_el = c.select_one("div.c6")
                content = content_el.get_text(strip=True) if content_el else ""

                score_el = c.select_one("div.c5 > span")
                score = None
                if score_el:
                    try:
                        score = int(score_el.get_text(strip=True))
                    except ValueError:
                        pass

                prev = c.find_previous_sibling()
                cid = "0"
                if prev and prev.get("name"):
                    m = re.search(r"\d+", prev["name"])
                    if m:
                        cid = m.group()

                vote_up = c.select_one(f"a#comment_vote_up_{cid}")
                vote_down = c.select_one(f"a#comment_vote_down_{cid}")
                vote_status = 0
                if vote_up and vote_up.get("style"):
                    vote_status = 1
                elif vote_down and vote_down.get("style"):
                    vote_status = -1

                comments.append(Comment(
                    id=cid,
                    content=content,
                    time=time_text,
                    user_name=name,
                    score=score,
                    vote_status=vote_status,
                ))
            except Exception:
                continue
        return comments

    # -----------------------------------------------------------------------
    # 缩略图
    # -----------------------------------------------------------------------

    def load_thumbnails(self, comic_url: str, page: Optional[str] = None) -> ThumbnailsResult:
        """加载画廊的缩略图页"""
        url = comic_url
        if page is not None:
            url += f"?p={page}"

        resp = self._request(url, cookies={"nw": "1"}, timeout=30)
        soup = BeautifulSoup(resp.text, "lxml")

        parsed_thumbs: list[ParsedThumbnail] = []

        # gdtm (sprite thumbnails)
        for div in soup.select("div.gdtm > div"):
            thumb = self._parse_sprite_thumbnail(div)
            if thumb:
                parsed_thumbs.append(thumb)

        # gdtl (direct images)
        for img in soup.select("div.gdtl > a > img"):
            thumb = self._parse_direct_thumbnail(img)
            if thumb:
                parsed_thumbs.append(thumb)

        # fallback: gt100 / gt200
        if not parsed_thumbs:
            for div in soup.select("div.gt100 > a > div, div.gt200 > a > div"):
                children = div.find_all(recursive=False)
                target = children[0] if children else div
                thumb = self._parse_sprite_thumbnail(target)
                if thumb:
                    parsed_thumbs.append(thumb)

        # 页码
        urls: list[str] = []
        for a in soup.select("div#gdt a"):
            href = a.get("href", "")
            if href:
                urls.append(href)

        # 翻页
        page_links = soup.select("table.ptb a")
        page_numbers = []
        for a in page_links:
            href = a.get("href", "")
            m = re.search(r"[?&]p=(\d+)", href)
            if m:
                page_numbers.append(int(m.group(1)))
            else:
                page_numbers.append(0)

        max_page_num = max(page_numbers) if page_numbers else 0
        current = int(page) if page else 0
        current += 1
        next_page = str(current) if current <= max_page_num else None

        items = [
            ThumbnailItem(
                url=thumb.url,
                page_url=page_url,
                width=thumb.width,
                height=thumb.height,
            )
            for thumb, page_url in zip(parsed_thumbs, urls)
        ]

        return ThumbnailsResult(
            thumbnails=[thumb.url for thumb in parsed_thumbs],
            urls=urls,
            items=items,
            next_page=next_page,
        )

    @staticmethod
    def _parse_int(value: Any) -> int:
        if value is None:
            return 0
        m = re.search(r"\d+", str(value))
        return int(m.group(0)) if m else 0

    @classmethod
    def _parse_size_from_style(cls, style: str) -> tuple[int, int]:
        width_m = re.search(r"width:\s*(\d+)px", style)
        height_m = re.search(r"height:\s*(\d+)px", style)
        width = int(width_m.group(1)) if width_m else 0
        height = int(height_m.group(1)) if height_m else 0
        return width, height

    @classmethod
    def _parse_gallery_cover(cls, element: Any) -> tuple[str, int, int]:
        """从画廊列表 img 节点解析封面 URL 和 EH 提供的显示尺寸。"""
        if element is None:
            return "", 0, 0
        src = element.get("data-src") or ""
        if not src or src.startswith("data:"):
            src = element.get("src", "")
        width = cls._parse_int(element.get("width"))
        height = cls._parse_int(element.get("height"))
        style_width, style_height = cls._parse_size_from_style(element.get("style", ""))
        width = width or style_width
        height = height or style_height
        return src, width, height

    @classmethod
    def _parse_direct_thumbnail(cls, element: Any) -> Optional[ParsedThumbnail]:
        """从直接 img 节点解析缩略图 URL 和显示尺寸。"""
        src = element.get("src", "")
        if not src:
            return None

        width = cls._parse_int(element.get("width"))
        height = cls._parse_int(element.get("height"))
        if not width or not height:
            style_width, style_height = cls._parse_size_from_style(element.get("style", ""))
            width = width or style_width
            height = height or style_height

        return ParsedThumbnail(url=src, width=width, height=height)

    @classmethod
    def _parse_sprite_thumbnail(cls, element: Any) -> Optional[ParsedThumbnail]:
        """从 sprite div 解析图片 URL（带 crop range 参数）和显示尺寸。"""
        style = element.get("style", "")
        if not style or "url(" not in style:
            return None

        # 提取 URL
        m = re.search(r"url\(([^)]+)\)", style)
        if not m:
            return None
        base = m.group(1)

        width, height = cls._parse_size_from_style(style)

        # 提取 position:  "url(...) -Npx" 形式
        pos_m = re.search(r"url\([^)]+\)\s*-(\d+)px", style)
        range_str = ""
        if pos_m and width:
            position = int(pos_m.group(1))
            range_str = f"x={position}-{position + width}"
        if height:
            sep = "&" if range_str else ""
            range_str += f"{sep}y=0-{height}"
        if range_str:
            base += f"@{range_str}"

        return ParsedThumbnail(url=base, width=width, height=height)

    # -----------------------------------------------------------------------
    # 图片密钥 (showkey / mpvkey)
    # -----------------------------------------------------------------------

    def get_key(self, page_url: str) -> KeyResult:
        """从图片页面提取密钥"""
        resp = self._request(page_url, timeout=30)
        soup = BeautifulSoup(resp.text, "lxml")

        for script in soup.find_all("script"):
            if not script.string:
                continue
            if "showkey" in script.string:
                m = re.search(r'showkey="(.*?)"', script.string)
                if m:
                    return KeyResult(showkey=m.group(1))

        mpvkey = None
        image_list = None
        for script in soup.find_all("script"):
            if not script.string:
                continue
            s = script.string
            if "mpvkey" in s:
                for part in s.split(";"):
                    part = part.strip()
                    if "mpvkey" in part:
                        mpvkey = part.split("=", 1)[1].strip().strip("\"'")
                    if "imagelist" in part:
                        raw = part.split("=", 1)[1].strip()
                        try:
                            image_list = json.loads(raw)
                        except json.JSONDecodeError:
                            pass
                break

        image_keys = [item["k"] for item in image_list] if image_list else []
        if mpvkey:
            return KeyResult(mpvkey=mpvkey, image_keys=image_keys)

        raise RuntimeError("无法从页面提取密钥")

    # -----------------------------------------------------------------------
    # 单张图片加载
    # -----------------------------------------------------------------------

    def get_image_url(
        self,
        comic_url: str,
        page_index: int,
        nl: Optional[str] = None,
    ) -> ImageLoadResult:
        """解析指定页的真实图片 URL；会根据 showkey/mpvkey 走不同 API。"""
        """
        获取单张图片的实际下载 URL。

        Args:
            comic_url: 画廊 URL
            page_index: 图片索引 (0-based)
            nl: nonce 值（用于反爬重试）
        """
        comic_info = self.load_comic_info(comic_url)
        first_thumbs = self.load_thumbnails(comic_url)
        key = self.get_key(first_thumbs.urls[0])

        gid, token = self.parse_url(comic_url)

        if key.mpvkey:
            return self._get_image_mpv(gid, key, page_index, nl)
        else:
            return self._get_image_showkey(
                gid, key, page_index, first_thumbs, comic_url, nl,
            )

    def _get_image_mpv(
        self,
        gid: str,
        key: KeyResult,
        page_index: int,
        nl: Optional[str] = None,
    ) -> ImageLoadResult:
        """新系统：通过 mpvkey + imagedispatch API 获取图片"""
        payload = {
            "gid": gid,
            "imgkey": key.image_keys[page_index],
            "method": "imagedispatch",
            "page": page_index + 1,
            "mpvkey": key.mpvkey,
        }
        if nl is not None:
            payload["nl"] = nl

        resp = self._post(
            self.api_url,
            json_data=payload,
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        next_nl = str(data.get("s", ""))
        return ImageLoadResult(
            url=str(data["i"]),
            headers={"referer": self.base_url},
            nl=next_nl,
        )

    def _get_image_showkey(
        self,
        gid: str,
        key: KeyResult,
        page_index: int,
        first_thumbs: ThumbnailsResult,
        comic_url: str,
        nl: Optional[str] = None,
    ) -> ImageLoadResult:
        """旧系统：通过 showkey + showpage API 获取图片"""

        def _parse_imgkey_from_url(url: str) -> str:
            return url.split("/")[4]

        if page_index < len(first_thumbs.urls):
            target_url = first_thumbs.urls[page_index]
        else:
            pp = len(first_thumbs.urls)
            should_load = page_index // pp
            idx = page_index % pp
            thumbs = self.load_thumbnails(comic_url, str(should_load))
            target_url = thumbs.urls[idx]

        payload = {
            "gid": gid,
            "imgkey": _parse_imgkey_from_url(target_url),
            "method": "showpage",
            "page": page_index + 1,
            "showkey": key.showkey,
        }
        if nl is not None:
            payload["nl"] = nl

        resp = self._post(
            self.api_url,
            json_data=payload,
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        i6 = data.get("i6", "")
        m = re.search(r"nl\('(.+?)'\)", i6)
        next_nl = m.group(1) if m else None

        i3 = data.get("i3", "")
        src_m = re.search(r'src="(.*?)"\s+style', i3)
        image_url = src_m.group(1) if src_m else ""

        return ImageLoadResult(
            url=image_url,
            headers={"referer": self.base_url},
            nl=next_nl,
        )

    # -----------------------------------------------------------------------
    # 归档下载 (Archive)
    # -----------------------------------------------------------------------

    def get_archives(self, comic_url: str) -> list[Archive]:
        """获取归档下载选项列表"""
        gid, token = self.parse_url(comic_url)
        resp = self._request(
            f"{self.base_url}/archiver.php?gid={gid}&token={token}",
            timeout=30,
        )
        soup = BeautifulSoup(resp.text, "lxml")
        db = soup.select_one("div#db")
        if not db:
            raise RuntimeError("归档页面解析失败")

        archives: list[Archive] = []

        # --- H@H 选项 ---
        # 结构: table > tr > td, 每个 td 含 <a onclick="do_hathdl('res')"> + <p>size</p> + <p>cost</p>
        hath_table = soup.select_one("div#db table")
        if hath_table:
            for cell in hath_table.find_all("td"):
                link = cell.find("a")
                onclick = link.get("onclick", "") if link else ""
                m = re.search(r"do_hathdl\('([^']+)'\)", onclick)
                pars = cell.find_all("p")
                if m:
                    resolution = m.group(1)
                    size = pars[1].get_text(strip=True) if len(pars) > 1 else "Unknown"
                    cost = pars[2].get_text(strip=True) if len(pars) > 2 else "Unknown"
                    archives.append(Archive(
                        id=f"h@h_{resolution}",
                        title=f"H@H {link.get_text(strip=True)}",
                        description=f"Size: {size}, Cost: {cost}",
                    ))
                elif len(pars) >= 3:
                    # 不可用的选项（N/A）
                    size = pars[1].get_text(strip=True)
                    cost = pars[2].get_text(strip=True)
                    if size != "N/A" and cost != "N/A":
                        res_text = pars[0].get_text(strip=True)
                        archives.append(Archive(
                            id=f"h@h_{res_text.lower().replace('x', '')}",
                            title=f"H@H {res_text}",
                            description=f"Size: {size}, Cost: {cost}",
                        ))

        # --- Original / Resample 归档 ---
        # 结构: div#db > div[0] > div(Original) + div(Resample)
        # 每个 div 内含 "Download Cost:xxx" 和 "Estimated Size:xxx"
        db_divs = [c for c in db.children if hasattr(c, "name") and c.name == "div"]
        if db_divs:
            info_div = db_divs[0]
            for sub in info_div.find_all("div", recursive=False):
                text = sub.get_text(strip=True)
                if not text:
                    continue
                # 提取 cost 和 size
                cost_m = re.search(r"Download Cost:\s*(.+?)(?:Estimated|$)", text)
                size_m = re.search(r"Estimated Size:\s*(.+)", text)
                cost = cost_m.group(1).strip() if cost_m else "Unknown"
                size = size_m.group(1).strip() if size_m else "Unknown"
                # 第一个是 Original, 第二个是 Resample
                aid = "0" if len([a for a in archives if a.id in ("0", "1")]) == 0 else "1"
                title = "Original" if aid == "0" else "Resample"
                archives.append(Archive(
                    id=aid,
                    title=title,
                    description=f"Cost: {cost}, Size: {size}",
                ))

        return archives

    def get_archive_download_url(self, comic_url: str, archive_id: str) -> str:
        """获取 EH Archive 的最终下载 URL；H@H 选项不返回本地可下载 URL。"""
        """
        获取归档下载的真实 URL。

        Args:
            comic_url: 画廊 URL
            archive_id: '0' = Original, '1' = Resample, 'h@h_xxx' = H@H

        Returns:
            归档文件下载直链
        """
        gid, token = self.parse_url(comic_url)

        # --- H@H ---
        if archive_id.startswith("h@h_"):
            resolution = archive_id[4:]
            resp = self._post(
                f"{self.base_url}/archiver.php?gid={gid}&token={token}",
                data={"hathdl_xres": resolution},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code != 200:
                raise RuntimeError(f"H@H 下载失败：HTTP {resp.status_code}")
            soup = BeautifulSoup(resp.text, "lxml")
            err = soup.select_one("p.br")
            if err:
                msg = err.get_text(strip=True)
                if "H@H client" in msg:
                    raise RuntimeError("需要将 H@H 客户端与你的账户关联")
                if "offline" in msg:
                    raise RuntimeError("你的 H@H 客户端处于离线状态")
                if "resolution" in msg:
                    raise RuntimeError("该画廊不提供此分辨率")
                raise RuntimeError(msg)
            return ""  # H@H 是服务端下载，不返回 URL

        # --- Original / Resample ---
        dltype = "org" if archive_id == "0" else "res"
        form_data = f"dltype={dltype}&dlcheck=Download+{dltype.title()}+Archive"

        resp = self._post(
            f"{self.base_url}/archiver.php?gid={gid}&token={token}",
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"归档请求失败：HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "lxml")
        link_el = soup.select_one("a")
        if not link_el or not link_el.get("href"):
            raise RuntimeError("无法获取中间下载链接")
        link1 = link_el["href"]

        # 跟随重定向
        resp2 = self._session.get(
            link1,
            headers={"http_client": "dart:io"},
        )
        soup2 = BeautifulSoup(resp2.text, "lxml")
        link2_el = soup2.select_one("a")
        if not link2_el or not link2_el.get("href"):
            raise RuntimeError("无法获取最终下载链接")
        link2 = link2_el["href"]

        # 拼接完整 URL
        parsed = urlparse(link1)
        result_url = f"{parsed.scheme}://{parsed.netloc}{link2}"

        # 检查 IP 限额
        head = self._session.head(
            result_url,
            headers={"http_client": "dart:io"},
        )
        if head.status_code == 410:
            raise RuntimeError("IP 配额已耗尽。")

        return result_url

    # -----------------------------------------------------------------------
    # 排行榜
    # -----------------------------------------------------------------------

    def get_toplist(
        self,
        option: str = "15-yesterday",
        page: int = 1,
    ) -> SearchResult:
        """
        获取排行榜。

        option:
            '15-yesterday', '13-month', '12-year', '11-all'
        """
        res = self._get_galleries(
            f"https://e-hentai.org/toplist.php?tl={option}&p={page - 1}",
            is_leaderboard=True,
        )
        if self.domain == EH_DOMAIN_EX:
            for c in res.comics:
                c.id = c.id.replace("e-hentai", "exhentai")
        return res

    # -----------------------------------------------------------------------
    # 收藏
    # -----------------------------------------------------------------------

    def get_favorites(
        self,
        folder: str = "-1",
        page_url: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> SearchResult:
        """获取收藏列表"""
        if page_url:
            if keyword:
                parsed = urlsplit(page_url)
                query = parse_qs(parsed.query, keep_blank_values=True)
                query.setdefault("f_search", [keyword])
                page_url = urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment)
                )
            return self._get_galleries(page_url)
        url = f"{self.base_url}/favorites.php"
        params = {}
        if folder != "-1":
            params["favcat"] = folder
        if keyword:
            params["f_search"] = keyword
        if params:
            url += f"?{urlencode(params)}"
        return self._get_galleries(url)

    def add_favorite(self, comic_url: str, folder_id: str = "0") -> None:
        """添加到收藏"""
        gid, token = self.parse_url(comic_url)
        resp = self._post(
            f"{self.base_url}/gallerypopups.php?gid={gid}&t={token}&act=addfav",
            data=f"favcat={folder_id}&favnote=&apply=Add+to+Favorites&update=1",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200 or not resp.text.strip() or resp.text[0] != "<":
            raise RuntimeError("添加收藏失败")

    def delete_favorite(self, comic_url: str) -> None:
        """从收藏移除"""
        gid, token = self.parse_url(comic_url)
        resp = self._post(
            f"{self.base_url}/gallerypopups.php?gid={gid}&t={token}&act=addfav",
            data="favcat=favdel&favnote=&apply=Apply+Changes&update=1",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200 or not resp.text.strip() or resp.text[0] != "<":
            raise RuntimeError("删除收藏失败")

    def get_favorite_folders(self) -> dict[str, str]:
        """获取收藏文件夹列表，返回 {id: name}"""
        resp = self._request(f"{self.base_url}/favorites.php", timeout=30)
        soup = BeautifulSoup(resp.text, "lxml")
        folders: dict[str, str] = {"-1": "All"}
        total = 0
        for item in soup.select("div.fp"):
            if "Show All Favorites" in item.get_text(strip=True):
                continue
            children = item.find_all(recursive=False)
            name = children[2].get_text(strip=True) if len(children) > 2 else f"Favorite {len(folders)}"
            length = children[0].get_text(strip=True) if children else ""
            if length:
                name += f" ({length})"
                try:
                    total += int(length)
                except ValueError:
                    pass
            folders[str(len(folders) - 1)] = name
        folders["-1"] = f"All ({total})"
        return folders

    # -----------------------------------------------------------------------
    # 评论操作
    # -----------------------------------------------------------------------

    def load_comments(self, comic_url: str) -> list[Comment]:
        """加载评论区"""
        resp = self._request(f"{comic_url}?hc=1", cookies={"nw": "1"}, timeout=30)
        soup = BeautifulSoup(resp.text, "lxml")
        return self._parse_comments(soup)

    def send_comment(self, comic_url: str, content: str) -> None:
        """发送评论"""
        resp = self._post(
            comic_url,
            data={"commenttext_new": content},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "referer": comic_url,
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"发送评论失败：HTTP {resp.status_code}")
        soup = BeautifulSoup(resp.text, "lxml")
        err = soup.select_one("p.br")
        if err:
            raise RuntimeError(err.get_text(strip=True))

    def vote_comment(
        self,
        comic_url: str,
        comment_id: str,
        is_up: bool,
    ) -> int:
        """评论投票，返回新分数"""
        if not self.api_key or not self.api_uid:
            raise RuntimeError("需要登录，但未提供 API 凭据")
        gid, token = self.parse_url(comic_url)
        resp = self._post(
            self.api_url,
            json_data={
                "gid": gid,
                "token": token,
                "method": "votecomment",
                "comment_id": comment_id,
                "comment_vote": 1 if is_up else -1,
                "apikey": self.api_key,
                "apiuid": self.api_uid,
            },
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data["comment_score"]

    # -----------------------------------------------------------------------
    # 星级评分
    # -----------------------------------------------------------------------

    def rate_gallery(self, comic_url: str, rating: int) -> None:
        """
        给画廊打分。

        Args:
            comic_url: 画廊 URL
            rating: 0-10 (app 5 星制, 1 rating = 0.5 stars)
        """
        if not self.api_key or not self.api_uid:
            raise RuntimeError("需要登录，但未提供 API 凭据")
        gid, token = self.parse_url(comic_url)
        resp = self._post(
            self.api_url,
            json_data={
                "gid": gid,
                "token": token,
                "method": "rategallery",
                "rating": rating,
                "apikey": self.api_key,
                "apiuid": self.api_uid,
            },
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"评分失败：HTTP {resp.status_code}")

    # -----------------------------------------------------------------------
    # 探索页面
    # -----------------------------------------------------------------------

    def get_latest(self, page_url: Optional[str] = None) -> SearchResult:
        """最新画廊"""
        return self._get_galleries(page_url or self.base_url)

    def get_popular(self, page_url: Optional[str] = None) -> SearchResult:
        """流行画廊"""
        return self._get_galleries(page_url or f"{self.base_url}/popular")

    def get_watched(self, page_url: Optional[str] = None) -> SearchResult:
        """关注画廊（需要登录）"""
        if not self.is_logged:
            raise RuntimeError("查看订阅页面需要登录")
        return self._get_galleries(page_url or f"{self.base_url}/watched")

    # -----------------------------------------------------------------------
    # 事件检查
    # -----------------------------------------------------------------------

    def check_dawn_event(self) -> Optional[str]:
        """检查黎明事件（EH 主页左上角的小提示）"""
        if not self.is_logged:
            return None
        resp = self._request("https://e-hentai.org/news.php", timeout=30)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        event = soup.select_one("#eventpane")
        if not event:
            return None
        info = event.select_one("div > p:nth-child(2)")
        return info.get_text(strip=True) if info else None

    # -----------------------------------------------------------------------
    # URL 处理
    # -----------------------------------------------------------------------

    @staticmethod
    def link_to_id(url: str, base_url: str = "https://e-hentai.org") -> Optional[str]:
        """将 URL 转换为标准画廊 ID"""
        url = url.split("?")[0]
        m = re.match(r"https?://(e-|ex)hentai\.org/g/(\d+)/(\w+)/?$", url)
        if m:
            return f"{base_url}/g/{m.group(2)}/{m.group(3)}/"
        return None
