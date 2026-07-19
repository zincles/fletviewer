//! EH gallery identity and official Archive option discovery.

use crate::{CoreError, ErrorCode, ProfileKey, session::SessionRegistry};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use url::Url;

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

    pub(crate) async fn archive_options(
        &self,
        key: &ProfileKey,
        gallery: EhGalleryRef,
        cancellation: CancellationToken,
    ) -> Result<EhArchiveOptions, CoreError> {
        if key.provider != "eh" {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                format!("profile {key} is not an EH profile"),
                false,
            ));
        }
        validate_gallery(&gallery)?;
        let path = format!("archiver.php?gid={}&token={}", gallery.gid, gallery.token);
        let response = self.sessions.get(key, &path, cancellation).await?;
        if response
            .content_type
            .as_deref()
            .is_some_and(|value| !value.to_ascii_lowercase().contains("html"))
        {
            return Err(unexpected(
                "EH Archive endpoint returned a non-HTML response",
            ));
        }
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
    use super::{EhArchiveDelivery, EhGalleryRef, EhService, parse_archive_options};
    use crate::{NetworkConfig, ProfileKey, ProviderProfileConfig, session::SessionRegistry};
    use axum::{Router, extract::RawQuery, http::header, routing::get};
    use std::{collections::BTreeMap, sync::Arc};
    use tokio::net::TcpListener;
    use tokio_util::sync::CancellationToken;
    use url::Url;

    const ARCHIVE_OPTIONS: &str = include_str!("../../tests/fixtures/eh/archive_options.html");

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
}
