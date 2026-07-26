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
    if key.provider != "pixiv"
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
    use super::{DetailBody, PageBody, SearchBody, encode_path_segment, map_illust, parse_ajax};

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
}
