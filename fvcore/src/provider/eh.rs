//! EH front-page browsing, gallery identity, and official Archive option discovery.

use crate::{CoreError, ErrorCode, ProfileKey, session::SessionRegistry};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, sync::Arc};
use tokio_util::sync::CancellationToken;
use url::Url;

const EH_MAX_GALLERY_PAGES: u32 = 2_000;
type ParsedHome = (
    Vec<EhGallerySummary>,
    Option<EhPageCursor>,
    Option<EhPageCursor>,
);

/// Direction of an EH seek cursor.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EhPageDirection {
    /// Seek toward newer galleries.
    Previous,
    /// Seek toward older galleries.
    Next,
}

/// Opaque-enough EH page cursor represented without accepting arbitrary URLs.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EhPageCursor {
    /// Seek direction.
    pub direction: EhPageDirection,
    /// Gallery ID used by EH as the seek boundary.
    pub gid: u64,
}

/// One gallery entry from an EH listing page.
#[derive(Clone, Debug, Serialize)]
pub struct EhGallerySummary {
    /// Stable gallery identity.
    pub gallery: EhGalleryRef,
    /// Canonical gallery page URL found in the listing.
    pub page_url: Url,
    /// Display title.
    pub title: String,
    /// EH category label, such as `Doujinshi` or `Manga`.
    pub category: Option<String>,
    /// Published timestamp as displayed by EH.
    pub published: Option<String>,
    /// Uploader name when exposed by the selected EH display mode.
    pub uploader: Option<String>,
    /// Number of gallery pages when exposed by the selected EH display mode.
    pub page_count: Option<u32>,
    /// Rating from 0.5 to 5.0 when exposed by the selected EH display mode.
    pub rating: Option<f32>,
    /// Gallery language excluding the `translated` marker.
    pub language: Option<String>,
    /// Provider-qualified tags excluding the language tag.
    pub tags: Vec<String>,
    /// Remote cover URL when exposed by the selected EH display mode.
    pub cover_url: Option<Url>,
    /// Cover display width supplied by EH.
    pub cover_width: Option<u32>,
    /// Cover display height supplied by EH.
    pub cover_height: Option<u32>,
}

/// One parsed EH front-page response.
#[derive(Clone, Debug, Serialize)]
pub struct EhHomePage {
    /// Profile that executed the request.
    pub profile: String,
    /// Session generation used for the complete response body.
    pub generation: u64,
    /// Parsed galleries in page order.
    pub galleries: Vec<EhGallerySummary>,
    /// Cursor for newer galleries.
    pub previous: Option<EhPageCursor>,
    /// Cursor for older galleries.
    pub next: Option<EhPageCursor>,
}

/// One comment displayed on an EH gallery page.
#[derive(Clone, Debug, Serialize)]
pub struct EhComment {
    /// Numeric comment ID as exposed by EH.
    pub id: String,
    /// Comment author.
    pub user_name: String,
    /// Displayed posting time, or `unknown` when absent.
    pub posted: String,
    /// Plain-text comment body.
    pub content: String,
    /// Current comment score when available.
    pub score: Option<i32>,
    /// Current user's vote: `-1`, `0`, or `1`.
    pub vote_status: i8,
}

/// Another gallery in the same EH version chain.
#[derive(Clone, Debug, Serialize)]
pub struct EhGalleryVersion {
    /// Gallery identity when the link is valid.
    pub gallery: Option<EhGalleryRef>,
    /// Gallery URL supplied by EH.
    pub page_url: Url,
    /// Display title.
    pub title: String,
    /// Added timestamp displayed by EH.
    pub posted: Option<String>,
}

/// Parsed metadata for one EH gallery.
#[derive(Clone, Debug, Serialize)]
pub struct EhGalleryDetail {
    /// Profile that executed the request.
    pub profile: String,
    /// Session generation used for the complete response body.
    pub generation: u64,
    /// Stable gallery identity.
    pub gallery: EhGalleryRef,
    /// Canonical gallery URL.
    pub page_url: Url,
    /// Primary title.
    pub title: String,
    /// Secondary title when present.
    pub subtitle: Option<String>,
    /// Remote cover URL when present.
    pub cover_url: Option<Url>,
    /// Tags grouped by the namespace displayed by EH.
    pub tags: BTreeMap<String, Vec<String>>,
    /// Average rating when present.
    pub rating: Option<f32>,
    /// Number of ratings.
    pub rating_count: u64,
    /// Number of gallery pages.
    pub page_count: u32,
    /// Whether the current account has favorited the gallery.
    pub is_favorite: bool,
    /// Zero-based favorite category when it can be inferred.
    pub favorite_category: Option<u8>,
    /// Gallery token embedded in page scripts, used by later image APIs.
    pub page_token: Option<String>,
    /// Uploader name.
    pub uploader: Option<String>,
    /// Posted timestamp displayed by EH.
    pub posted: Option<String>,
    /// Parent gallery URL or text.
    pub parent: Option<String>,
    /// Gallery visibility text.
    pub visible: Option<String>,
    /// Gallery language detail text.
    pub language: Option<String>,
    /// Gallery file size text.
    pub file_size: Option<String>,
    /// Number of users who favorited the gallery.
    pub favorite_count: u64,
    /// Parsed comments in page order.
    pub comments: Vec<EhComment>,
    /// Newer galleries listed in the version chain.
    pub newer_versions: Vec<EhGalleryVersion>,
}

/// One gallery page thumbnail.
#[derive(Clone, Debug, Serialize)]
pub struct EhThumbnail {
    /// Thumbnail URL. Sprite crops append the local `@x=...&y=...` directive.
    pub image_url: String,
    /// EH image page URL.
    pub page_url: Url,
    /// Zero-based gallery page index parsed from the EH image-page URL.
    pub page: u32,
    /// Display width supplied by EH.
    pub width: Option<u32>,
    /// Display height supplied by EH.
    pub height: Option<u32>,
}

/// One zero-based page of EH gallery thumbnails.
#[derive(Clone, Debug, Serialize)]
pub struct EhThumbnailPage {
    /// Profile that executed the request.
    pub profile: String,
    /// Session generation used for the complete response body.
    pub generation: u64,
    /// Stable gallery identity.
    pub gallery: EhGalleryRef,
    /// Zero-based thumbnail page requested from EH.
    pub page: u32,
    /// Parsed thumbnails in gallery order.
    pub items: Vec<EhThumbnail>,
    /// Next zero-based page when exposed by EH.
    pub next_page: Option<u32>,
}

/// Resolved original image metadata for one EH gallery page.
#[derive(Clone, Debug, Serialize)]
pub struct EhImageResolution {
    /// Resolved remote original-image URL.
    pub url: Url,
    /// Referer required when fetching the image.
    pub referer: Url,
    /// Optional EH reload nonce for a subsequent resolution attempt.
    pub next_nl: Option<String>,
}

enum EhImageKey {
    Show(String),
    Mpv {
        key: String,
        image_keys: Vec<String>,
    },
}

/// Stable EH gallery identity accepted by Archive methods.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EhGalleryRef {
    /// Numeric gallery ID.
    pub gid: u64,
    /// Gallery token from the EH URL.
    pub token: String,
}

impl EhGalleryRef {
    /// Parses an e-hentai.org or exhentai.org gallery URL.
    pub fn parse(input: &str) -> Result<Self, CoreError> {
        let url = Url::parse(input).map_err(|_| invalid_gallery())?;
        if !matches!(url.scheme(), "http" | "https")
            || !matches!(url.host_str(), Some("e-hentai.org" | "exhentai.org"))
        {
            return Err(invalid_gallery());
        }
        let mut segments = url
            .path_segments()
            .ok_or_else(invalid_gallery)?
            .filter(|segment| !segment.is_empty());
        if segments.next() != Some("g") {
            return Err(invalid_gallery());
        }
        let gid = segments
            .next()
            .and_then(|value| value.parse::<u64>().ok())
            .filter(|value| *value > 0)
            .ok_or_else(invalid_gallery)?;
        let token = segments.next().ok_or_else(invalid_gallery)?;
        if segments.next().is_some() || !valid_token(token) {
            return Err(invalid_gallery());
        }
        Ok(Self {
            gid,
            token: token.to_ascii_lowercase(),
        })
    }
}

/// Delivery method for one EH Archive option.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EhArchiveDelivery {
    /// A direct Archive URL can be resolved and downloaded by fvcore.
    Archive,
    /// EH sends the work to a linked H@H client; fvcore cannot download it locally.
    Hath,
}

/// One official EH Archive option.
#[derive(Clone, Debug, Serialize)]
pub struct EhArchiveOption {
    /// Stable option ID submitted back to the Core.
    pub id: String,
    /// Display title supplied or derived from EH.
    pub title: String,
    /// Estimated Archive size text.
    pub estimated_size: Option<String>,
    /// Download cost text.
    pub cost: Option<String>,
    /// Delivery mechanism.
    pub delivery: EhArchiveDelivery,
    /// Whether this option can create a local fvcore download task.
    pub locally_downloadable: bool,
}

/// Archive options returned for one gallery.
#[derive(Clone, Debug, Serialize)]
pub struct EhArchiveOptions {
    /// Profile that executed the request.
    pub profile: String,
    /// Session generation used for the complete response body.
    pub generation: u64,
    /// Gallery identity.
    pub gallery: EhGalleryRef,
    /// Parsed options in page order.
    pub options: Vec<EhArchiveOption>,
}

/// Official EH Archive variant that can produce a local download.
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EhArchiveVariant {
    /// Original-resolution Archive, normally consuming GP or free quota.
    Original,
    /// Resampled Archive offered by EH.
    Resample,
}

pub(crate) struct EhService {
    sessions: Arc<SessionRegistry>,
}

impl EhService {
    pub(crate) fn new(sessions: Arc<SessionRegistry>) -> Self {
        Self { sessions }
    }

    pub(crate) async fn home(
        &self,
        key: &ProfileKey,
        cursor: Option<EhPageCursor>,
        cancellation: CancellationToken,
    ) -> Result<EhHomePage, CoreError> {
        ensure_eh(key)?;
        if cursor.is_some_and(|value| value.gid == 0) {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "EH page cursor GID must be positive",
                false,
            ));
        }
        let query = cursor.map_or_else(Vec::new, |value| {
            vec![(
                match value.direction {
                    EhPageDirection::Previous => "prev",
                    EhPageDirection::Next => "next",
                }
                .to_owned(),
                value.gid.to_string(),
            )]
        });
        let response = self
            .sessions
            .get_with_query(key, "", &query, crate::session::ApiAuth::None, cancellation)
            .await?;
        ensure_html(&response.content_type, "EH front page")?;
        let generation = response.generation;
        let final_url = response.final_url;
        let html = std::str::from_utf8(&response.body)
            .map_err(|_| unexpected("EH front page returned invalid UTF-8"))?;
        let (galleries, previous, next) = parse_home(html, &final_url)?;
        Ok(EhHomePage {
            profile: key.profile.clone(),
            generation,
            galleries,
            previous,
            next,
        })
    }

    pub(crate) async fn archive_options(
        &self,
        key: &ProfileKey,
        gallery: EhGalleryRef,
        cancellation: CancellationToken,
    ) -> Result<EhArchiveOptions, CoreError> {
        ensure_eh(key)?;
        validate_gallery(&gallery)?;
        let path = format!("archiver.php?gid={}&token={}", gallery.gid, gallery.token);
        let response = self.sessions.get(key, &path, cancellation).await?;
        ensure_html(&response.content_type, "EH Archive endpoint")?;
        let generation = response.generation;
        let html = std::str::from_utf8(&response.body)
            .map_err(|_| unexpected("EH Archive endpoint returned invalid UTF-8"))?;
        let options = parse_archive_options(html)?;
        Ok(EhArchiveOptions {
            profile: key.profile.clone(),
            generation,
            gallery,
            options,
        })
    }

    pub(crate) async fn gallery_detail(
        &self,
        key: &ProfileKey,
        gallery: EhGalleryRef,
        cancellation: CancellationToken,
    ) -> Result<EhGalleryDetail, CoreError> {
        ensure_eh(key)?;
        validate_gallery(&gallery)?;
        let path = format!("g/{}/{}/", gallery.gid, gallery.token);
        let response = self.sessions.get(key, &path, cancellation).await?;
        ensure_html(&response.content_type, "EH gallery page")?;
        let html = std::str::from_utf8(&response.body)
            .map_err(|_| unexpected("EH gallery page returned invalid UTF-8"))?;
        parse_gallery_detail(
            html,
            &response.final_url,
            key.profile.clone(),
            response.generation,
            gallery,
        )
    }

    pub(crate) async fn thumbnails(
        &self,
        key: &ProfileKey,
        gallery: EhGalleryRef,
        page: u32,
        cancellation: CancellationToken,
    ) -> Result<EhThumbnailPage, CoreError> {
        ensure_eh(key)?;
        validate_gallery(&gallery)?;
        if page >= EH_MAX_GALLERY_PAGES {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "EH thumbnail page is out of range",
                false,
            ));
        }
        let path = format!("g/{}/{}/", gallery.gid, gallery.token);
        let query = (page > 0).then(|| vec![("p".to_owned(), page.to_string())]);
        let response = self
            .sessions
            .get_with_query(
                key,
                &path,
                query.as_deref().unwrap_or_default(),
                crate::session::ApiAuth::None,
                cancellation,
            )
            .await?;
        ensure_html(&response.content_type, "EH thumbnail page")?;
        let html = std::str::from_utf8(&response.body)
            .map_err(|_| unexpected("EH thumbnail page returned invalid UTF-8"))?;
        let (items, next_page) = parse_thumbnails(html, &response.final_url, page)?;
        Ok(EhThumbnailPage {
            profile: key.profile.clone(),
            generation: response.generation,
            gallery,
            page,
            items,
            next_page,
        })
    }

    pub(crate) async fn resolve_original(
        &self,
        key: &ProfileKey,
        gallery: EhGalleryRef,
        page: u32,
        nl: Option<&str>,
        cancellation: CancellationToken,
    ) -> Result<EhImageResolution, CoreError> {
        ensure_eh(key)?;
        validate_gallery(&gallery)?;
        if page >= EH_MAX_GALLERY_PAGES {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "EH image page is out of range",
                false,
            ));
        }
        let first = self
            .thumbnails(key, gallery.clone(), 0, cancellation.child_token())
            .await?;
        let first_page_url = first
            .items
            .first()
            .map(|item| item.page_url.clone())
            .ok_or_else(|| unexpected("EH gallery contains no image page links"))?;
        let response = self
            .sessions
            .get_absolute(
                key,
                &first_page_url,
                None,
                2 * 1024 * 1024,
                cancellation.child_token(),
                |_, _| {},
            )
            .await?;
        ensure_html(&response.content_type, "EH image page")?;
        let html = std::str::from_utf8(&response.body)
            .map_err(|_| unexpected("EH image page returned invalid UTF-8"))?;
        let image_key = parse_image_key(html)?;
        let (method, key_name, key_value, image_key) = match image_key {
            EhImageKey::Mpv { key, image_keys } => {
                let image_key = image_keys.get(page as usize).cloned().ok_or_else(|| {
                    CoreError::new(
                        ErrorCode::InvalidInput,
                        format!("EH page {page} is outside the gallery"),
                        false,
                    )
                })?;
                ("imagedispatch", "mpvkey", key, image_key)
            }
            EhImageKey::Show(showkey) => {
                let thumbnail_page_size = first.items.len();
                if thumbnail_page_size == 0 {
                    return Err(unexpected("EH thumbnail page contains no image links"));
                }
                let target_page = page as usize / thumbnail_page_size;
                let target_index = page as usize % thumbnail_page_size;
                let thumbnails = if target_page == 0 {
                    first
                } else {
                    self.thumbnails(
                        key,
                        gallery.clone(),
                        u32::try_from(target_page).map_err(|_| {
                            CoreError::new(
                                ErrorCode::InvalidInput,
                                "EH image page is out of range",
                                false,
                            )
                        })?,
                        cancellation.child_token(),
                    )
                    .await?
                };
                let page_url = thumbnails
                    .items
                    .get(target_index)
                    .map(|item| &item.page_url)
                    .ok_or_else(|| {
                        CoreError::new(
                            ErrorCode::InvalidInput,
                            format!("EH page {page} is outside the gallery"),
                            false,
                        )
                    })?;
                let image_key = parse_image_key_from_url(page_url)?;
                ("showpage", "showkey", showkey, image_key)
            }
        };
        let mut payload = serde_json::json!({
            "gid": gallery.gid,
            "imgkey": image_key,
            "method": method,
            "page": page + 1,
            key_name: key_value,
        });
        if let Some(nl) = nl.filter(|value| !value.is_empty()) {
            payload["nl"] = serde_json::Value::String(nl.to_owned());
        }
        let response = self
            .sessions
            .post_eh_api(key, &payload, cancellation)
            .await?;
        ensure_json(&response.content_type, "EH image API")?;
        parse_image_api_response(method, &response.body, &response.final_url)
    }

    pub(crate) async fn submit_archive(
        &self,
        key: &ProfileKey,
        gallery: EhGalleryRef,
        variant: EhArchiveVariant,
        cancellation: CancellationToken,
    ) -> Result<Url, CoreError> {
        ensure_eh(key)?;
        validate_gallery(&gallery)?;
        let path = format!("archiver.php?gid={}&token={}", gallery.gid, gallery.token);
        let dltype = match variant {
            EhArchiveVariant::Original => "org",
            EhArchiveVariant::Resample => "res",
        };
        let response = self
            .sessions
            .post_eh_archive(
                key,
                &path,
                &format!(
                    "dltype={dltype}&dlcheck=Download+{}+Archive",
                    if dltype == "org" {
                        "Original"
                    } else {
                        "Resample"
                    }
                ),
                cancellation.child_token(),
            )
            .await?;
        ensure_html(&response.content_type, "EH Archive submission")?;
        let first = parse_first_link(&response.body, &response.final_url, "EH Archive submission")?;
        let intermediate = self
            .sessions
            .get_absolute(
                key,
                &first,
                Some(&response.final_url),
                2 * 1024 * 1024,
                cancellation,
                |_, _| {},
            )
            .await?;
        ensure_html(&intermediate.content_type, "EH Archive intermediate page")?;
        parse_first_link(
            &intermediate.body,
            &intermediate.final_url,
            "EH Archive intermediate page",
        )
    }
}

fn parse_first_link(body: &[u8], base: &Url, endpoint: &str) -> Result<Url, CoreError> {
    let html = std::str::from_utf8(body)
        .map_err(|_| unexpected(format!("{endpoint} returned invalid UTF-8")))?;
    let dom = tl::parse(html, tl::ParserOptions::default())
        .map_err(|_| unexpected(format!("{endpoint} contains malformed HTML")))?;
    let parser = dom.parser();
    dom.query_selector("a")
        .into_iter()
        .flatten()
        .filter_map(|node| node.get(parser).and_then(tl::Node::as_tag))
        .filter_map(|tag| attribute(tag, "href", parser))
        .find_map(|href| base.join(&href).ok())
        .filter(|url| {
            matches!(url.scheme(), "http" | "https")
                && url.username().is_empty()
                && url.password().is_none()
        })
        .ok_or_else(|| unexpected(format!("{endpoint} contains no valid download link")))
}

fn parse_image_key(html: &str) -> Result<EhImageKey, CoreError> {
    if let Some(captures) = Regex::new(r#"showkey\s*=\s*[\"']([^\"']+)[\"']"#)
        .expect("static EH showkey regex is valid")
        .captures(html)
    {
        return Ok(EhImageKey::Show(captures[1].to_owned()));
    }
    let mpvkey = Regex::new(r#"mpvkey\s*=\s*[\"']([^\"']+)[\"']"#)
        .expect("static EH mpvkey regex is valid")
        .captures(html)
        .map(|captures| captures[1].to_owned());
    let image_keys = Regex::new(r#"[\"']k[\"']\s*:\s*[\"']([^\"']+)[\"']"#)
        .expect("static EH image-key regex is valid")
        .captures_iter(html)
        .map(|captures| captures[1].to_owned())
        .collect::<Vec<_>>();
    match mpvkey {
        Some(key) if !image_keys.is_empty() => Ok(EhImageKey::Mpv { key, image_keys }),
        _ => Err(unexpected("EH image page contains no recognized image key")),
    }
}

fn parse_image_key_from_url(url: &Url) -> Result<String, CoreError> {
    let mut parts = url
        .path_segments()
        .ok_or_else(|| unexpected("EH image page URL has no path"))?;
    if parts.next() != Some("s") {
        return Err(unexpected("EH image page URL has an invalid path"));
    }
    parts
        .next()
        .filter(|value| !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_alphanumeric()))
        .map(str::to_owned)
        .ok_or_else(|| unexpected("EH image page URL contains an invalid image key"))
}

fn parse_image_api_response(
    method: &str,
    body: &[u8],
    api_url: &Url,
) -> Result<EhImageResolution, CoreError> {
    let value: serde_json::Value = serde_json::from_slice(body)
        .map_err(|_| unexpected("EH image API returned invalid JSON"))?;
    if let Some(error) = value.get("error").and_then(serde_json::Value::as_str) {
        return Err(unexpected(format!(
            "EH image API rejected the request: {error}"
        )));
    }
    let (image_url, next_nl) = if method == "imagedispatch" {
        (
            value.get("i").and_then(serde_json::Value::as_str),
            value
                .get("s")
                .and_then(serde_json::Value::as_str)
                .and_then(|value| (!value.is_empty()).then(|| value.to_owned())),
        )
    } else {
        let image_html = value
            .get("i3")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default();
        let image_url = Regex::new(r#"src=[\"']([^\"']+)[\"']"#)
            .expect("static EH API image regex is valid")
            .captures(image_html)
            .map(|captures| captures[1].to_owned());
        let next_nl = value
            .get("i6")
            .and_then(serde_json::Value::as_str)
            .and_then(|html| {
                Regex::new(r#"nl\([\"']([^\"']+)[\"']\)"#)
                    .expect("static EH nl regex is valid")
                    .captures(html)
                    .map(|captures| captures[1].to_owned())
            });
        return resolved_image(image_url.as_deref(), next_nl, api_url);
    };
    resolved_image(image_url, next_nl, api_url)
}

fn resolved_image(
    image_url: Option<&str>,
    next_nl: Option<String>,
    api_url: &Url,
) -> Result<EhImageResolution, CoreError> {
    let url = image_url
        .and_then(|value| Url::parse(value).ok())
        .filter(|url| {
            matches!(url.scheme(), "http" | "https")
                && url.username().is_empty()
                && url.password().is_none()
        })
        .ok_or_else(|| unexpected("EH image API returned no valid image URL"))?;
    let mut referer = api_url.clone();
    referer.set_path("/");
    referer.set_query(None);
    referer.set_fragment(None);
    Ok(EhImageResolution {
        url,
        referer,
        next_nl,
    })
}

fn parse_gallery_detail(
    html: &str,
    base_url: &Url,
    profile: String,
    generation: u64,
    gallery: EhGalleryRef,
) -> Result<EhGalleryDetail, CoreError> {
    if html.trim().is_empty() {
        return Err(unexpected("EH gallery page returned an empty response"));
    }
    let dom = tl::parse(html, tl::ParserOptions::default())
        .map_err(|_| unexpected("EH gallery page contains malformed HTML"))?;
    let parser = dom.parser();
    let title = document_text(&dom, "#gn").unwrap_or_default();
    if title.is_empty() {
        return Err(unexpected("EH gallery page is missing its title"));
    }
    let subtitle = document_text(&dom, "#gj");
    let uploader = document_text(&dom, "#gdn");
    let mut tags = BTreeMap::new();
    let tag_pattern =
        Regex::new(r"toggle_tagmenu\(\d+,'([^']+)'").expect("static EH tag regex is valid");
    if let Some(rows) = dom.query_selector("tr") {
        for row in rows.filter_map(|node| node.get(parser).and_then(tl::Node::as_tag)) {
            let Some(mut cells) = descendants(row, parser, "td") else {
                continue;
            };
            let Some(namespace) = cells
                .next()
                .and_then(|cell| nonempty(clean_text(&cell.inner_text(parser))))
                .map(|value| value.trim_end_matches(':').to_owned())
            else {
                continue;
            };
            let values: Vec<String> = descendants(row, parser, "a")
                .into_iter()
                .flatten()
                .filter_map(|tag| attribute(tag, "onclick", parser))
                .filter_map(|onclick| {
                    tag_pattern
                        .captures(&onclick)
                        .map(|captures| captures[1].to_owned())
                })
                .collect();
            if !values.is_empty() {
                tags.insert(namespace, values);
            }
        }
    }
    if let Some(category) = document_text(&dom, ".cs") {
        tags.insert("Category".to_owned(), vec![category]);
    }
    if let Some(value) = &uploader {
        tags.insert("uploader".to_owned(), vec![value.clone()]);
    }
    let page_count = dom
        .query_selector(".gdt2")
        .into_iter()
        .flatten()
        .filter_map(|node| node.get(parser).and_then(tl::Node::as_tag))
        .find_map(|tag| parse_page_count(&clean_text(&tag.inner_text(parser))))
        .unwrap_or(1);
    let favorite_link = document_text(&dom, "#favoritelink");
    let is_favorite = favorite_link
        .as_deref()
        .is_none_or(|value| !value.contains("Add to Favorites"));
    let favorite_category = dom
        .query_selector("#fav")
        .and_then(|mut nodes| nodes.next())
        .and_then(|node| node.get(parser).and_then(tl::Node::as_tag))
        .and_then(|tag| attribute(tag, "style", parser))
        .and_then(|style| {
            Regex::new(r"background-position:0px\s+-(\d+)px")
                .expect("static EH favorite regex is valid")
                .captures(&style)
                .and_then(|captures| captures[1].parse::<u32>().ok())
                .and_then(|position| position.checked_sub(2))
                .map(|position| (position / 19) as u8)
        })
        .filter(|_| is_favorite);
    let cover_url = dom
        .query_selector("#gleft #gd1 div")
        .and_then(|mut nodes| nodes.next())
        .and_then(|node| node.get(parser).and_then(tl::Node::as_tag))
        .and_then(|tag| attribute(tag, "style", parser))
        .and_then(|style| first_http_url(&style))
        .and_then(|value| Url::parse(&value).ok());
    let rating = document_text(&dom, "#rating_label").and_then(|label| {
        Regex::new(r"([0-9]+(?:\.[0-9]+)?)")
            .expect("static EH detail rating regex is valid")
            .captures_iter(&label)
            .last()
            .and_then(|captures| captures[1].parse().ok())
    });
    let rating_count = document_text(&dom, "#rating_count")
        .and_then(|value| parse_count(&value))
        .unwrap_or(0);
    let mut metadata = BTreeMap::new();
    if let Some(rows) = dom.query_selector("tr") {
        for row in rows.filter_map(|node| node.get(parser).and_then(tl::Node::as_tag)) {
            let Some(cells) = descendants(row, parser, "td") else {
                continue;
            };
            let cells: Vec<_> = cells.collect();
            if cells.len() < 2 {
                continue;
            }
            let key = clean_text(&cells[0].inner_text(parser));
            let value = if key.starts_with("Parent") {
                descendants(cells[1], parser, "a")
                    .and_then(|mut links| links.next())
                    .and_then(|link| attribute(link, "href", parser))
                    .unwrap_or_else(|| clean_text(&cells[1].inner_text(parser)))
            } else {
                clean_text(&cells[1].inner_text(parser))
            };
            metadata.insert(key.trim_end_matches(':').to_owned(), value);
        }
    }
    let page_token = Regex::new(r#"var\s+token\s*=\s*[\"']([^\"']+)[\"']"#)
        .expect("static EH page token regex is valid")
        .captures(html)
        .map(|captures| captures[1].to_owned());
    let comments = parse_comments(&dom);
    let newer_versions = parse_versions(&dom, html, base_url);
    Ok(EhGalleryDetail {
        profile,
        generation,
        gallery,
        page_url: base_url.clone(),
        title,
        subtitle,
        cover_url,
        tags,
        rating,
        rating_count,
        page_count,
        is_favorite,
        favorite_category,
        page_token,
        uploader,
        posted: metadata.get("Posted").cloned().and_then(nonempty),
        parent: metadata.get("Parent").cloned().and_then(nonempty),
        visible: metadata.get("Visible").cloned().and_then(nonempty),
        language: metadata.get("Language").cloned().and_then(nonempty),
        file_size: metadata.get("File Size").cloned().and_then(nonempty),
        favorite_count: metadata
            .get("Favorited")
            .and_then(|value| match value.as_str() {
                "Never" => Some(0),
                "Once" => Some(1),
                _ => parse_count(value),
            })
            .unwrap_or(0),
        comments,
        newer_versions,
    })
}

fn parse_comments(dom: &tl::VDom<'_>) -> Vec<EhComment> {
    let parser = dom.parser();
    dom.query_selector(".c1")
        .into_iter()
        .flatten()
        .filter_map(|node| node.get(parser).and_then(tl::Node::as_tag))
        .map(|comment| {
            let header = first_text(comment, parser, ".c3").unwrap_or_default();
            let posted = Regex::new(r"Posted on\s+(.+?)\s+by\b")
                .expect("static EH comment time regex is valid")
                .captures(&header)
                .map_or_else(|| "unknown".to_owned(), |captures| captures[1].to_owned());
            let html = comment.inner_html(parser);
            let id = Regex::new(r"comment_vote_(?:up|down)_(\d+)")
                .expect("static EH comment ID regex is valid")
                .captures(&html)
                .map_or_else(|| "0".to_owned(), |captures| captures[1].to_owned());
            let selected = |direction: &str| {
                descendants(comment, parser, &format!("#comment_vote_{direction}_{id}"))
                    .and_then(|mut nodes| nodes.next())
                    .and_then(|tag| attribute(tag, "style", parser))
                    .is_some_and(|style| !style.is_empty())
            };
            let vote_status = if selected("up") {
                1
            } else if selected("down") {
                -1
            } else {
                0
            };
            EhComment {
                id,
                user_name: descendants(comment, parser, ".c3")
                    .and_then(|mut nodes| nodes.next())
                    .and_then(|header| descendants(header, parser, "a"))
                    .and_then(|mut nodes| nodes.next())
                    .and_then(|tag| nonempty(clean_text(&tag.inner_text(parser))))
                    .unwrap_or_default(),
                posted,
                content: first_text(comment, parser, ".c6").unwrap_or_default(),
                score: descendants(comment, parser, ".c5")
                    .and_then(|mut nodes| nodes.next())
                    .and_then(|score| descendants(score, parser, "span"))
                    .and_then(|mut nodes| nodes.next())
                    .and_then(|tag| clean_text(&tag.inner_text(parser)).parse().ok()),
                vote_status,
            }
        })
        .collect()
}

fn parse_versions(dom: &tl::VDom<'_>, html: &str, base_url: &Url) -> Vec<EhGalleryVersion> {
    let parser = dom.parser();
    let dates: Vec<_> = Regex::new(r"(?i),\s*added\s+(.+?)<br\s*/?>")
        .expect("static EH version date regex is valid")
        .captures_iter(html)
        .map(|captures| clean_text(&captures[1]))
        .collect();
    dom.query_selector("#gnd")
        .into_iter()
        .flatten()
        .filter_map(|node| node.get(parser).and_then(tl::Node::as_tag))
        .flat_map(|container| descendants(container, parser, "a").into_iter().flatten())
        .enumerate()
        .filter_map(|(index, link)| {
            let href = attribute(link, "href", parser)?;
            let page_url = base_url.join(&href).ok()?;
            Some(EhGalleryVersion {
                gallery: parse_gallery_path(&page_url),
                page_url,
                title: clean_text(&link.inner_text(parser)),
                posted: dates.get(index).cloned().and_then(nonempty),
            })
        })
        .collect()
}

fn parse_thumbnails(
    html: &str,
    base_url: &Url,
    page: u32,
) -> Result<(Vec<EhThumbnail>, Option<u32>), CoreError> {
    let dom = tl::parse(html, tl::ParserOptions::default())
        .map_err(|_| unexpected("EH thumbnail page contains malformed HTML"))?;
    let parser = dom.parser();
    let mut items = Vec::new();
    if let Some(links) = dom.query_selector("a") {
        for link in links.filter_map(|node| node.get(parser).and_then(tl::Node::as_tag)) {
            let Some(page_url) = attribute(link, "href", parser)
                .and_then(|href| base_url.join(&href).ok())
                .filter(|url| {
                    matches!(url.scheme(), "http" | "https")
                        && url
                            .path_segments()
                            .is_some_and(|mut parts| parts.next() == Some("s"))
                })
            else {
                continue;
            };
            let direct = descendants(link, parser, "img").and_then(|mut nodes| nodes.next());
            let sprite = descendants(link, parser, "div").and_then(|mut nodes| nodes.next());
            let parsed = direct
                .and_then(|tag| parse_direct_thumbnail(tag, parser))
                .or_else(|| sprite.and_then(|tag| parse_sprite_thumbnail(tag, parser)));
            if let Some((image_url, width, height)) = parsed {
                let Some(page) = parse_gallery_page_index(&page_url) else {
                    continue;
                };
                items.push(EhThumbnail {
                    image_url,
                    page_url,
                    page,
                    width,
                    height,
                });
            }
        }
    }
    let max_page = dom
        .query_selector("a")
        .into_iter()
        .flatten()
        .filter_map(|node| node.get(parser).and_then(tl::Node::as_tag))
        .filter_map(|tag| attribute(tag, "href", parser))
        .filter_map(|href| {
            Regex::new(r"[?&]p=(\d+)")
                .expect("static EH thumbnail page regex is valid")
                .captures(&href)
                .and_then(|captures| captures[1].parse::<u32>().ok())
        })
        .max()
        .unwrap_or(0);
    let next_page = page.checked_add(1).filter(|next| *next <= max_page);
    Ok((items, next_page))
}

fn parse_gallery_page_index(url: &Url) -> Option<u32> {
    let tail = url.path_segments()?.next_back()?;
    tail.rsplit_once('-')
        .and_then(|(_, page)| page.parse::<u32>().ok())
        .and_then(|page| page.checked_sub(1))
}

fn parse_direct_thumbnail(
    tag: &tl::HTMLTag<'_>,
    parser: &tl::Parser<'_>,
) -> Option<(String, Option<u32>, Option<u32>)> {
    let source = attribute(tag, "src", parser).and_then(nonempty)?;
    let style = attribute(tag, "style", parser).unwrap_or_default();
    Some((
        source,
        dimension(tag, parser, "width", &style),
        dimension(tag, parser, "height", &style),
    ))
}

fn parse_sprite_thumbnail(
    tag: &tl::HTMLTag<'_>,
    parser: &tl::Parser<'_>,
) -> Option<(String, Option<u32>, Option<u32>)> {
    let style = attribute(tag, "style", parser)?;
    let mut source = Regex::new(r#"url\([\"']?([^)'\"]+)"#)
        .expect("static EH sprite URL regex is valid")
        .captures(&style)?[1]
        .to_owned();
    let width = dimension(tag, parser, "width", &style);
    let height = dimension(tag, parser, "height", &style);
    let position = Regex::new(r"url\([^)]+\)\s*-(\d+)px")
        .expect("static EH sprite position regex is valid")
        .captures(&style)
        .and_then(|captures| captures[1].parse::<u32>().ok());
    let mut ranges = Vec::new();
    if let (Some(position), Some(width)) = (position, width) {
        ranges.push(format!("x={position}-{}", position.saturating_add(width)));
    }
    if let Some(height) = height {
        ranges.push(format!("y=0-{height}"));
    }
    if !ranges.is_empty() {
        source.push('@');
        source.push_str(&ranges.join("&"));
    }
    Some((source, width, height))
}

fn document_text(dom: &tl::VDom<'_>, selector: &str) -> Option<String> {
    dom.query_selector(selector)
        .and_then(|mut nodes| nodes.next())
        .and_then(|node| node.get(dom.parser()).and_then(tl::Node::as_tag))
        .and_then(|tag| nonempty(clean_text(&tag.inner_text(dom.parser()))))
}

fn parse_page_count(value: &str) -> Option<u32> {
    Regex::new(r"(?i)\b(\d{1,4})\s*pages?\b")
        .expect("static EH page-count regex is valid")
        .captures(value)
        .and_then(|captures| captures[1].parse().ok())
        .filter(|value| (1..=EH_MAX_GALLERY_PAGES).contains(value))
}

fn parse_count(value: &str) -> Option<u64> {
    Regex::new(r"[\d,]+")
        .expect("static EH count regex is valid")
        .find(value)
        .and_then(|value| value.as_str().replace(',', "").parse().ok())
}

fn first_http_url(value: &str) -> Option<String> {
    Regex::new(r#"https?://[^\s\"')]+"#)
        .expect("static HTTP URL regex is valid")
        .find(value)
        .map(|value| value.as_str().to_owned())
}

fn parse_home(html: &str, base_url: &Url) -> Result<ParsedHome, CoreError> {
    if html.trim().is_empty() {
        return Err(unexpected("EH front page returned an empty response"));
    }
    let dom = tl::parse(html, tl::ParserOptions::default())
        .map_err(|_| unexpected("EH front page contains malformed HTML"))?;
    let parser = dom.parser();
    let mut galleries = Vec::new();
    for selector in ["tr", ".gl1t"] {
        let containers = dom
            .query_selector(selector)
            .ok_or_else(|| unexpected("failed to initialize EH gallery selector"))?;
        for handle in containers {
            let Some(container) = handle.get(parser).and_then(tl::Node::as_tag) else {
                continue;
            };
            if let Some(gallery) = parse_gallery_summary(container, parser, base_url) {
                galleries.push(gallery);
            }
        }
    }
    if galleries.is_empty() {
        return Err(unexpected(
            "EH front page contains no recognized gallery entries",
        ));
    }
    let previous =
        page_cursor(&dom, base_url, &["#uprev", "#dprev"], "prev")?.map(|gid| EhPageCursor {
            direction: EhPageDirection::Previous,
            gid,
        });
    let next =
        page_cursor(&dom, base_url, &["#unext", "#dnext"], "next")?.map(|gid| EhPageCursor {
            direction: EhPageDirection::Next,
            gid,
        });
    Ok((galleries, previous, next))
}

fn parse_gallery_summary(
    container: &tl::HTMLTag<'_>,
    parser: &tl::Parser<'_>,
    base_url: &Url,
) -> Option<EhGallerySummary> {
    let gallery_anchor = descendants(container, parser, "a")?.find_map(|tag| {
        let href = attribute(tag, "href", parser)?;
        let url = resolve_same_origin(base_url, &href)?;
        let gallery = parse_gallery_path(&url)?;
        Some((tag, url, gallery))
    })?;
    let title = first_text(container, parser, ".glink")
        .or_else(|| nonempty(clean_text(&gallery_anchor.0.inner_text(parser))))?;
    let category =
        first_text(container, parser, ".cn").or_else(|| first_text(container, parser, ".cs"));
    let text = clean_text(&container.inner_html(parser));
    let published = Regex::new(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?")
        .expect("static EH date regex is valid")
        .find(&text)
        .map(|value| value.as_str().to_owned());
    let page_count = Regex::new(r"(?i)\b(\d{1,4})\s*pages?\b")
        .expect("static EH page-count regex is valid")
        .captures(&text)
        .and_then(|captures| captures[1].parse::<u32>().ok())
        .filter(|value| (1..=EH_MAX_GALLERY_PAGES).contains(value));
    let rating = descendants(container, parser, ".ir").and_then(|nodes| {
        nodes
            .filter_map(|tag| attribute(tag, "style", parser))
            .find_map(|style| parse_rating(&style))
    });
    let mut language = None;
    let mut tags = Vec::new();
    if let Some(tag_nodes) = descendants(container, parser, ".gt, .gtl") {
        for tag in tag_nodes {
            let Some(value) = attribute(tag, "title", parser).and_then(nonempty) else {
                continue;
            };
            if let Some(value) = value.strip_prefix("language:") {
                if value != "translated" {
                    language = Some(value.to_owned());
                }
            } else {
                tags.push(value);
            }
        }
    }
    let uploader = [".gl4c", ".gl3e", ".gl5m"].iter().find_map(|selector| {
        descendants(container, parser, selector)?
            .find_map(|section| first_text(section, parser, "a"))
    });
    let (cover_url, cover_width, cover_height) = parse_cover(container, parser, base_url);
    Some(EhGallerySummary {
        gallery: gallery_anchor.2,
        page_url: gallery_anchor.1,
        title,
        category,
        published,
        uploader,
        page_count,
        rating,
        language,
        tags,
        cover_url,
        cover_width,
        cover_height,
    })
}

fn descendants<'a, 'b>(
    tag: &'b tl::HTMLTag<'a>,
    parser: &'b tl::Parser<'a>,
    selector: &'b str,
) -> Option<impl Iterator<Item = &'b tl::HTMLTag<'a>> + 'b> {
    tag.query_selector(parser, selector)
        .map(|nodes| nodes.filter_map(move |handle| handle.get(parser).and_then(tl::Node::as_tag)))
}

fn first_text(tag: &tl::HTMLTag<'_>, parser: &tl::Parser<'_>, selector: &str) -> Option<String> {
    descendants(tag, parser, selector)?
        .find_map(|value| nonempty(clean_text(&value.inner_text(parser))))
}

fn parse_cover(
    container: &tl::HTMLTag<'_>,
    parser: &tl::Parser<'_>,
    base_url: &Url,
) -> (Option<Url>, Option<u32>, Option<u32>) {
    let Some(image) = descendants(container, parser, "img").and_then(|mut nodes| {
        nodes.find(|tag| {
            ["data-src", "src"].iter().any(|name| {
                attribute(tag, name, parser)
                    .is_some_and(|value| !value.is_empty() && !value.starts_with("data:"))
            })
        })
    }) else {
        return (None, None, None);
    };
    let source = attribute(image, "data-src", parser)
        .filter(|value| !value.starts_with("data:"))
        .or_else(|| attribute(image, "src", parser).filter(|value| !value.starts_with("data:")));
    let cover_url = source
        .and_then(|source| base_url.join(&source).ok())
        .filter(|url| {
            matches!(url.scheme(), "http" | "https")
                && url.username().is_empty()
                && url.password().is_none()
        });
    let style = attribute(image, "style", parser).unwrap_or_default();
    let width = dimension(image, parser, "width", &style);
    let height = dimension(image, parser, "height", &style);
    (cover_url, width, height)
}

fn dimension(
    image: &tl::HTMLTag<'_>,
    parser: &tl::Parser<'_>,
    name: &str,
    style: &str,
) -> Option<u32> {
    attribute(image, name, parser)
        .and_then(|value| value.parse().ok())
        .or_else(|| {
            Regex::new(&format!(r"(?i)\b{name}:\s*(\d+)px"))
                .expect("EH dimension regex is valid")
                .captures(style)
                .and_then(|captures| captures[1].parse().ok())
        })
        .filter(|value| *value > 0)
}

fn parse_rating(style: &str) -> Option<f32> {
    let captures = Regex::new(r"background-position:\s*(-?\d+)px\s+(-?\d+)px")
        .expect("static EH rating regex is valid")
        .captures(style)?;
    let x = captures[1].parse::<i32>().ok()?;
    let y = captures[2].parse::<i32>().ok()?;
    match (x, y) {
        (0, -1) => Some(5.0),
        (0, -21) => Some(4.5),
        (-16, -1) => Some(4.0),
        (-16, -21) => Some(3.5),
        (-32, -1) => Some(3.0),
        (-32, -21) => Some(2.5),
        (-48, -1) => Some(2.0),
        (-48, -21) => Some(1.5),
        (-64, -1) => Some(1.0),
        (-64, -21) => Some(0.5),
        _ => None,
    }
}

fn page_cursor(
    dom: &tl::VDom<'_>,
    base_url: &Url,
    selectors: &[&str],
    parameter: &str,
) -> Result<Option<u64>, CoreError> {
    for selector in selectors {
        let Some(tag) = dom
            .query_selector(selector)
            .and_then(|mut nodes| nodes.next())
            .and_then(|handle| handle.get(dom.parser()))
            .and_then(tl::Node::as_tag)
        else {
            continue;
        };
        let Some(href) = attribute(tag, "href", dom.parser()) else {
            continue;
        };
        let Some(url) = resolve_same_origin(base_url, &href) else {
            return Err(unexpected("EH pagination URL escaped the profile origin"));
        };
        return url
            .query_pairs()
            .find(|(name, _)| name == parameter)
            .and_then(|(_, value)| value.parse::<u64>().ok())
            .filter(|value| *value > 0)
            .map(Some)
            .ok_or_else(|| unexpected("EH pagination URL contains an invalid cursor"));
    }
    Ok(None)
}

fn resolve_same_origin(base: &Url, value: &str) -> Option<Url> {
    let value = value.replace("&amp;", "&");
    let url = base.join(&value).ok()?;
    (url.scheme() == base.scheme()
        && url.host_str() == base.host_str()
        && url.port_or_known_default() == base.port_or_known_default()
        && url.username().is_empty()
        && url.password().is_none())
    .then_some(url)
}

fn parse_gallery_path(url: &Url) -> Option<EhGalleryRef> {
    let mut segments = url.path_segments()?.filter(|segment| !segment.is_empty());
    if segments.next()? != "g" {
        return None;
    }
    let gid = segments
        .next()?
        .parse::<u64>()
        .ok()
        .filter(|value| *value > 0)?;
    let token = segments.next()?;
    if segments.next().is_some() || !valid_token(token) {
        return None;
    }
    Some(EhGalleryRef {
        gid,
        token: token.to_ascii_lowercase(),
    })
}

fn ensure_eh(key: &ProfileKey) -> Result<(), CoreError> {
    if key.provider == "eh" {
        Ok(())
    } else {
        Err(CoreError::new(
            ErrorCode::InvalidInput,
            format!("profile {key} is not an EH profile"),
            false,
        ))
    }
}

fn ensure_html(content_type: &Option<String>, endpoint: &str) -> Result<(), CoreError> {
    if content_type
        .as_deref()
        .is_some_and(|value| !value.to_ascii_lowercase().contains("html"))
    {
        Err(unexpected(format!(
            "{endpoint} returned a non-HTML response"
        )))
    } else {
        Ok(())
    }
}

fn ensure_json(content_type: &Option<String>, endpoint: &str) -> Result<(), CoreError> {
    if content_type
        .as_deref()
        .is_some_and(|value| !value.to_ascii_lowercase().contains("json"))
    {
        Err(unexpected(format!(
            "{endpoint} returned a non-JSON response"
        )))
    } else {
        Ok(())
    }
}

fn parse_archive_options(html: &str) -> Result<Vec<EhArchiveOption>, CoreError> {
    let parser = tl::parse(html, tl::ParserOptions::default())
        .map_err(|_| unexpected("EH Archive page contains malformed HTML"))?;
    let document = parser.nodes();
    let parser_ref = parser.parser();
    let db = document
        .iter()
        .filter_map(tl::Node::as_tag)
        .find(|tag| {
            tag.name().as_utf8_str().eq_ignore_ascii_case("div")
                && attribute(tag, "id", parser_ref).as_deref() == Some("db")
        })
        .ok_or_else(|| unexpected("EH Archive page is missing the option container"))?;
    let inner = db.inner_text(parser_ref).to_string();
    let mut options = Vec::new();
    parse_hath_options(html, &mut options)?;
    parse_direct_options(&inner, &mut options)?;
    if options.is_empty() {
        return Err(unexpected("EH Archive page contains no recognized options"));
    }
    Ok(options)
}

fn parse_hath_options(source: &str, options: &mut Vec<EhArchiveOption>) -> Result<(), CoreError> {
    let call_pattern = Regex::new(r#"do_hathdl\('([^']+)'\)"#)
        .map_err(|_| unexpected("failed to initialize EH H@H parser"))?;
    let paragraph_pattern = Regex::new(r"(?is)<p[^>]*>(.*?)</p>")
        .map_err(|_| unexpected("failed to initialize EH H@H detail parser"))?;
    for captures in call_pattern.captures_iter(source) {
        let resolution = clean_text(&captures[1]);
        if resolution.is_empty() {
            continue;
        }
        let Some(call_match) = captures.get(0) else {
            continue;
        };
        let cell_start = source[..call_match.start()]
            .rfind("<td")
            .unwrap_or(call_match.start());
        let cell_end = source[call_match.end()..]
            .find("</td>")
            .map_or(source.len(), |offset| call_match.end() + offset);
        let cell = &source[cell_start..cell_end];
        let title = source[call_match.end()..]
            .find('>')
            .map(|offset| call_match.end() + offset + 1)
            .and_then(|start| {
                source[start..cell_end]
                    .find("</a>")
                    .map(|offset| clean_text(&source[start..start + offset]))
            })
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| resolution.clone());
        let paragraphs: Vec<_> = paragraph_pattern
            .captures_iter(cell)
            .map(|value| clean_text(&value[1]))
            .collect();
        options.push(EhArchiveOption {
            id: format!("h@h_{resolution}"),
            title: format!("H@H {title}"),
            estimated_size: paragraphs.get(1).cloned().and_then(nonempty),
            cost: paragraphs.get(2).cloned().and_then(nonempty),
            delivery: EhArchiveDelivery::Hath,
            locally_downloadable: false,
        });
    }
    Ok(())
}

fn parse_direct_options(text: &str, options: &mut Vec<EhArchiveOption>) -> Result<(), CoreError> {
    let normalized = text.split_whitespace().collect::<Vec<_>>().join(" ");
    let option_pattern = Regex::new(r"(?i)(Original|Resample)\s+Archive")
        .map_err(|_| unexpected("failed to initialize EH Archive parser"))?;
    let detail_pattern = Regex::new(r"(?i)Download\s*Cost:\s*(.*?)\s*Estimated\s*Size:\s*(.*)")
        .map_err(|_| unexpected("failed to initialize EH Archive detail parser"))?;
    let matches: Vec<_> = option_pattern.find_iter(&normalized).collect();
    for (index, option_match) in matches.iter().enumerate() {
        let segment_end = matches
            .get(index + 1)
            .map_or(normalized.len(), regex::Match::start);
        let segment = &normalized[option_match.end()..segment_end];
        let Some(details) = detail_pattern.captures(segment) else {
            continue;
        };
        let original = option_match
            .as_str()
            .to_ascii_lowercase()
            .starts_with("original");
        options.push(EhArchiveOption {
            id: if original { "0" } else { "1" }.to_owned(),
            title: if original { "Original" } else { "Resample" }.to_owned(),
            estimated_size: nonempty(clean_text(&details[2])),
            cost: nonempty(clean_text(&details[1])),
            delivery: EhArchiveDelivery::Archive,
            locally_downloadable: true,
        });
    }
    Ok(())
}

fn attribute(tag: &tl::HTMLTag<'_>, name: &str, _parser: &tl::Parser<'_>) -> Option<String> {
    tag.attributes()
        .get(name)
        .flatten()
        .map(|value| value.as_utf8_str().into_owned())
}

fn clean_text(value: &str) -> String {
    let without_tags = Regex::new(r"(?is)<[^>]+>")
        .expect("static regex is valid")
        .replace_all(value, " ");
    without_tags
        .replace("&amp;", "&")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn nonempty(value: String) -> Option<String> {
    (!value.is_empty()).then_some(value)
}

fn valid_token(token: &str) -> bool {
    (8..=64).contains(&token.len()) && token.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn validate_gallery(gallery: &EhGalleryRef) -> Result<(), CoreError> {
    if gallery.gid == 0 || !valid_token(&gallery.token) {
        Err(invalid_gallery())
    } else {
        Ok(())
    }
}

fn invalid_gallery() -> CoreError {
    CoreError::new(
        ErrorCode::InvalidInput,
        "EH gallery must contain a positive GID and hexadecimal token",
        false,
    )
}

fn unexpected(message: impl Into<String>) -> CoreError {
    CoreError::new(ErrorCode::UnexpectedResponse, message, false)
}

#[cfg(test)]
mod tests {
    use super::{
        EhArchiveDelivery, EhGalleryRef, EhPageCursor, EhPageDirection, EhService,
        parse_archive_options, parse_gallery_detail, parse_home, parse_image_api_response,
        parse_image_key, parse_thumbnails,
    };
    use crate::{NetworkConfig, ProfileKey, ProviderProfileConfig, session::SessionRegistry};
    use axum::{Router, extract::RawQuery, http::header, routing::get};
    use std::{collections::BTreeMap, sync::Arc};
    use tokio::net::TcpListener;
    use tokio_util::sync::CancellationToken;
    use url::Url;

    const ARCHIVE_OPTIONS: &str = include_str!("../../tests/fixtures/eh/archive_options.html");
    const HOME_COMPACT: &str = include_str!("../../tests/fixtures/eh/home_compact.html");
    const GALLERY_DETAIL: &str = include_str!("../../tests/fixtures/eh/gallery_detail.html");
    const THUMBNAILS: &str = include_str!("../../tests/fixtures/eh/thumbnails.html");
    const IMAGE_SHOWKEY: &str = include_str!("../../tests/fixtures/eh/image_showkey.html");
    const IMAGE_MPV: &str = include_str!("../../tests/fixtures/eh/image_mpv.html");
    const API_SHOWPAGE: &str = include_str!("../../tests/fixtures/eh/api_showpage.json");
    const API_IMAGEDISPATCH: &str = include_str!("../../tests/fixtures/eh/api_imagedispatch.json");

    #[test]
    fn parses_gallery_urls_strictly() {
        let gallery = EhGalleryRef::parse("https://e-hentai.org/g/123456/abcdef1234/").unwrap();
        assert_eq!(gallery.gid, 123456);
        assert_eq!(gallery.token, "abcdef1234");
        assert!(EhGalleryRef::parse("https://example.com/g/123456/abcdef1234/").is_err());
        assert!(EhGalleryRef::parse("https://e-hentai.org/g/0/not-token/").is_err());
    }

    #[test]
    fn parses_archive_fixture() {
        let options = parse_archive_options(ARCHIVE_OPTIONS).unwrap();
        assert_eq!(options.len(), 3);
        assert_eq!(options[0].id, "h@h_org");
        assert_eq!(options[0].delivery, EhArchiveDelivery::Hath);
        assert!(!options[0].locally_downloadable);
        assert_eq!(options[1].id, "0");
        assert_eq!(options[1].cost.as_deref(), Some("250 GP"));
        assert_eq!(options[2].id, "1");
        assert_eq!(options[2].estimated_size.as_deref(), Some("45.67 MiB"));
    }

    #[test]
    fn parses_compact_home_fixture() {
        let base = Url::parse("https://e-hentai.org/").unwrap();
        let (galleries, previous, next) = parse_home(HOME_COMPACT, &base).unwrap();
        assert_eq!(galleries.len(), 2);
        assert_eq!(galleries[0].gallery.gid, 1234567);
        assert_eq!(galleries[0].title, "Fixture & Gallery One");
        assert_eq!(galleries[0].category.as_deref(), Some("Doujinshi"));
        assert_eq!(galleries[0].published.as_deref(), Some("2026-07-20 09:15"));
        assert_eq!(galleries[0].uploader.as_deref(), Some("fixture_uploader"));
        assert_eq!(galleries[0].page_count, Some(42));
        assert_eq!(galleries[0].rating, Some(4.5));
        assert_eq!(galleries[0].language.as_deref(), Some("english"));
        assert_eq!(galleries[0].tags, ["artist:alice", "female:glasses"]);
        assert_eq!(galleries[0].cover_width, Some(250));
        assert_eq!(galleries[0].cover_height, Some(350));
        assert_eq!(
            previous,
            Some(EhPageCursor {
                direction: EhPageDirection::Previous,
                gid: 1234566,
            })
        );
        assert_eq!(
            next,
            Some(EhPageCursor {
                direction: EhPageDirection::Next,
                gid: 1234565,
            })
        );
    }

    #[test]
    fn parses_gallery_detail_fixture() {
        let base = Url::parse("https://e-hentai.org/g/123456/abcdef1234/").unwrap();
        let detail = parse_gallery_detail(
            GALLERY_DETAIL,
            &base,
            "default".to_owned(),
            7,
            EhGalleryRef {
                gid: 123456,
                token: "abcdef1234".to_owned(),
            },
        )
        .unwrap();
        assert_eq!(detail.title, "Fixture Gallery Title");
        assert_eq!(detail.subtitle.as_deref(), Some("Fixture Japanese Title"));
        assert_eq!(detail.page_count, 42);
        assert_eq!(detail.rating, Some(4.75));
        assert_eq!(detail.rating_count, 1234);
        assert_eq!(detail.favorite_category, Some(2));
        assert_eq!(detail.favorite_count, 1234);
        assert_eq!(detail.page_token.as_deref(), Some("page-token"));
        assert_eq!(detail.tags["artist"], ["artist:fixture artist"]);
        assert_eq!(detail.comments[0].id, "77");
        assert_eq!(detail.comments[0].vote_status, 1);
        assert_eq!(
            detail.newer_versions[0].gallery.as_ref().unwrap().gid,
            222222
        );
    }

    #[test]
    fn parses_thumbnail_fixture() {
        let base = Url::parse("https://e-hentai.org/g/123456/abcdef1234/").unwrap();
        let (items, next) = parse_thumbnails(THUMBNAILS, &base, 0).unwrap();
        assert_eq!(items.len(), 2);
        assert_eq!(
            items[0].image_url,
            "https://ehgt.org/sprite.webp@x=200-300&y=0-140"
        );
        assert_eq!(items[0].width, Some(100));
        assert_eq!(items[1].image_url, "https://ehgt.org/direct.webp");
        assert_eq!(items[1].height, Some(160));
        assert_eq!(next, Some(1));
    }

    #[test]
    fn parses_eh_image_keys_and_api_responses() {
        assert!(matches!(
            parse_image_key(IMAGE_SHOWKEY).unwrap(),
            super::EhImageKey::Show(key) if key == "fixture-showkey"
        ));
        match parse_image_key(IMAGE_MPV).unwrap() {
            super::EhImageKey::Mpv { key, image_keys } => {
                assert_eq!(key, "fixture-mpvkey");
                assert_eq!(image_keys, ["key-one", "key-two"]);
            }
            super::EhImageKey::Show(_) => panic!("expected MPV key"),
        }
        let api = Url::parse("https://e-hentai.org/api.php").unwrap();
        let showpage = parse_image_api_response("showpage", API_SHOWPAGE.as_bytes(), &api).unwrap();
        assert_eq!(
            showpage.url.as_str(),
            "https://images.example/fixture-original.jpg"
        );
        assert_eq!(showpage.next_nl.as_deref(), Some("fixture-nl"));
        let mpv =
            parse_image_api_response("imagedispatch", API_IMAGEDISPATCH.as_bytes(), &api).unwrap();
        assert_eq!(
            mpv.url.as_str(),
            "https://images.example/fixture-mpv-original.jpg"
        );
        assert_eq!(mpv.next_nl.as_deref(), Some("fixture-mpv-nl"));
    }

    #[tokio::test]
    async fn archive_options_use_the_configured_shared_profile() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let listen = listener.local_addr().unwrap();
        let router = Router::new().route(
            "/archiver.php",
            get(|RawQuery(query): RawQuery| async move {
                assert_eq!(query.as_deref(), Some("gid=123456&token=abcdef1234"));
                (
                    [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
                    ARCHIVE_OPTIONS,
                )
            }),
        );
        tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
        let profile = ProviderProfileConfig {
            provider: "eh".to_owned(),
            profile: "default".to_owned(),
            base_url: Url::parse(&format!("http://{listen}/")).unwrap(),
            ..ProviderProfileConfig::default()
        };
        let profiles = BTreeMap::from([("eh".to_owned(), profile)]);
        let sessions =
            Arc::new(SessionRegistry::new(&profiles, &NetworkConfig::default()).unwrap());
        let result = EhService::new(sessions)
            .archive_options(
                &ProfileKey::new("eh", "default"),
                EhGalleryRef {
                    gid: 123456,
                    token: "abcdef1234".to_owned(),
                },
                CancellationToken::new(),
            )
            .await
            .unwrap();
        assert_eq!(result.generation, 1);
        assert_eq!(result.options.len(), 3);
    }

    #[tokio::test]
    async fn home_uses_the_configured_shared_profile_and_cursor() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let listen = listener.local_addr().unwrap();
        let fixture = HOME_COMPACT.replace("https://e-hentai.org/", &format!("http://{listen}/"));
        let router = Router::new().route(
            "/",
            get(move |RawQuery(query): RawQuery| {
                let fixture = fixture.clone();
                async move {
                    assert_eq!(query.as_deref(), Some("next=1234565"));
                    (
                        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
                        fixture,
                    )
                }
            }),
        );
        tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
        let profile = ProviderProfileConfig {
            provider: "eh".to_owned(),
            profile: "default".to_owned(),
            base_url: Url::parse(&format!("http://{listen}/")).unwrap(),
            ..ProviderProfileConfig::default()
        };
        let sessions = Arc::new(
            SessionRegistry::new(
                &BTreeMap::from([("eh".to_owned(), profile)]),
                &NetworkConfig::default(),
            )
            .unwrap(),
        );
        let result = EhService::new(sessions)
            .home(
                &ProfileKey::new("eh", "default"),
                Some(EhPageCursor {
                    direction: EhPageDirection::Next,
                    gid: 1234565,
                }),
                CancellationToken::new(),
            )
            .await
            .unwrap();
        assert_eq!(result.generation, 1);
        assert_eq!(result.galleries.len(), 2);
    }
}
