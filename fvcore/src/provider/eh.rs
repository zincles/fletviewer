//! EH front-page browsing, gallery identity, and official Archive option discovery.

use crate::{CoreError, ErrorCode, ProfileKey, session::SessionRegistry};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
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
        parse_archive_options, parse_home,
    };
    use crate::{NetworkConfig, ProfileKey, ProviderProfileConfig, session::SessionRegistry};
    use axum::{Router, extract::RawQuery, http::header, routing::get};
    use std::{collections::BTreeMap, sync::Arc};
    use tokio::net::TcpListener;
    use tokio_util::sync::CancellationToken;
    use url::Url;

    const ARCHIVE_OPTIONS: &str = include_str!("../../tests/fixtures/eh/archive_options.html");
    const HOME_COMPACT: &str = include_str!("../../tests/fixtures/eh/home_compact.html");

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
