//! Pixiv Web AJAX detail and multi-page image metadata.

use crate::{CoreError, ErrorCode, ProfileKey, session::SessionRegistry};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use url::Url;

/// Pixiv creator summary attached to one illustration.
#[derive(Clone, Debug, Serialize)]
pub struct PixivUser {
    /// Pixiv user ID.
    pub id: String,
    /// Display name.
    pub name: String,
}

/// One page and its Provider-supplied representations.
#[derive(Clone, Debug, Serialize)]
pub struct PixivPage {
    /// Zero-based page index.
    pub index: u32,
    /// Original image URL.
    pub original_url: Url,
    /// Regular image URL, when supplied.
    pub regular_url: Option<Url>,
    /// Small image URL, when supplied.
    pub small_url: Option<Url>,
}

/// Pixiv illustration detail without raw Provider JSON.
#[derive(Clone, Debug, Serialize)]
pub struct PixivIllust {
    /// Illustration ID.
    pub id: String,
    /// Human-facing artwork URL.
    pub page_url: Url,
    /// Artwork title.
    pub title: String,
    /// HTML caption supplied by Pixiv.
    pub caption: String,
    /// Illustration type number supplied by Pixiv.
    pub illust_type: u32,
    /// Number of image pages.
    pub page_count: u32,
    /// Original width of the first page.
    pub width: u32,
    /// Original height of the first page.
    pub height: u32,
    /// R18 restriction level.
    pub x_restrict: u32,
    /// View count.
    pub view_count: u64,
    /// Bookmark count.
    pub bookmark_count: u64,
    /// Whether the current session bookmarked this artwork.
    pub bookmarked: bool,
    /// Creation timestamp supplied by Pixiv.
    pub created_at: String,
    /// Creator summary.
    pub user: PixivUser,
    /// Pixiv tags.
    pub tags: Vec<String>,
    /// Page resources in Provider order.
    pub pages: Vec<PixivPage>,
}

/// One Pixiv artwork summary returned by Web AJAX search.
#[derive(Clone, Debug, Serialize)]
pub struct PixivSearchItem {
    /// Numeric illustration ID rendered as text.
    pub id: String,
    /// Artwork title.
    pub title: String,
    /// Creator summary.
    pub user: PixivUser,
    /// Number of artwork pages.
    pub page_count: u32,
    /// R18 restriction level.
    pub x_restrict: u32,
    /// Search thumbnail URL supplied by Pixiv.
    pub thumbnail_url: Option<Url>,
    /// Tags supplied by the search response.
    pub tags: Vec<String>,
}

/// One stable page of Pixiv artwork search results.
#[derive(Clone, Debug, Serialize)]
pub struct PixivSearchResult {
    /// Profile that executed the request.
    pub profile: String,
    /// Immutable session generation used for the response body.
    pub generation: u64,
    /// Provider-native query text.
    pub query: String,
    /// One-based Pixiv page number.
    pub page: u32,
    /// Last page reported by Pixiv.
    pub last_page: u32,
    /// Next page when more results exist.
    pub next_page: Option<u32>,
    /// Artwork summaries in Provider order.
    pub items: Vec<PixivSearchItem>,
}

/// Current Pixiv discovery recommendations without a synthetic pagination cursor.
#[derive(Clone, Debug, Serialize)]
pub struct PixivRecommendationResult {
    /// Profile that executed the request.
    pub profile: String,
    /// Immutable session generation used for the response body.
    pub generation: u64,
    /// Artwork summaries in Provider order.
    pub items: Vec<PixivSearchItem>,
}

/// Which authenticated Pixiv following feed to read.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum PixivFollowingVisibility {
    /// General followed-artists feed.
    Public,
    /// R18 followed-artists feed.
    Private,
}

/// One stable page of the authenticated Pixiv following feed.
#[derive(Clone, Debug, Serialize)]
pub struct PixivFollowingResult {
    /// Profile that executed the request.
    pub profile: String,
    /// Immutable authenticated session generation used for the response body.
    pub generation: u64,
    /// Requested public or private feed.
    pub visibility: PixivFollowingVisibility,
    /// One-based Pixiv page number.
    pub page: u32,
    /// Next page when Pixiv reports that more work exists.
    pub next_page: Option<u32>,
    /// Artwork summaries in Provider order.
    pub items: Vec<PixivSearchItem>,
}

/// Which authenticated Pixiv bookmark collection to read.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum PixivBookmarkVisibility {
    /// Public bookmarks visible to the signed-in user.
    Public,
    /// Private bookmarks visible only to the signed-in user.
    Private,
}

/// One bounded slice of the authenticated current-user Pixiv bookmarks.
#[derive(Clone, Debug, Serialize)]
pub struct PixivBookmarksResult {
    /// Profile that executed the request.
    pub profile: String,
    /// Immutable authenticated session generation used for the response body.
    pub generation: u64,
    /// Requested public or private bookmark collection.
    pub visibility: PixivBookmarkVisibility,
    /// Zero-based result offset.
    pub offset: u32,
    /// Fixed number of results requested per slice.
    pub limit: u32,
    /// Total bookmarked works reported by Pixiv.
    pub total: u32,
    /// Next offset when more results exist.
    pub next_offset: Option<u32>,
    /// Artwork summaries in Provider order.
    pub items: Vec<PixivSearchItem>,
}

/// One Pixiv artwork summary returned by the ranking feed.
#[derive(Clone, Debug, Serialize)]
pub struct PixivRankingItem {
    /// Rank on the requested page/date.
    pub rank: u32,
    /// Rank in the previous comparable period, when supplied.
    pub previous_rank: Option<u32>,
    /// Numeric illustration ID rendered as text.
    pub id: String,
    /// Artwork title.
    pub title: String,
    /// Creator summary.
    pub user: PixivUser,
    /// Number of artwork pages.
    pub page_count: u32,
    /// R18 restriction level when supplied by Pixiv.
    pub x_restrict: u32,
    /// Ranking thumbnail URL supplied by Pixiv.
    pub thumbnail_url: Option<Url>,
    /// Tags supplied by the ranking response.
    pub tags: Vec<String>,
}

/// One stable page of Pixiv ranking results.
#[derive(Clone, Debug, Serialize)]
pub struct PixivRankingResult {
    /// Profile that executed the request.
    pub profile: String,
    /// Immutable session generation used for the response body.
    pub generation: u64,
    /// Stable caller-facing mode: `day`, `week`, or `month`.
    pub mode: String,
    /// Optional ranking date in `YYYY-MM-DD` form.
    pub date: String,
    /// One-based Pixiv page number.
    pub page: u32,
    /// Next page reported by Pixiv.
    pub next_page: Option<u32>,
    /// Ranked artwork summaries in Provider order.
    pub items: Vec<PixivRankingItem>,
}

pub(crate) struct PixivService {
    sessions: Arc<SessionRegistry>,
}

impl PixivService {
    pub(crate) fn new(sessions: Arc<SessionRegistry>) -> Self {
        Self { sessions }
    }

    pub(crate) async fn illust(
        &self,
        key: &ProfileKey,
        illust_id: &str,
        cancellation: CancellationToken,
    ) -> Result<PixivIllust, CoreError> {
        ensure_pixiv(key, illust_id)?;
        let response = self
            .sessions
            .get_pixiv_ajax(
                key,
                &format!("ajax/illust/{illust_id}"),
                &[],
                &format!("artworks/{illust_id}"),
                cancellation.child_token(),
            )
            .await?;
        let response_url = response.final_url.clone();
        let detail: AjaxResponse<DetailBody> = parse_ajax(&response.body)?;
        let body = detail.body.ok_or_else(|| unavailable(illust_id))?;
        let page_response = self
            .sessions
            .get_pixiv_ajax(
                key,
                &format!("ajax/illust/{illust_id}/pages"),
                &[("lang".to_owned(), "zh".to_owned())],
                &format!("artworks/{illust_id}"),
                cancellation,
            )
            .await?;
        let pages: AjaxResponse<Vec<PageBody>> = parse_ajax(&page_response.body)?;
        let pages = pages.body.ok_or_else(|| unavailable(illust_id))?;
        map_illust(&response_url, illust_id, body, pages)
    }

    pub(crate) async fn search(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u32,
        cancellation: CancellationToken,
    ) -> Result<PixivSearchResult, CoreError> {
        ensure_pixiv_search(key, query, page)?;
        let query = query.trim();
        let encoded = encode_path_segment(query)?;
        let response = self
            .sessions
            .get_pixiv_ajax(
                key,
                &format!("ajax/search/artworks/{encoded}"),
                &[
                    ("word".to_owned(), query.to_owned()),
                    ("order".to_owned(), "date_d".to_owned()),
                    ("mode".to_owned(), "all".to_owned()),
                    ("p".to_owned(), page.to_string()),
                    ("s_mode".to_owned(), "s_tag_full".to_owned()),
                    ("type".to_owned(), "all".to_owned()),
                    ("lang".to_owned(), "zh".to_owned()),
                ],
                &format!("tags/{encoded}/artworks"),
                cancellation,
            )
            .await?;
        let generation = response.generation;
        let result: AjaxResponse<SearchBody> = parse_ajax(&response.body)?;
        let feed = result
            .body
            .and_then(|body| body.illust_manga)
            .ok_or_else(|| unexpected("Pixiv search response has no illustration feed"))?;
        let items = feed
            .data
            .into_iter()
            .filter(|item| !item.id.is_empty())
            .map(PixivSearchItem::from)
            .collect::<Vec<_>>();
        if !items.is_empty() && feed.last_page < page {
            return Err(unexpected("Pixiv search pagination is inconsistent"));
        }
        let last_page = feed.last_page;
        Ok(PixivSearchResult {
            profile: key.profile.clone(),
            generation,
            query: query.to_owned(),
            page,
            last_page,
            next_page: (!items.is_empty() && page < last_page).then_some(page + 1),
            items,
        })
    }

    pub(crate) async fn ranking(
        &self,
        key: &ProfileKey,
        mode: &str,
        date: &str,
        page: u32,
        cancellation: CancellationToken,
    ) -> Result<PixivRankingResult, CoreError> {
        let (mode, web_mode) = ensure_pixiv_ranking(key, mode, date, page)?;
        let mut query = vec![
            ("mode".to_owned(), web_mode.to_owned()),
            ("content".to_owned(), "all".to_owned()),
            ("p".to_owned(), page.to_string()),
            ("format".to_owned(), "json".to_owned()),
        ];
        if !date.is_empty() {
            query.push(("date".to_owned(), date.replace('-', "")));
        }
        let response = self
            .sessions
            .get_pixiv_ajax(key, "ranking.php", &query, "ranking.php", cancellation)
            .await?;
        let generation = response.generation;
        let body: RankingBody = serde_json::from_slice(&response.body)
            .map_err(|_| unexpected("Pixiv ranking response shape is invalid"))?;
        let items = body
            .contents
            .into_iter()
            .filter_map(PixivRankingItem::from_body)
            .collect::<Vec<_>>();
        if body.next.is_some_and(|next| next <= page) {
            return Err(unexpected("Pixiv ranking pagination is inconsistent"));
        }
        Ok(PixivRankingResult {
            profile: key.profile.clone(),
            generation,
            mode: mode.to_owned(),
            date: date.to_owned(),
            page,
            next_page: (!items.is_empty()).then_some(body.next).flatten(),
            items,
        })
    }

    pub(crate) async fn recommendations(
        &self,
        key: &ProfileKey,
        cancellation: CancellationToken,
    ) -> Result<PixivRecommendationResult, CoreError> {
        ensure_pixiv_profile(key)?;
        let response = self
            .sessions
            .get_pixiv_ajax(
                key,
                "ajax/discovery/artworks",
                &[
                    ("mode".to_owned(), "all".to_owned()),
                    ("limit".to_owned(), "100".to_owned()),
                    ("lang".to_owned(), "zh".to_owned()),
                ],
                "discovery",
                cancellation,
            )
            .await?;
        let generation = response.generation;
        let result: AjaxResponse<DiscoveryBody> = parse_ajax(&response.body)?;
        let items = result
            .body
            .and_then(|body| body.thumbnails)
            .map(|thumbnails| thumbnails.illust)
            .ok_or_else(|| unexpected("Pixiv discovery response has no illustration feed"))?
            .into_iter()
            .filter(|item| !item.id.is_empty())
            .map(PixivSearchItem::from)
            .collect();
        Ok(PixivRecommendationResult {
            profile: key.profile.clone(),
            generation,
            items,
        })
    }

    pub(crate) async fn following(
        &self,
        key: &ProfileKey,
        visibility: PixivFollowingVisibility,
        page: u32,
        cancellation: CancellationToken,
    ) -> Result<PixivFollowingResult, CoreError> {
        ensure_pixiv_page(key, page, "following")?;
        let mode = match visibility {
            PixivFollowingVisibility::Public => "all",
            PixivFollowingVisibility::Private => "r18",
        };
        let response = self
            .sessions
            .get_authenticated_pixiv_ajax(
                key,
                "ajax/follow_latest/illust",
                &[
                    ("p".to_owned(), page.to_string()),
                    ("mode".to_owned(), mode.to_owned()),
                    ("lang".to_owned(), "zh".to_owned()),
                ],
                "bookmark_new_illust.php",
                cancellation,
            )
            .await?;
        let generation = response.generation;
        let result: AjaxResponse<FollowingBody> = parse_ajax(&response.body)?;
        let body = result
            .body
            .ok_or_else(|| unexpected("Pixiv following response has no body"))?;
        let items = body
            .thumbnails
            .map(|thumbnails| thumbnails.illust)
            .ok_or_else(|| unexpected("Pixiv following response has no illustration feed"))?
            .into_iter()
            .filter(|item| !item.id.is_empty())
            .map(PixivSearchItem::from)
            .collect::<Vec<_>>();
        let is_last_page = body
            .page
            .ok_or_else(|| unexpected("Pixiv following response has no pagination state"))?
            .is_last_page;
        Ok(PixivFollowingResult {
            profile: key.profile.clone(),
            generation,
            visibility,
            page,
            next_page: (!items.is_empty() && !is_last_page).then_some(page + 1),
            items,
        })
    }

    pub(crate) async fn bookmarks(
        &self,
        key: &ProfileKey,
        visibility: PixivBookmarkVisibility,
        offset: u32,
        cancellation: CancellationToken,
    ) -> Result<PixivBookmarksResult, CoreError> {
        ensure_pixiv_offset(key, offset, "bookmarks")?;
        let rest = match visibility {
            PixivBookmarkVisibility::Public => "show",
            PixivBookmarkVisibility::Private => "hide",
        };
        const LIMIT: u32 = 48;
        let response = self
            .sessions
            .get_current_user_pixiv_ajax(
                key,
                &[
                    ("tag".to_owned(), String::new()),
                    ("offset".to_owned(), offset.to_string()),
                    ("limit".to_owned(), LIMIT.to_string()),
                    ("rest".to_owned(), rest.to_owned()),
                    ("lang".to_owned(), "zh".to_owned()),
                ],
                cancellation,
                |user_id| {
                    (
                        format!("ajax/user/{user_id}/illusts/bookmarks"),
                        format!("users/{user_id}/bookmarks/artworks"),
                    )
                },
            )
            .await?;
        let generation = response.generation;
        let result: AjaxResponse<BookmarksBody> = parse_ajax(&response.body)?;
        let body = result
            .body
            .ok_or_else(|| unexpected("Pixiv bookmarks response has no body"))?;
        let items = body
            .works
            .into_iter()
            .filter(|item| !item.id.is_empty())
            .map(PixivSearchItem::from)
            .collect::<Vec<_>>();
        let next_offset = offset
            .checked_add(LIMIT)
            .filter(|next| !items.is_empty() && *next < body.total);
        Ok(PixivBookmarksResult {
            profile: key.profile.clone(),
            generation,
            visibility,
            offset,
            limit: LIMIT,
            total: body.total,
            next_offset,
            items,
        })
    }
}

#[derive(Deserialize)]
struct DiscoveryBody {
    thumbnails: Option<DiscoveryThumbnails>,
}

#[derive(Deserialize)]
struct DiscoveryThumbnails {
    #[serde(default)]
    illust: Vec<SearchItemBody>,
}

#[derive(Deserialize)]
struct FollowingBody {
    thumbnails: Option<DiscoveryThumbnails>,
    page: Option<FollowingPage>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct FollowingPage {
    is_last_page: bool,
}

#[derive(Deserialize)]
struct BookmarksBody {
    #[serde(default)]
    works: Vec<SearchItemBody>,
    #[serde(default, deserialize_with = "u32_from_any")]
    total: u32,
}

#[derive(Deserialize)]
struct RankingBody {
    #[serde(default)]
    contents: Vec<RankingItemBody>,
    #[serde(default, deserialize_with = "optional_u32_from_any")]
    next: Option<u32>,
}

#[derive(Deserialize)]
struct RankingItemBody {
    #[serde(default, deserialize_with = "u32_from_any")]
    rank: u32,
    #[serde(
        default,
        alias = "yes_rank",
        deserialize_with = "optional_u32_from_any"
    )]
    previous_rank: Option<u32>,
    #[serde(
        default,
        alias = "illustId",
        alias = "illust_id",
        deserialize_with = "string_from_any"
    )]
    id: String,
    #[serde(default)]
    title: String,
    #[serde(default, alias = "userId", deserialize_with = "string_from_any")]
    user_id: String,
    #[serde(default, alias = "userName")]
    user_name: String,
    #[serde(
        default = "one",
        alias = "pageCount",
        alias = "illust_page_count",
        deserialize_with = "u32_from_any"
    )]
    page_count: u32,
    #[serde(default, alias = "xRestrict", deserialize_with = "u32_from_any")]
    x_restrict: u32,
    #[serde(default, alias = "url")]
    thumbnail_url: Option<Url>,
    #[serde(default)]
    tags: Vec<String>,
}

impl PixivRankingItem {
    fn from_body(item: RankingItemBody) -> Option<Self> {
        if item.id.is_empty() || item.rank == 0 {
            return None;
        }
        Some(Self {
            rank: item.rank,
            previous_rank: item.previous_rank,
            id: item.id,
            title: item.title,
            user: PixivUser {
                id: item.user_id,
                name: item.user_name,
            },
            page_count: item.page_count,
            x_restrict: item.x_restrict,
            thumbnail_url: item.thumbnail_url,
            tags: item.tags,
        })
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SearchBody {
    illust_manga: Option<SearchFeed>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SearchFeed {
    #[serde(default)]
    data: Vec<SearchItemBody>,
    #[serde(default)]
    last_page: u32,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SearchItemBody {
    #[serde(default)]
    id: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    user_id: String,
    #[serde(default)]
    user_name: String,
    #[serde(default = "one")]
    page_count: u32,
    #[serde(default)]
    x_restrict: u32,
    #[serde(default)]
    url: Option<Url>,
    #[serde(default)]
    tags: Vec<String>,
}

impl From<SearchItemBody> for PixivSearchItem {
    fn from(item: SearchItemBody) -> Self {
        Self {
            id: item.id,
            title: item.title,
            user: PixivUser {
                id: item.user_id,
                name: item.user_name,
            },
            page_count: item.page_count,
            x_restrict: item.x_restrict,
            thumbnail_url: item.url,
            tags: item.tags,
        }
    }
}

#[derive(Deserialize)]
struct AjaxResponse<T> {
    #[serde(default)]
    error: bool,
    #[serde(default)]
    message: String,
    body: Option<T>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct DetailBody {
    id: String,
    title: String,
    #[serde(default)]
    description: String,
    #[serde(default)]
    illust_type: u32,
    #[serde(default = "one")]
    page_count: u32,
    #[serde(default)]
    width: u32,
    #[serde(default)]
    height: u32,
    #[serde(default)]
    x_restrict: u32,
    #[serde(default)]
    view_count: u64,
    #[serde(default)]
    bookmark_count: u64,
    bookmark_data: Option<serde_json::Value>,
    #[serde(default)]
    create_date: String,
    #[serde(default)]
    user_id: String,
    #[serde(default)]
    user_name: String,
    #[serde(default)]
    tags: TagsBody,
}

#[derive(Default, Deserialize)]
struct TagsBody {
    #[serde(default)]
    tags: Vec<TagBody>,
}

#[derive(Deserialize)]
struct TagBody {
    tag: String,
}

#[derive(Deserialize)]
struct PageBody {
    urls: PageUrls,
}

#[derive(Deserialize)]
struct PageUrls {
    original: Url,
    #[serde(default)]
    regular: Option<Url>,
    #[serde(default)]
    small: Option<Url>,
}

fn parse_ajax<T: for<'de> Deserialize<'de>>(bytes: &[u8]) -> Result<T, CoreError> {
    let value: AjaxResponse<serde_json::Value> = serde_json::from_slice(bytes)
        .map_err(|_| unexpected("Pixiv AJAX returned malformed JSON"))?;
    if value.error {
        return Err(CoreError::new(
            ErrorCode::AccessDenied,
            if value.message.is_empty() {
                "Pixiv AJAX rejected the request".to_owned()
            } else {
                format!("Pixiv AJAX rejected the request: {}", value.message)
            },
            false,
        ));
    }
    serde_json::from_slice(bytes).map_err(|_| unexpected("Pixiv AJAX response shape is invalid"))
}

fn map_illust(
    response_url: &Url,
    requested_id: &str,
    body: DetailBody,
    pages: Vec<PageBody>,
) -> Result<PixivIllust, CoreError> {
    if body.id != requested_id || pages.is_empty() || pages.len() != body.page_count as usize {
        return Err(unexpected(
            "Pixiv detail and page metadata are inconsistent",
        ));
    }
    let mut page_url = response_url.clone();
    page_url.set_path(&format!("artworks/{requested_id}"));
    page_url.set_query(None);
    page_url.set_fragment(None);
    Ok(PixivIllust {
        id: body.id,
        page_url,
        title: body.title,
        caption: body.description,
        illust_type: body.illust_type,
        page_count: body.page_count,
        width: body.width,
        height: body.height,
        x_restrict: body.x_restrict,
        view_count: body.view_count,
        bookmark_count: body.bookmark_count,
        bookmarked: body.bookmark_data.is_some(),
        created_at: body.create_date,
        user: PixivUser {
            id: body.user_id,
            name: body.user_name,
        },
        tags: body.tags.tags.into_iter().map(|tag| tag.tag).collect(),
        pages: pages
            .into_iter()
            .enumerate()
            .map(|(index, page)| PixivPage {
                index: index as u32,
                original_url: page.urls.original,
                regular_url: page.urls.regular,
                small_url: page.urls.small,
            })
            .collect(),
    })
}

fn ensure_pixiv(key: &ProfileKey, illust_id: &str) -> Result<(), CoreError> {
    if ensure_pixiv_profile(key).is_err()
        || illust_id.is_empty()
        || !illust_id.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(CoreError::new(
            ErrorCode::InvalidInput,
            "Pixiv profile and numeric illustration ID are required",
            false,
        ));
    }
    Ok(())
}

fn ensure_pixiv_profile(key: &ProfileKey) -> Result<(), CoreError> {
    if key.provider != "pixiv" {
        return Err(CoreError::new(
            ErrorCode::InvalidInput,
            "Pixiv profile is required",
            false,
        ));
    }
    Ok(())
}

fn ensure_pixiv_page(key: &ProfileKey, page: u32, feed: &str) -> Result<(), CoreError> {
    ensure_pixiv_profile(key)?;
    if page == 0 || page > 1_000 {
        return Err(CoreError::new(
            ErrorCode::InvalidInput,
            format!("Pixiv {feed} page must be from 1 to 1000"),
            false,
        ));
    }
    Ok(())
}

fn ensure_pixiv_offset(key: &ProfileKey, offset: u32, feed: &str) -> Result<(), CoreError> {
    ensure_pixiv_profile(key)?;
    if offset > 48_000 {
        return Err(CoreError::new(
            ErrorCode::InvalidInput,
            format!("Pixiv {feed} offset must not exceed 48000"),
            false,
        ));
    }
    Ok(())
}

fn ensure_pixiv_search(key: &ProfileKey, query: &str, page: u32) -> Result<(), CoreError> {
    if key.provider != "pixiv"
        || query.trim().is_empty()
        || query.len() > 500
        || page == 0
        || page > 1_000
    {
        return Err(CoreError::new(
            ErrorCode::InvalidInput,
            "Pixiv search requires a bounded query and page from 1 to 1000",
            false,
        ));
    }
    Ok(())
}

fn ensure_pixiv_ranking<'a>(
    key: &ProfileKey,
    mode: &'a str,
    date: &str,
    page: u32,
) -> Result<(&'a str, &'static str), CoreError> {
    let mode = mode.trim();
    let web_mode = match mode {
        "day" => "daily",
        "week" => "weekly",
        "month" => "monthly",
        _ => return Err(invalid_ranking()),
    };
    let valid_date = if date.is_empty() {
        true
    } else {
        let format = time::format_description::parse("[year]-[month]-[day]")
            .map_err(|_| invalid_ranking())?;
        time::Date::parse(date, &format).is_ok() && date.len() == 10
    };
    if key.provider != "pixiv" || page == 0 || page > 1_000 || !valid_date {
        return Err(invalid_ranking());
    }
    Ok((mode, web_mode))
}

fn invalid_ranking() -> CoreError {
    CoreError::new(
        ErrorCode::InvalidInput,
        "Pixiv ranking requires mode day/week/month, an optional YYYY-MM-DD date, and page from 1 to 1000",
        false,
    )
}

fn string_from_any<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_json::Value::deserialize(deserializer)?;
    Ok(match value {
        serde_json::Value::String(value) => value,
        serde_json::Value::Number(value) => value.to_string(),
        _ => String::new(),
    })
}

fn u32_from_any<'de, D>(deserializer: D) -> Result<u32, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_json::Value::deserialize(deserializer)?;
    Ok(match value {
        serde_json::Value::Number(value) => value.as_u64().and_then(|value| value.try_into().ok()),
        serde_json::Value::String(value) => value.parse().ok(),
        _ => None,
    }
    .unwrap_or_default())
}

fn optional_u32_from_any<'de, D>(deserializer: D) -> Result<Option<u32>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = serde_json::Value::deserialize(deserializer)?;
    Ok(match value {
        serde_json::Value::Number(value) => value.as_u64().and_then(|value| value.try_into().ok()),
        serde_json::Value::String(value) => value.parse().ok(),
        _ => None,
    })
}

fn encode_path_segment(value: &str) -> Result<String, CoreError> {
    let mut url = Url::parse("https://pixiv.invalid/")
        .map_err(|_| unexpected("failed to create Pixiv search URL"))?;
    url.path_segments_mut()
        .map_err(|_| unexpected("failed to create Pixiv search URL"))?
        .push(value);
    Ok(url.path().trim_start_matches('/').to_owned())
}

const fn one() -> u32 {
    1
}

fn unavailable(id: &str) -> CoreError {
    CoreError::new(
        ErrorCode::ResourceNotFound,
        format!("Pixiv illustration {id} does not exist or is inaccessible"),
        false,
    )
}

fn unexpected(message: impl Into<String>) -> CoreError {
    CoreError::new(ErrorCode::UnexpectedResponse, message, false)
}

#[cfg(test)]
mod tests {
    use super::{
        BookmarksBody, DetailBody, DiscoveryBody, FollowingBody, PageBody, RankingBody, SearchBody,
        encode_path_segment, map_illust, parse_ajax,
    };

    #[test]
    fn maps_detail_and_page_fixtures() {
        let detail: super::AjaxResponse<DetailBody> =
            parse_ajax(include_bytes!("../../tests/fixtures/pixiv/illust.json")).unwrap();
        let pages: super::AjaxResponse<Vec<PageBody>> =
            parse_ajax(include_bytes!("../../tests/fixtures/pixiv/pages.json")).unwrap();
        let illust = map_illust(
            &url::Url::parse("https://www.pixiv.net/ajax/illust/12345678").unwrap(),
            "12345678",
            detail.body.unwrap(),
            pages.body.unwrap(),
        )
        .unwrap();
        assert_eq!(illust.title, "Fixture illustration");
        assert_eq!(illust.user.id, "87654321");
        assert_eq!(illust.tags, ["original", "風景"]);
        assert_eq!(illust.pages.len(), 2);
        assert!(illust.pages[1].original_url.as_str().ends_with("_p1.png"));
    }

    #[test]
    fn parses_search_fixture_and_encodes_one_path_segment() {
        let search: super::AjaxResponse<SearchBody> =
            parse_ajax(include_bytes!("../../tests/fixtures/pixiv/search.json")).unwrap();
        let feed = search.body.unwrap().illust_manga.unwrap();
        assert_eq!(feed.last_page, 3);
        let item = super::PixivSearchItem::from(feed.data.into_iter().next().unwrap());
        assert_eq!(item.id, "12345");
        assert_eq!(item.tags, ["landscape", "sky"]);
        assert_eq!(
            encode_path_segment("風景 / sky").unwrap(),
            "%E9%A2%A8%E6%99%AF%20%2F%20sky"
        );
    }

    #[test]
    fn parses_ranking_fixture_with_string_and_numeric_fields() {
        let ranking: RankingBody =
            serde_json::from_slice(include_bytes!("../../tests/fixtures/pixiv/ranking.json"))
                .unwrap();
        assert_eq!(ranking.next, Some(2));
        let item = super::PixivRankingItem::from_body(ranking.contents.into_iter().next().unwrap())
            .unwrap();
        assert_eq!(item.rank, 1);
        assert_eq!(item.previous_rank, Some(3));
        assert_eq!(item.id, "99887766");
        assert_eq!(item.page_count, 2);
    }

    #[test]
    fn validates_ranking_mode_date_and_page() {
        let key = crate::ProfileKey::new("pixiv", "default");
        assert_eq!(
            super::ensure_pixiv_ranking(&key, "day", "2026-07-25", 1).unwrap(),
            ("day", "daily")
        );
        assert!(super::ensure_pixiv_ranking(&key, "daily", "", 1).is_err());
        assert!(super::ensure_pixiv_ranking(&key, "day", "2026-02-30", 1).is_err());
        assert!(super::ensure_pixiv_ranking(&key, "day", "", 0).is_err());
    }

    #[test]
    fn parses_discovery_fixture_without_inventing_pagination() {
        let discovery: super::AjaxResponse<DiscoveryBody> =
            parse_ajax(include_bytes!("../../tests/fixtures/pixiv/discovery.json")).unwrap();
        let items = discovery.body.unwrap().thumbnails.unwrap().illust;
        assert_eq!(items.len(), 2);
        let item = super::PixivSearchItem::from(items.into_iter().next().unwrap());
        assert_eq!(item.id, "11223344");
        assert_eq!(item.title, "Discovery Fixture");
        assert_eq!(item.tags, ["original", "landscape"]);
    }

    #[test]
    fn parses_following_fixture_and_pagination_state() {
        let following: super::AjaxResponse<FollowingBody> =
            parse_ajax(include_bytes!("../../tests/fixtures/pixiv/following.json")).unwrap();
        let body = following.body.unwrap();
        assert!(!body.page.unwrap().is_last_page);
        let item = super::PixivSearchItem::from(
            body.thumbnails.unwrap().illust.into_iter().next().unwrap(),
        );
        assert_eq!(item.id, "44332211");
        assert_eq!(item.title, "Following Fixture");
    }

    #[test]
    fn parses_bookmarks_fixture_and_total() {
        let bookmarks: super::AjaxResponse<BookmarksBody> =
            parse_ajax(include_bytes!("../../tests/fixtures/pixiv/bookmarks.json")).unwrap();
        let body = bookmarks.body.unwrap();
        assert_eq!(body.total, 49);
        let item = super::PixivSearchItem::from(body.works.into_iter().next().unwrap());
        assert_eq!(item.id, "77889900");
        assert_eq!(item.title, "Bookmark Fixture");
    }
}
