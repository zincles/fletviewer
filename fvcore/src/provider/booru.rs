//! Booru public API models and protocol implementations.

use crate::{
    CoreError, ErrorCode, ProfileKey,
    session::{ApiAuth, NetworkResponse, SessionRegistry},
};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, sync::Arc};
use tokio_util::sync::CancellationToken;
use url::Url;

/// One image representation exposed by a Booru post.
#[derive(Clone, Debug, Default, Serialize)]
pub struct ImageVariant {
    /// Absolute image URL, when supplied by the Provider.
    pub url: Option<Url>,
    /// Pixel width, when known.
    pub width: Option<u32>,
    /// Pixel height, when known.
    pub height: Option<u32>,
    /// File size in bytes, when known.
    pub byte_length: Option<u64>,
}

/// Provider-neutral subset of one Booru post without discarding download metadata.
#[derive(Clone, Debug, Serialize)]
pub struct BooruPost {
    /// Provider implementation identifier.
    pub provider: String,
    /// Provider post identifier.
    pub id: u64,
    /// Human-facing post URL.
    pub page_url: Url,
    /// Original image representation.
    pub original: ImageVariant,
    /// Resized sample representation.
    pub sample: ImageVariant,
    /// Small preview representation.
    pub preview: ImageVariant,
    /// General tags.
    pub general_tags: Vec<String>,
    /// Artist tags.
    pub artist_tags: Vec<String>,
    /// Character tags.
    pub character_tags: Vec<String>,
    /// Copyright tags.
    pub copyright_tags: Vec<String>,
    /// Provider metadata tags.
    pub meta_tags: Vec<String>,
    /// Complete Provider-specific tag categories, including categories outside the common five.
    pub provider_tags: BTreeMap<String, Vec<String>>,
    /// Provider rating value.
    pub rating: String,
    /// Provider score.
    pub score: i64,
    /// Source URL or attribution text.
    pub source: Option<String>,
    /// Provider-declared original content MD5 as 32 lowercase hexadecimal characters.
    pub original_md5: Option<String>,
    /// Provider-declared original file extension.
    pub file_extension: Option<String>,
    /// Provider creation timestamp without reinterpretation.
    pub created_at: Option<String>,
}

/// One page returned by a Booru search.
#[derive(Clone, Debug, Serialize)]
pub struct BooruSearchResult {
    /// Provider implementation identifier.
    pub provider: String,
    /// Profile that executed the request.
    pub profile: String,
    /// Immutable session generation used for the response body lifetime.
    pub generation: u64,
    /// Original tag query.
    pub query: String,
    /// Requested page number.
    pub page: u64,
    /// Next page when the current page reached the requested limit.
    pub next_page: Option<u64>,
    /// Provider-reported total post count, when available.
    pub total_count: Option<u64>,
    /// Parsed posts.
    pub posts: Vec<BooruPost>,
}

/// One Provider tag completion candidate.
#[derive(Clone, Debug, Serialize)]
pub struct BooruTagSuggestion {
    /// Provider-native tag text.
    pub tag: String,
    /// Normalized Provider category name.
    pub category: String,
    /// Provider-reported post count.
    pub count: u64,
}

/// One immutable collection of Booru tag completion candidates.
#[derive(Clone, Debug, Serialize)]
pub struct BooruTagSuggestions {
    /// Provider implementation identifier.
    pub provider: String,
    /// Profile that executed the request.
    pub profile: String,
    /// Immutable session generation used for the response body lifetime.
    pub generation: u64,
    /// Original trimmed completion query.
    pub query: String,
    /// Parsed suggestions in Provider order.
    pub suggestions: Vec<BooruTagSuggestion>,
}

#[derive(Deserialize)]
struct DanbooruPost {
    id: u64,
    #[serde(default)]
    created_at: Option<String>,
    #[serde(default)]
    score: i64,
    #[serde(default)]
    source: String,
    #[serde(default)]
    md5: Option<String>,
    #[serde(default)]
    rating: String,
    #[serde(default)]
    image_width: Option<u32>,
    #[serde(default)]
    image_height: Option<u32>,
    #[serde(default)]
    file_size: Option<u64>,
    #[serde(default)]
    file_ext: Option<String>,
    #[serde(default)]
    file_url: Option<Url>,
    #[serde(default)]
    large_file_url: Option<Url>,
    #[serde(default)]
    preview_file_url: Option<Url>,
    #[serde(default)]
    tag_string_general: String,
    #[serde(default)]
    tag_string_artist: String,
    #[serde(default)]
    tag_string_character: String,
    #[serde(default)]
    tag_string_copyright: String,
    #[serde(default)]
    tag_string_meta: String,
}

pub(crate) struct BooruService {
    sessions: Arc<SessionRegistry>,
}

impl BooruService {
    pub(crate) fn new(sessions: Arc<SessionRegistry>) -> Self {
        Self { sessions }
    }

    pub(crate) async fn search_danbooru(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u64,
        limit: u32,
        cancellation: CancellationToken,
    ) -> Result<BooruSearchResult, CoreError> {
        ensure_provider(key, "danbooru")?;
        let page = page.max(1);
        let limit = limit.clamp(1, 200);
        let parameters = vec![
            ("tags".to_owned(), query.trim().to_owned()),
            ("page".to_owned(), page.to_string()),
            ("limit".to_owned(), limit.to_string()),
        ];
        let response = self
            .sessions
            .get_with_query(key, "posts.json", &parameters, ApiAuth::Basic, cancellation)
            .await?;
        let generation = response.generation;
        let base_url = response.final_url.clone();
        let posts: Vec<DanbooruPost> = parse_json(response)?;
        let reached_limit = posts.len() == limit as usize;
        let posts = posts
            .into_iter()
            .map(|post| map_danbooru_post(key, &base_url, post))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(BooruSearchResult {
            provider: key.provider.clone(),
            profile: key.profile.clone(),
            generation,
            query: query.trim().to_owned(),
            page,
            next_page: reached_limit.then_some(page + 1),
            total_count: None,
            posts,
        })
    }

    pub(crate) async fn get_danbooru_post(
        &self,
        key: &ProfileKey,
        post_id: u64,
        cancellation: CancellationToken,
    ) -> Result<BooruPost, CoreError> {
        ensure_provider(key, "danbooru")?;
        if post_id == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Danbooru post ID must be greater than zero",
                false,
            ));
        }
        let response = self
            .sessions
            .get_with_query(
                key,
                &format!("posts/{post_id}.json"),
                &[],
                ApiAuth::Basic,
                cancellation,
            )
            .await?;
        let base_url = response.final_url.clone();
        map_danbooru_post(key, &base_url, parse_json(response)?)
    }

    pub(crate) async fn search_gelbooru(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u64,
        limit: u32,
        cancellation: CancellationToken,
    ) -> Result<BooruSearchResult, CoreError> {
        ensure_provider(key, "gelbooru")?;
        let limit = limit.clamp(1, 100);
        let parameters = vec![
            ("page".to_owned(), "dapi".to_owned()),
            ("s".to_owned(), "post".to_owned()),
            ("q".to_owned(), "index".to_owned()),
            ("json".to_owned(), "1".to_owned()),
            ("tags".to_owned(), query.trim().to_owned()),
            ("pid".to_owned(), page.to_string()),
            ("limit".to_owned(), limit.to_string()),
        ];
        let response = self
            .sessions
            .get_with_query(
                key,
                "index.php",
                &parameters,
                ApiAuth::GelbooruQuery,
                cancellation,
            )
            .await?;
        let generation = response.generation;
        let base_url = response.final_url.clone();
        let (raw_posts, total_count) = parse_gelbooru_posts(response)?;
        let reached_limit = raw_posts.len() == limit as usize;
        let posts = raw_posts
            .into_iter()
            .map(|post| map_gelbooru_post(key, &base_url, &post))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(BooruSearchResult {
            provider: key.provider.clone(),
            profile: key.profile.clone(),
            generation,
            query: query.trim().to_owned(),
            page,
            next_page: reached_limit.then_some(page + 1),
            total_count,
            posts,
        })
    }

    pub(crate) async fn get_gelbooru_post(
        &self,
        key: &ProfileKey,
        post_id: u64,
        cancellation: CancellationToken,
    ) -> Result<BooruPost, CoreError> {
        ensure_provider(key, "gelbooru")?;
        if post_id == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Gelbooru post ID must be greater than zero",
                false,
            ));
        }
        let parameters = vec![
            ("page".to_owned(), "dapi".to_owned()),
            ("s".to_owned(), "post".to_owned()),
            ("q".to_owned(), "index".to_owned()),
            ("json".to_owned(), "1".to_owned()),
            ("id".to_owned(), post_id.to_string()),
        ];
        let response = self
            .sessions
            .get_with_query(
                key,
                "index.php",
                &parameters,
                ApiAuth::GelbooruQuery,
                cancellation,
            )
            .await?;
        let base_url = response.final_url.clone();
        let (mut posts, _) = parse_gelbooru_posts(response)?;
        let post = posts.pop().ok_or_else(|| {
            CoreError::new(
                ErrorCode::ResourceNotFound,
                format!("Gelbooru post {post_id} was not found"),
                false,
            )
        })?;
        map_gelbooru_post(key, &base_url, &post)
    }

    pub(crate) async fn search_gelbooru_xml(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u64,
        limit: u32,
        cancellation: CancellationToken,
    ) -> Result<BooruSearchResult, CoreError> {
        ensure_gelbooru_xml_provider(key)?;
        let limit = limit.clamp(1, 100);
        let parameters = vec![
            ("page".to_owned(), "dapi".to_owned()),
            ("s".to_owned(), "post".to_owned()),
            ("q".to_owned(), "index".to_owned()),
            ("tags".to_owned(), query.trim().to_owned()),
            ("pid".to_owned(), page.to_string()),
            ("limit".to_owned(), limit.to_string()),
        ];
        let response = self
            .sessions
            .get_with_query(key, "index.php", &parameters, ApiAuth::None, cancellation)
            .await?;
        let generation = response.generation;
        let base_url = response.final_url.clone();
        let (raw_posts, total_count) = parse_gelbooru_xml_posts(response, &key.provider)?;
        let reached_limit = raw_posts.len() == limit as usize;
        let posts = raw_posts
            .iter()
            .map(|post| map_gelbooru_post(key, &base_url, post))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(BooruSearchResult {
            provider: key.provider.clone(),
            profile: key.profile.clone(),
            generation,
            query: query.trim().to_owned(),
            page,
            next_page: reached_limit.then_some(page + 1),
            total_count,
            posts,
        })
    }

    pub(crate) async fn get_gelbooru_xml_post(
        &self,
        key: &ProfileKey,
        post_id: u64,
        cancellation: CancellationToken,
    ) -> Result<BooruPost, CoreError> {
        ensure_gelbooru_xml_provider(key)?;
        if post_id == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Gelbooru-style XML post ID must be greater than zero",
                false,
            ));
        }
        let parameters = vec![
            ("page".to_owned(), "dapi".to_owned()),
            ("s".to_owned(), "post".to_owned()),
            ("q".to_owned(), "index".to_owned()),
            ("id".to_owned(), post_id.to_string()),
        ];
        let response = self
            .sessions
            .get_with_query(key, "index.php", &parameters, ApiAuth::None, cancellation)
            .await?;
        let base_url = response.final_url.clone();
        let (mut posts, _) = parse_gelbooru_xml_posts(response, &key.provider)?;
        let post = posts.pop().ok_or_else(|| {
            CoreError::new(
                ErrorCode::ResourceNotFound,
                format!("{} post {post_id} was not found", key.provider),
                false,
            )
        })?;
        map_gelbooru_post(key, &base_url, &post)
    }

    pub(crate) async fn search_moebooru(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u64,
        limit: u32,
        cancellation: CancellationToken,
    ) -> Result<BooruSearchResult, CoreError> {
        ensure_moebooru_provider(key)?;
        let page = page.max(1);
        let limit = limit.clamp(1, 100);
        let parameters = vec![
            ("tags".to_owned(), query.trim().to_owned()),
            ("page".to_owned(), page.to_string()),
            ("limit".to_owned(), limit.to_string()),
        ];
        let response = self
            .sessions
            .get_with_query(key, "post.json", &parameters, ApiAuth::None, cancellation)
            .await?;
        let generation = response.generation;
        let base_url = response.final_url.clone();
        let raw_posts: Vec<serde_json::Value> = parse_json(response)?;
        let reached_limit = raw_posts.len() == limit as usize;
        let posts = raw_posts
            .iter()
            .map(|post| map_moebooru_post(key, &base_url, post))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(BooruSearchResult {
            provider: key.provider.clone(),
            profile: key.profile.clone(),
            generation,
            query: query.trim().to_owned(),
            page,
            next_page: reached_limit.then_some(page + 1),
            total_count: None,
            posts,
        })
    }

    pub(crate) async fn get_moebooru_post(
        &self,
        key: &ProfileKey,
        post_id: u64,
        cancellation: CancellationToken,
    ) -> Result<BooruPost, CoreError> {
        ensure_moebooru_provider(key)?;
        if post_id == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Moebooru post ID must be greater than zero",
                false,
            ));
        }
        let parameters = vec![
            ("tags".to_owned(), format!("id:{post_id}")),
            ("limit".to_owned(), "1".to_owned()),
        ];
        let response = self
            .sessions
            .get_with_query(key, "post.json", &parameters, ApiAuth::None, cancellation)
            .await?;
        let base_url = response.final_url.clone();
        let mut posts: Vec<serde_json::Value> = parse_json(response)?;
        let post = posts.pop().ok_or_else(|| {
            CoreError::new(
                ErrorCode::ResourceNotFound,
                format!("{} post {post_id} was not found", key.provider),
                false,
            )
        })?;
        map_moebooru_post(key, &base_url, &post)
    }

    pub(crate) async fn tag_suggestions(
        &self,
        key: &ProfileKey,
        query: &str,
        limit: u32,
        cancellation: CancellationToken,
    ) -> Result<BooruTagSuggestions, CoreError> {
        let query = query.trim();
        if query.is_empty() {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Booru tag suggestion query cannot be empty",
                false,
            ));
        }
        let limit = limit.clamp(1, booru_tag_limit(key)?);
        let response = match key.provider.as_str() {
            "danbooru" => {
                let parameters = vec![
                    ("search[name_matches]".to_owned(), format!("{query}*")),
                    ("search[order]".to_owned(), "count".to_owned()),
                    ("limit".to_owned(), limit.to_string()),
                ];
                self.sessions
                    .get_with_query(key, "tags.json", &parameters, ApiAuth::Basic, cancellation)
                    .await?
            }
            "gelbooru" => {
                let parameters = gelbooru_tag_parameters(query, limit, true);
                self.sessions
                    .get_with_query(
                        key,
                        "index.php",
                        &parameters,
                        ApiAuth::GelbooruQuery,
                        cancellation,
                    )
                    .await?
            }
            "safebooru" | "rule34" | "tbib" | "xbooru" | "hypnohub" => {
                let parameters = gelbooru_tag_parameters(query, limit, false);
                self.sessions
                    .get_with_query(key, "index.php", &parameters, ApiAuth::None, cancellation)
                    .await?
            }
            "yandere" | "konachan" | "konachan_net" | "lolibooru" | "behoimi" => {
                let parameters = vec![
                    ("name".to_owned(), format!("{query}*")),
                    ("order".to_owned(), "count".to_owned()),
                    ("limit".to_owned(), limit.to_string()),
                ];
                self.sessions
                    .get_with_query(key, "tag.json", &parameters, ApiAuth::None, cancellation)
                    .await?
            }
            _ => return Err(unsupported_booru_provider(key)),
        };
        let generation = response.generation;
        let suggestions = match key.provider.as_str() {
            "danbooru" => parse_tag_json(response, "category", "post_count")?,
            "gelbooru" => parse_gelbooru_tag_json(response)?,
            "safebooru" | "rule34" | "tbib" | "xbooru" | "hypnohub" => {
                parse_tag_xml(response, &key.provider)?
            }
            _ => parse_tag_json(response, "type", "count")?,
        };
        Ok(BooruTagSuggestions {
            provider: key.provider.clone(),
            profile: key.profile.clone(),
            generation,
            query: query.to_owned(),
            suggestions,
        })
    }

    pub(crate) async fn search_e621(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u64,
        limit: u32,
        cancellation: CancellationToken,
    ) -> Result<BooruSearchResult, CoreError> {
        ensure_e621_provider(key)?;
        let page = page.max(1);
        let limit = limit.clamp(1, 320);
        let parameters = vec![
            ("tags".to_owned(), query.trim().to_owned()),
            ("page".to_owned(), page.to_string()),
            ("limit".to_owned(), limit.to_string()),
        ];
        let response = self
            .sessions
            .get_with_query(key, "posts.json", &parameters, ApiAuth::None, cancellation)
            .await?;
        let generation = response.generation;
        let base_url = response.final_url.clone();
        let raw_posts = parse_e621_posts(response)?;
        let reached_limit = raw_posts.len() == limit as usize;
        let posts = raw_posts
            .iter()
            .map(|post| map_e621_post(key, &base_url, post))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(BooruSearchResult {
            provider: key.provider.clone(),
            profile: key.profile.clone(),
            generation,
            query: query.trim().to_owned(),
            page,
            next_page: reached_limit.then_some(page + 1),
            total_count: None,
            posts,
        })
    }

    pub(crate) async fn get_e621_post(
        &self,
        key: &ProfileKey,
        post_id: u64,
        cancellation: CancellationToken,
    ) -> Result<BooruPost, CoreError> {
        ensure_e621_provider(key)?;
        if post_id == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "E621 post ID must be greater than zero",
                false,
            ));
        }
        let response = self
            .sessions
            .get_with_query(
                key,
                &format!("posts/{post_id}.json"),
                &[],
                ApiAuth::None,
                cancellation,
            )
            .await?;
        let base_url = response.final_url.clone();
        let value: serde_json::Value = parse_json(response)?;
        let post = value.get("post").ok_or_else(|| {
            CoreError::new(
                ErrorCode::ResourceNotFound,
                format!("{} post {post_id} was not found", key.provider),
                false,
            )
        })?;
        map_e621_post(key, &base_url, post)
    }

    pub(crate) async fn search_philomena(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u64,
        limit: u32,
        cancellation: CancellationToken,
    ) -> Result<BooruSearchResult, CoreError> {
        ensure_philomena_provider(key)?;
        let page = page.max(1);
        let limit = limit.clamp(1, 50);
        let parameters = vec![
            ("q".to_owned(), query.trim().to_owned()),
            ("page".to_owned(), page.to_string()),
            ("per_page".to_owned(), limit.to_string()),
        ];
        let response = self
            .sessions
            .get_with_query(
                key,
                "api/v1/json/search/images",
                &parameters,
                ApiAuth::PhilomenaQuery,
                cancellation,
            )
            .await?;
        let generation = response.generation;
        let base_url = response.final_url.clone();
        let (raw_posts, total_count) = parse_philomena_posts(response)?;
        let reached_limit = raw_posts.len() == limit as usize;
        let posts = raw_posts
            .iter()
            .map(|post| map_philomena_post(key, &base_url, post))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(BooruSearchResult {
            provider: key.provider.clone(),
            profile: key.profile.clone(),
            generation,
            query: query.trim().to_owned(),
            page,
            next_page: reached_limit.then_some(page + 1),
            total_count,
            posts,
        })
    }

    pub(crate) async fn get_philomena_post(
        &self,
        key: &ProfileKey,
        post_id: u64,
        cancellation: CancellationToken,
    ) -> Result<BooruPost, CoreError> {
        ensure_philomena_provider(key)?;
        if post_id == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Philomena image ID must be greater than zero",
                false,
            ));
        }
        let response = self
            .sessions
            .get_with_query(
                key,
                &format!("api/v1/json/images/{post_id}"),
                &[],
                ApiAuth::PhilomenaQuery,
                cancellation,
            )
            .await?;
        let base_url = response.final_url.clone();
        let value: serde_json::Value = parse_json(response)?;
        let post = value.get("image").ok_or_else(|| {
            CoreError::new(
                ErrorCode::ResourceNotFound,
                format!("{} image {post_id} was not found", key.provider),
                false,
            )
        })?;
        map_philomena_post(key, &base_url, post)
    }

    pub(crate) async fn search_paheal(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u64,
        limit: u32,
        cancellation: CancellationToken,
    ) -> Result<BooruSearchResult, CoreError> {
        ensure_provider(key, "paheal")?;
        let page = page.max(1);
        let limit = limit.clamp(1, 100);
        let parameters = vec![
            ("tags".to_owned(), query.trim().to_owned()),
            ("page".to_owned(), page.to_string()),
            ("limit".to_owned(), limit.to_string()),
        ];
        let response = self
            .sessions
            .get_with_query(
                key,
                "api/danbooru/find_posts/index.xml",
                &parameters,
                ApiAuth::None,
                cancellation,
            )
            .await?;
        let generation = response.generation;
        let base_url = response.final_url.clone();
        let raw_posts = parse_paheal_posts(response)?;
        let reached_limit = raw_posts.len() == limit as usize;
        let posts = raw_posts
            .iter()
            .map(|post| map_paheal_post(key, &base_url, post))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(BooruSearchResult {
            provider: key.provider.clone(),
            profile: key.profile.clone(),
            generation,
            query: query.trim().to_owned(),
            page,
            next_page: reached_limit.then_some(page + 1),
            total_count: None,
            posts,
        })
    }

    pub(crate) async fn get_paheal_post(
        &self,
        key: &ProfileKey,
        post_id: u64,
        cancellation: CancellationToken,
    ) -> Result<BooruPost, CoreError> {
        ensure_provider(key, "paheal")?;
        if post_id == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "Paheal post ID must be greater than zero",
                false,
            ));
        }
        let parameters = vec![
            ("id".to_owned(), post_id.to_string()),
            ("limit".to_owned(), "1".to_owned()),
        ];
        let response = self
            .sessions
            .get_with_query(
                key,
                "api/danbooru/find_posts/index.xml",
                &parameters,
                ApiAuth::None,
                cancellation,
            )
            .await?;
        let base_url = response.final_url.clone();
        let mut posts = parse_paheal_posts(response)?;
        let post = posts.pop().ok_or_else(|| {
            CoreError::new(
                ErrorCode::ResourceNotFound,
                format!("Paheal post {post_id} was not found"),
                false,
            )
        })?;
        map_paheal_post(key, &base_url, &post)
    }
}

fn gelbooru_tag_parameters(query: &str, limit: u32, json: bool) -> Vec<(String, String)> {
    let mut parameters = vec![
        ("page".to_owned(), "dapi".to_owned()),
        ("s".to_owned(), "tag".to_owned()),
        ("q".to_owned(), "index".to_owned()),
        ("name_pattern".to_owned(), format!("{query}%")),
        ("limit".to_owned(), limit.to_string()),
        ("orderby".to_owned(), "count".to_owned()),
        ("order".to_owned(), "DESC".to_owned()),
    ];
    if json {
        parameters.push(("json".to_owned(), "1".to_owned()));
    }
    parameters
}

fn booru_tag_limit(key: &ProfileKey) -> Result<u32, CoreError> {
    match key.provider.as_str() {
        "danbooru" => Ok(200),
        "gelbooru" | "safebooru" | "rule34" | "tbib" | "xbooru" | "hypnohub" | "yandere"
        | "konachan" | "konachan_net" | "lolibooru" | "behoimi" => Ok(100),
        _ => Err(unsupported_booru_provider(key)),
    }
}

fn unsupported_booru_provider(key: &ProfileKey) -> CoreError {
    CoreError::new(
        ErrorCode::InvalidInput,
        format!("profile {key} is not a supported Booru profile"),
        false,
    )
}

fn map_danbooru_post(
    key: &ProfileKey,
    response_url: &Url,
    post: DanbooruPost,
) -> Result<BooruPost, CoreError> {
    let mut page_url = response_url.clone();
    page_url.set_path(&format!("/posts/{}", post.id));
    page_url.set_query(None);
    page_url.set_fragment(None);
    let original_url = post.file_url.or_else(|| post.large_file_url.clone());
    if original_url.is_none() {
        return Err(CoreError::new(
            ErrorCode::UnexpectedResponse,
            format!("Danbooru post {} has no downloadable image URL", post.id),
            false,
        ));
    }
    Ok(BooruPost {
        provider: key.provider.clone(),
        id: post.id,
        page_url,
        original: ImageVariant {
            url: original_url,
            width: post.image_width,
            height: post.image_height,
            byte_length: post.file_size,
        },
        sample: ImageVariant {
            url: post.large_file_url,
            ..ImageVariant::default()
        },
        preview: ImageVariant {
            url: post.preview_file_url,
            ..ImageVariant::default()
        },
        general_tags: split_tags(&post.tag_string_general),
        artist_tags: split_tags(&post.tag_string_artist),
        character_tags: split_tags(&post.tag_string_character),
        copyright_tags: split_tags(&post.tag_string_copyright),
        meta_tags: split_tags(&post.tag_string_meta),
        provider_tags: BTreeMap::new(),
        rating: post.rating,
        score: post.score,
        source: nonempty(post.source),
        original_md5: normalize_md5(post.md5)?,
        file_extension: post.file_ext.and_then(normalize_extension),
        created_at: post.created_at,
    })
}

fn parse_json<T: for<'de> Deserialize<'de>>(response: NetworkResponse) -> Result<T, CoreError> {
    if response
        .content_type
        .as_deref()
        .is_some_and(|value| !value.to_ascii_lowercase().contains("json"))
    {
        return Err(CoreError::new(
            ErrorCode::UnexpectedResponse,
            "Booru API returned a non-JSON response",
            false,
        ));
    }
    serde_json::from_slice(&response.body).map_err(|_| {
        CoreError::new(
            ErrorCode::UnexpectedResponse,
            "Booru API returned malformed JSON",
            false,
        )
    })
}

fn parse_gelbooru_posts(
    response: NetworkResponse,
) -> Result<(Vec<serde_json::Value>, Option<u64>), CoreError> {
    let value: serde_json::Value = parse_json(response)?;
    if let Some(message) = value
        .get("message")
        .and_then(serde_json::Value::as_str)
        .filter(|_| value.get("success").and_then(serde_json::Value::as_bool) == Some(false))
    {
        return Err(CoreError::new(
            ErrorCode::AccessDenied,
            format!("Gelbooru API rejected the request: {message}"),
            false,
        ));
    }
    match value {
        serde_json::Value::Array(posts) => Ok((posts, None)),
        serde_json::Value::Object(mut object) => {
            let total = object
                .get("@attributes")
                .and_then(|attributes| attributes.get("count"))
                .and_then(value_u64);
            let posts = match object.remove("post") {
                None | Some(serde_json::Value::Null) => Vec::new(),
                Some(serde_json::Value::Array(posts)) => posts,
                Some(post @ serde_json::Value::Object(_)) => vec![post],
                Some(_) => return Err(unexpected("Gelbooru API returned an invalid post list")),
            };
            Ok((posts, total))
        }
        _ => Err(unexpected("Gelbooru API returned an invalid JSON root")),
    }
}

fn parse_gelbooru_xml_posts(
    response: NetworkResponse,
    provider: &str,
) -> Result<(Vec<serde_json::Value>, Option<u64>), CoreError> {
    let body = std::str::from_utf8(&response.body)
        .map_err(|_| unexpected(format!("{provider} API returned non-UTF-8 XML")))?;
    let document = roxmltree::Document::parse(body)
        .map_err(|_| unexpected(format!("{provider} API returned malformed XML")))?;
    let root = document.root_element();
    if root.tag_name().name() == "error" {
        let message = root.text().map(str::trim).filter(|value| !value.is_empty());
        return Err(CoreError::new(
            ErrorCode::AccessDenied,
            format!(
                "{provider} API rejected the request: {}",
                message.unwrap_or("unknown reason")
            ),
            false,
        ));
    }
    if root.tag_name().name() != "posts" {
        return Err(unexpected(format!(
            "{provider} API returned an invalid XML root"
        )));
    }
    let total_count = root.attribute("count").and_then(|value| value.parse().ok());
    let posts = root
        .children()
        .filter(|node| node.is_element() && node.tag_name().name() == "post")
        .map(|node| {
            serde_json::Value::Object(
                node.attributes()
                    .map(|attribute| {
                        (
                            attribute.name().to_owned(),
                            serde_json::Value::String(attribute.value().to_owned()),
                        )
                    })
                    .collect(),
            )
        })
        .collect();
    Ok((posts, total_count))
}

fn parse_tag_json(
    response: NetworkResponse,
    category_field: &str,
    count_field: &str,
) -> Result<Vec<BooruTagSuggestion>, CoreError> {
    let values: Vec<serde_json::Value> = parse_json(response)?;
    values
        .iter()
        .map(|value| map_tag_suggestion(value, category_field, count_field))
        .collect()
}

fn parse_gelbooru_tag_json(
    response: NetworkResponse,
) -> Result<Vec<BooruTagSuggestion>, CoreError> {
    let value: serde_json::Value = parse_json(response)?;
    let values = match value {
        serde_json::Value::Array(values) => values,
        serde_json::Value::Object(mut object) => match object.remove("tag") {
            None | Some(serde_json::Value::Null) => Vec::new(),
            Some(serde_json::Value::Array(values)) => values,
            Some(value @ serde_json::Value::Object(_)) => vec![value],
            Some(_) => return Err(unexpected("Gelbooru API returned an invalid tag list")),
        },
        _ => return Err(unexpected("Gelbooru API returned an invalid tag response")),
    };
    values
        .iter()
        .map(|value| map_tag_suggestion(value, "type", "count"))
        .collect()
}

fn map_tag_suggestion(
    value: &serde_json::Value,
    category_field: &str,
    count_field: &str,
) -> Result<BooruTagSuggestion, CoreError> {
    let object = value
        .as_object()
        .ok_or_else(|| unexpected("Booru tag suggestion must be an object"))?;
    let tag = object
        .get("name")
        .and_then(serde_json::Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| unexpected("Booru tag suggestion has no name"))?;
    Ok(BooruTagSuggestion {
        tag: tag.to_owned(),
        category: tag_category(object.get(category_field).and_then(value_i64)),
        count: object
            .get(count_field)
            .and_then(value_u64)
            .unwrap_or_default(),
    })
}

fn parse_tag_xml(
    response: NetworkResponse,
    provider: &str,
) -> Result<Vec<BooruTagSuggestion>, CoreError> {
    let body = std::str::from_utf8(&response.body)
        .map_err(|_| unexpected(format!("{provider} API returned non-UTF-8 tag XML")))?;
    let document = roxmltree::Document::parse(body)
        .map_err(|_| unexpected(format!("{provider} API returned malformed tag XML")))?;
    let root = document.root_element();
    if root.tag_name().name() == "error" {
        return Err(CoreError::new(
            ErrorCode::AccessDenied,
            format!("{provider} tag API rejected the request"),
            false,
        ));
    }
    if root.tag_name().name() != "tags" {
        return Err(unexpected(format!(
            "{provider} API returned an invalid tag XML root"
        )));
    }
    root.children()
        .filter(|node| node.is_element() && node.tag_name().name() == "tag")
        .map(|node| {
            let tag = node
                .attribute("name")
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .ok_or_else(|| unexpected("Booru tag suggestion has no name"))?;
            Ok(BooruTagSuggestion {
                tag: tag.to_owned(),
                category: tag_category(node.attribute("type").and_then(|value| value.parse().ok())),
                count: node
                    .attribute("count")
                    .and_then(|value| value.parse().ok())
                    .unwrap_or_default(),
            })
        })
        .collect()
}

fn tag_category(value: Option<i64>) -> String {
    match value {
        Some(1) => "artist",
        Some(3) => "copyright",
        Some(4) => "character",
        Some(5) => "meta",
        _ => "general",
    }
    .to_owned()
}

fn map_gelbooru_post(
    key: &ProfileKey,
    response_url: &Url,
    value: &serde_json::Value,
) -> Result<BooruPost, CoreError> {
    let object = value
        .as_object()
        .ok_or_else(|| unexpected("Gelbooru API post must be an object"))?;
    let id = object
        .get("id")
        .and_then(value_u64)
        .ok_or_else(|| unexpected("Gelbooru API post has no valid ID"))?;
    let original_url = object
        .get("file_url")
        .and_then(|value| value_url_with_base(value, response_url));
    let sample_url = object
        .get("sample_url")
        .and_then(|value| value_url_with_base(value, response_url));
    if original_url.is_none() && sample_url.is_none() {
        return Err(unexpected(format!(
            "Gelbooru post {id} has no downloadable image URL"
        )));
    }
    let mut page_url = response_url.clone();
    page_url.set_path("/index.php");
    page_url.set_query(Some(&format!("page=post&s=view&id={id}")));
    page_url.set_fragment(None);
    let tags = object
        .get("tags")
        .and_then(serde_json::Value::as_str)
        .map_or_else(Vec::new, split_tags);
    let original_md5 = normalize_md5(
        object
            .get("md5")
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned),
    )?;
    let file_extension = object
        .get("image")
        .or_else(|| object.get("file_url"))
        .and_then(serde_json::Value::as_str)
        .and_then(|value| {
            value
                .rsplit_once('.')
                .map(|(_, extension)| extension.to_owned())
        })
        .and_then(normalize_extension);
    Ok(BooruPost {
        provider: key.provider.clone(),
        id,
        page_url,
        original: ImageVariant {
            url: original_url.or_else(|| sample_url.clone()),
            width: object.get("width").and_then(value_u32),
            height: object.get("height").and_then(value_u32),
            byte_length: None,
        },
        sample: ImageVariant {
            url: sample_url,
            width: object.get("sample_width").and_then(value_u32),
            height: object.get("sample_height").and_then(value_u32),
            byte_length: None,
        },
        preview: ImageVariant {
            url: object
                .get("preview_url")
                .and_then(|value| value_url_with_base(value, response_url)),
            width: object.get("preview_width").and_then(value_u32),
            height: object.get("preview_height").and_then(value_u32),
            byte_length: None,
        },
        general_tags: tags,
        artist_tags: Vec::new(),
        character_tags: Vec::new(),
        copyright_tags: Vec::new(),
        meta_tags: Vec::new(),
        provider_tags: BTreeMap::new(),
        rating: object
            .get("rating")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        score: object.get("score").and_then(value_i64).unwrap_or_default(),
        source: object
            .get("source")
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned)
            .and_then(nonempty),
        original_md5,
        file_extension,
        created_at: object
            .get("created_at")
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned),
    })
}

fn map_moebooru_post(
    key: &ProfileKey,
    response_url: &Url,
    value: &serde_json::Value,
) -> Result<BooruPost, CoreError> {
    let mut post = map_gelbooru_post(key, response_url, value)?;
    post.page_url.set_path(&format!("/post/show/{}", post.id));
    post.page_url.set_query(None);
    post.file_extension = value
        .get("file_ext")
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned)
        .and_then(normalize_extension)
        .or(post.file_extension);
    post.created_at = value.get("created_at").map(|value| match value {
        serde_json::Value::String(value) => value.clone(),
        value => value.to_string(),
    });
    Ok(post)
}

fn parse_e621_posts(response: NetworkResponse) -> Result<Vec<serde_json::Value>, CoreError> {
    let mut value: serde_json::Value = parse_json(response)?;
    match value.get_mut("posts").map(serde_json::Value::take) {
        Some(serde_json::Value::Array(posts)) => Ok(posts),
        _ => Err(unexpected("E621 API returned an invalid post list")),
    }
}

fn map_e621_post(
    key: &ProfileKey,
    response_url: &Url,
    value: &serde_json::Value,
) -> Result<BooruPost, CoreError> {
    let object = value
        .as_object()
        .ok_or_else(|| unexpected("E621 API post must be an object"))?;
    let id = object
        .get("id")
        .and_then(value_u64)
        .ok_or_else(|| unexpected("E621 API post has no valid ID"))?;
    let file = object
        .get("file")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| unexpected("E621 API post has no file metadata"))?;
    let sample = object.get("sample").and_then(serde_json::Value::as_object);
    let preview = object.get("preview").and_then(serde_json::Value::as_object);
    let original_url = file
        .get("url")
        .and_then(|value| value_url_with_base(value, response_url));
    if original_url.is_none() {
        return Err(unexpected(format!(
            "{} post {id} has no downloadable image URL",
            key.provider
        )));
    }
    let provider_tags = object
        .get("tags")
        .and_then(serde_json::Value::as_object)
        .map(|tags| {
            tags.iter()
                .filter_map(|(category, values)| {
                    let values = values.as_array()?;
                    Some((
                        category.clone(),
                        values
                            .iter()
                            .filter_map(serde_json::Value::as_str)
                            .map(str::to_owned)
                            .collect(),
                    ))
                })
                .collect::<BTreeMap<_, _>>()
        })
        .unwrap_or_default();
    let mut page_url = response_url.clone();
    page_url.set_path(&format!("/posts/{id}"));
    page_url.set_query(None);
    Ok(BooruPost {
        provider: key.provider.clone(),
        id,
        page_url,
        original: ImageVariant {
            url: original_url,
            width: file.get("width").and_then(value_u32),
            height: file.get("height").and_then(value_u32),
            byte_length: file.get("size").and_then(value_u64),
        },
        sample: ImageVariant {
            url: sample
                .and_then(|sample| sample.get("url"))
                .and_then(|value| value_url_with_base(value, response_url)),
            width: sample
                .and_then(|sample| sample.get("width"))
                .and_then(value_u32),
            height: sample
                .and_then(|sample| sample.get("height"))
                .and_then(value_u32),
            byte_length: None,
        },
        preview: ImageVariant {
            url: preview
                .and_then(|preview| preview.get("url"))
                .and_then(|value| value_url_with_base(value, response_url)),
            width: preview
                .and_then(|preview| preview.get("width"))
                .and_then(value_u32),
            height: preview
                .and_then(|preview| preview.get("height"))
                .and_then(value_u32),
            byte_length: None,
        },
        general_tags: provider_tags.get("general").cloned().unwrap_or_default(),
        artist_tags: provider_tags.get("artist").cloned().unwrap_or_default(),
        character_tags: provider_tags.get("character").cloned().unwrap_or_default(),
        copyright_tags: provider_tags.get("copyright").cloned().unwrap_or_default(),
        meta_tags: provider_tags.get("meta").cloned().unwrap_or_default(),
        provider_tags,
        rating: object
            .get("rating")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        score: object
            .get("score")
            .and_then(|score| score.get("total").or(Some(score)))
            .and_then(value_i64)
            .unwrap_or_default(),
        source: object
            .get("sources")
            .and_then(serde_json::Value::as_array)
            .and_then(|sources| sources.first())
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned)
            .and_then(nonempty),
        original_md5: normalize_md5(
            file.get("md5")
                .and_then(serde_json::Value::as_str)
                .map(str::to_owned),
        )?,
        file_extension: file
            .get("ext")
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned)
            .and_then(normalize_extension),
        created_at: object
            .get("created_at")
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned),
    })
}

fn parse_philomena_posts(
    response: NetworkResponse,
) -> Result<(Vec<serde_json::Value>, Option<u64>), CoreError> {
    let mut value: serde_json::Value = parse_json(response)?;
    let total = value.get("total").and_then(value_u64);
    match value.get_mut("images").map(serde_json::Value::take) {
        Some(serde_json::Value::Array(posts)) => Ok((posts, total)),
        _ => Err(unexpected("Philomena API returned an invalid image list")),
    }
}

fn map_philomena_post(
    key: &ProfileKey,
    response_url: &Url,
    value: &serde_json::Value,
) -> Result<BooruPost, CoreError> {
    let object = value
        .as_object()
        .ok_or_else(|| unexpected("Philomena API image must be an object"))?;
    let id = object
        .get("id")
        .and_then(value_u64)
        .ok_or_else(|| unexpected("Philomena API image has no valid ID"))?;
    let representations = object
        .get("representations")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| unexpected("Philomena API image has no representations"))?;
    let original_url = representations
        .get("full")
        .and_then(|value| value_url_with_base(value, response_url));
    if original_url.is_none() {
        return Err(unexpected(format!(
            "{} image {id} has no full representation",
            key.provider
        )));
    }
    let general_tags = object
        .get("tags")
        .and_then(serde_json::Value::as_array)
        .map(|tags| {
            tags.iter()
                .filter_map(serde_json::Value::as_str)
                .map(str::to_owned)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let provider_tags = BTreeMap::from([("general".to_owned(), general_tags.clone())]);
    let mut page_url = response_url.clone();
    page_url.set_path(&format!("/images/{id}"));
    page_url.set_query(None);
    Ok(BooruPost {
        provider: key.provider.clone(),
        id,
        page_url,
        original: ImageVariant {
            url: original_url,
            width: object.get("width").and_then(value_u32),
            height: object.get("height").and_then(value_u32),
            byte_length: None,
        },
        sample: ImageVariant {
            url: representations
                .get("large")
                .and_then(|value| value_url_with_base(value, response_url)),
            ..ImageVariant::default()
        },
        preview: ImageVariant {
            url: representations
                .get("thumb")
                .or_else(|| representations.get("small"))
                .and_then(|value| value_url_with_base(value, response_url)),
            ..ImageVariant::default()
        },
        general_tags,
        artist_tags: Vec::new(),
        character_tags: Vec::new(),
        copyright_tags: Vec::new(),
        meta_tags: Vec::new(),
        provider_tags,
        rating: object
            .get("sfw")
            .map(serde_json::Value::to_string)
            .unwrap_or_default(),
        score: object.get("score").and_then(value_i64).unwrap_or_default(),
        source: object
            .get("source_url")
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned)
            .and_then(nonempty),
        original_md5: None,
        file_extension: representations
            .get("full")
            .and_then(serde_json::Value::as_str)
            .and_then(|url| {
                url.rsplit_once('.')
                    .map(|(_, extension)| extension.to_owned())
            })
            .and_then(normalize_extension),
        created_at: object
            .get("created_at")
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned),
    })
}

fn parse_paheal_posts(response: NetworkResponse) -> Result<Vec<serde_json::Value>, CoreError> {
    let body = std::str::from_utf8(&response.body)
        .map_err(|_| unexpected("Paheal API returned non-UTF-8 XML"))?;
    let document = roxmltree::Document::parse(body)
        .map_err(|_| unexpected("Paheal API returned malformed XML"))?;
    Ok(document
        .descendants()
        .filter(|node| {
            node.is_element()
                && matches!(node.tag_name().name(), "post" | "tag")
                && node.attribute("file_url").is_some()
        })
        .map(|node| {
            serde_json::Value::Object(
                node.attributes()
                    .map(|attribute| {
                        (
                            attribute.name().to_owned(),
                            serde_json::Value::String(attribute.value().to_owned()),
                        )
                    })
                    .collect(),
            )
        })
        .collect())
}

fn map_paheal_post(
    key: &ProfileKey,
    response_url: &Url,
    value: &serde_json::Value,
) -> Result<BooruPost, CoreError> {
    let mut post = map_gelbooru_post(key, response_url, value)?;
    post.page_url.set_path(&format!("/post/view/{}", post.id));
    post.page_url.set_query(None);
    post.original_md5 = None;
    Ok(post)
}

fn value_u64(value: &serde_json::Value) -> Option<u64> {
    value
        .as_u64()
        .or_else(|| value.as_str().and_then(|value| value.parse().ok()))
}

fn value_u32(value: &serde_json::Value) -> Option<u32> {
    value_u64(value).and_then(|value| u32::try_from(value).ok())
}

fn value_i64(value: &serde_json::Value) -> Option<i64> {
    value
        .as_i64()
        .or_else(|| value.as_str().and_then(|value| value.parse().ok()))
}

fn value_url_with_base(value: &serde_json::Value, base: &Url) -> Option<Url> {
    let value = value.as_str()?.trim();
    if value.is_empty() {
        None
    } else if value.starts_with("//") {
        Url::parse(&format!("{}:{value}", base.scheme())).ok()
    } else {
        Url::parse(value).ok().or_else(|| base.join(value).ok())
    }
}

fn unexpected(message: impl Into<String>) -> CoreError {
    CoreError::new(ErrorCode::UnexpectedResponse, message, false)
}

fn ensure_provider(key: &ProfileKey, expected: &str) -> Result<(), CoreError> {
    if key.provider == expected {
        Ok(())
    } else {
        Err(CoreError::new(
            ErrorCode::InvalidInput,
            format!("profile {key} is not a {expected} profile"),
            false,
        ))
    }
}

fn ensure_gelbooru_xml_provider(key: &ProfileKey) -> Result<(), CoreError> {
    if matches!(
        key.provider.as_str(),
        "safebooru" | "rule34" | "tbib" | "xbooru" | "hypnohub"
    ) {
        Ok(())
    } else {
        Err(CoreError::new(
            ErrorCode::InvalidInput,
            format!("profile {key} is not a supported Gelbooru-style XML profile"),
            false,
        ))
    }
}

fn ensure_moebooru_provider(key: &ProfileKey) -> Result<(), CoreError> {
    if matches!(
        key.provider.as_str(),
        "yandere" | "konachan" | "konachan_net" | "lolibooru" | "behoimi"
    ) {
        Ok(())
    } else {
        Err(CoreError::new(
            ErrorCode::InvalidInput,
            format!("profile {key} is not a supported Moebooru profile"),
            false,
        ))
    }
}

fn ensure_e621_provider(key: &ProfileKey) -> Result<(), CoreError> {
    if matches!(key.provider.as_str(), "e621" | "e926") {
        Ok(())
    } else {
        Err(CoreError::new(
            ErrorCode::InvalidInput,
            format!("profile {key} is not a supported E621 profile"),
            false,
        ))
    }
}

fn ensure_philomena_provider(key: &ProfileKey) -> Result<(), CoreError> {
    if matches!(key.provider.as_str(), "derpibooru" | "furbooru") {
        Ok(())
    } else {
        Err(CoreError::new(
            ErrorCode::InvalidInput,
            format!("profile {key} is not a supported Philomena profile"),
            false,
        ))
    }
}

fn split_tags(value: &str) -> Vec<String> {
    value.split_whitespace().map(str::to_owned).collect()
}

fn nonempty(value: String) -> Option<String> {
    (!value.trim().is_empty()).then_some(value)
}

fn normalize_md5(value: Option<String>) -> Result<Option<String>, CoreError> {
    let Some(value) = value else {
        return Ok(None);
    };
    let value = value.to_ascii_lowercase();
    if value.len() == 32 && value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        Ok(Some(value))
    } else {
        Err(CoreError::new(
            ErrorCode::UnexpectedResponse,
            "Booru API returned an invalid original MD5",
            false,
        ))
    }
}

fn normalize_extension(value: String) -> Option<String> {
    let value = value.trim().trim_start_matches('.').to_ascii_lowercase();
    (!value.is_empty()
        && value.len() <= 10
        && value.bytes().all(|byte| byte.is_ascii_alphanumeric()))
    .then_some(if value == "jpeg" {
        "jpg".to_owned()
    } else {
        value
    })
}

#[cfg(test)]
mod tests {
    use super::BooruService;
    use crate::{NetworkConfig, ProfileKey, ProviderProfileConfig, session::SessionRegistry};
    use axum::{
        Router,
        extract::Query,
        http::{HeaderMap, StatusCode, header},
        response::IntoResponse,
        routing::get,
    };
    use std::{
        collections::{BTreeMap, HashMap},
        sync::Arc,
    };
    use tokio::net::TcpListener;
    use tokio_util::sync::CancellationToken;
    use url::Url;

    const DANBOORU_POSTS: &str = include_str!("../../tests/fixtures/danbooru/posts.json");
    const GELBOORU_POSTS: &str = include_str!("../../tests/fixtures/gelbooru/posts.json");
    const SAFEBOORU_POSTS: &str = include_str!("../../tests/fixtures/safebooru/posts.xml");
    const MOEBOORU_POSTS: &str = include_str!("../../tests/fixtures/moebooru/posts.json");
    const TAGS_JSON: &str = include_str!("../../tests/fixtures/booru/tags.json");
    const TAGS_XML: &str = include_str!("../../tests/fixtures/booru/tags.xml");
    const E621_POSTS: &str = include_str!("../../tests/fixtures/e621/posts.json");
    const PHILOMENA_IMAGES: &str = include_str!("../../tests/fixtures/philomena/images.json");
    const PAHEAL_POSTS: &str = include_str!("../../tests/fixtures/paheal/posts.xml");

    async fn server(router: Router) -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let listen = listener.local_addr().unwrap();
        tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
        listen
    }

    fn service(provider: &str, listen: std::net::SocketAddr) -> (BooruService, ProfileKey) {
        let profile = ProviderProfileConfig {
            provider: provider.to_owned(),
            profile: "default".to_owned(),
            base_url: Url::parse(&format!("http://{listen}/")).unwrap(),
            ..ProviderProfileConfig::default()
        };
        let profiles = BTreeMap::from([("default".to_owned(), profile)]);
        let sessions =
            Arc::new(SessionRegistry::new(&profiles, &NetworkConfig::default()).unwrap());
        (
            BooruService::new(sessions),
            ProfileKey::new(provider, "default"),
        )
    }

    #[tokio::test]
    async fn maps_danbooru_search_and_detail_fixtures() {
        let router = Router::new()
            .route(
                "/posts.json",
                get(
                    |Query(query): Query<HashMap<String, String>>, headers: HeaderMap| async move {
                        assert_eq!(query.get("tags").map(String::as_str), Some("blue_sky"));
                        assert_eq!(query.get("page").map(String::as_str), Some("2"));
                        assert_eq!(query.get("limit").map(String::as_str), Some("1"));
                        assert!(headers.get(header::AUTHORIZATION).is_none());
                        ([(header::CONTENT_TYPE, "application/json")], DANBOORU_POSTS)
                    },
                ),
            )
            .route(
                "/posts/123.json",
                get(|| async {
                    let detail = DANBOORU_POSTS
                        .trim()
                        .strip_prefix('[')
                        .and_then(|value| value.strip_suffix(']'))
                        .expect("fixture is a JSON array");
                    ([(header::CONTENT_TYPE, "application/json")], detail)
                }),
            );
        let listen = server(router).await;
        let (service, key) = service("danbooru", listen);
        let result = service
            .search_danbooru(&key, "blue_sky", 2, 1, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.page, 2);
        assert_eq!(result.next_page, Some(3));
        assert_eq!(result.posts[0].id, 123);
        assert_eq!(
            result.posts[0].original_md5.as_deref(),
            Some("d256310bfab43e08b6422e311cd9b2c9")
        );
        assert_eq!(result.posts[0].general_tags, ["blue_sky", "cloud"]);
        assert_eq!(result.posts[0].file_extension.as_deref(), Some("webp"));

        let detail = service
            .get_danbooru_post(&key, 123, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(detail.id, 123);
        assert!(detail.page_url.as_str().ends_with("/posts/123"));
    }

    #[tokio::test]
    async fn maps_gelbooru_search_and_empty_detail() {
        let router = Router::new().route(
            "/index.php",
            get(|Query(query): Query<HashMap<String, String>>| async move {
                assert_eq!(query.get("page").map(String::as_str), Some("dapi"));
                assert_eq!(query.get("s").map(String::as_str), Some("post"));
                assert_eq!(query.get("q").map(String::as_str), Some("index"));
                if query.contains_key("id") {
                    return (
                        [(header::CONTENT_TYPE, "application/json")],
                        r#"{"@attributes":{"count":0},"post":[]}"#,
                    )
                        .into_response();
                }
                assert_eq!(query.get("pid").map(String::as_str), Some("0"));
                assert_eq!(query.get("tags").map(String::as_str), Some("cloud"));
                ([(header::CONTENT_TYPE, "application/json")], GELBOORU_POSTS).into_response()
            }),
        );
        let listen = server(router).await;
        let (service, key) = service("gelbooru", listen);
        let result = service
            .search_gelbooru(&key, "cloud", 0, 100, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.total_count, Some(1));
        assert_eq!(result.posts[0].id, 456);
        assert_eq!(result.posts[0].original.width, Some(1920));
        assert_eq!(result.posts[0].preview.height, Some(169));
        assert_eq!(result.posts[0].file_extension.as_deref(), Some("webp"));

        let error = service
            .get_gelbooru_post(&key, 999, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(error.code(), crate::ErrorCode::ResourceNotFound);
    }

    #[tokio::test]
    async fn maps_safebooru_xml_search_detail_and_rejection() {
        let router = Router::new().route(
            "/index.php",
            get(|Query(query): Query<HashMap<String, String>>| async move {
                assert_eq!(query.get("page").map(String::as_str), Some("dapi"));
                assert_eq!(query.get("s").map(String::as_str), Some("post"));
                assert_eq!(query.get("q").map(String::as_str), Some("index"));
                if query.get("id").map(String::as_str) == Some("999") {
                    return (
                        [(header::CONTENT_TYPE, "application/xml")],
                        "<posts count=\"0\" />",
                    )
                        .into_response();
                }
                if query.get("tags").map(String::as_str) == Some("denied") {
                    return (
                        [(header::CONTENT_TYPE, "application/xml")],
                        "<error>blocked</error>",
                    )
                        .into_response();
                }
                ([(header::CONTENT_TYPE, "application/xml")], SAFEBOORU_POSTS).into_response()
            }),
        );
        let listen = server(router).await;
        let (safebooru, key) = service("safebooru", listen);
        let result = safebooru
            .search_gelbooru_xml(&key, "blue_sky", 0, 1, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.total_count, Some(1));
        assert_eq!(result.next_page, Some(1));
        assert_eq!(result.posts[0].id, 789);
        assert_eq!(result.posts[0].general_tags, ["blue_sky", "cloud"]);
        assert_eq!(
            result.posts[0].original_md5.as_deref(),
            Some("d256310bfab43e08b6422e311cd9b2c9")
        );
        assert_eq!(
            result.posts[0].original.url.as_ref().unwrap().host_str(),
            Some("127.0.0.1")
        );
        assert_eq!(
            result.posts[0].preview.url.as_ref().unwrap().as_str(),
            "http://cdn.safebooru.example/thumbnails/example.jpg"
        );

        let detail = safebooru
            .get_gelbooru_xml_post(&key, 789, CancellationToken::new())
            .await
            .unwrap();
        assert!(detail.page_url.as_str().contains("id=789"));
        let missing = safebooru
            .get_gelbooru_xml_post(&key, 999, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(missing.code(), crate::ErrorCode::ResourceNotFound);
        let denied = safebooru
            .search_gelbooru_xml(&key, "denied", 0, 40, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(denied.code(), crate::ErrorCode::AccessDenied);

        let (rule34, key) = service("rule34", listen);
        let result = rule34
            .search_gelbooru_xml(&key, "blue_sky", 0, 40, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.provider, "rule34");
        assert_eq!(result.posts[0].provider, "rule34");

        let (danbooru, key) = service("danbooru", listen);
        let error = danbooru
            .search_gelbooru_xml(&key, "", 0, 40, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(error.code(), crate::ErrorCode::InvalidInput);
    }

    #[tokio::test]
    async fn maps_moebooru_search_detail_and_protocol_allowlist() {
        let router = Router::new().route(
            "/post.json",
            get(|Query(query): Query<HashMap<String, String>>| async move {
                if query.get("tags").map(String::as_str) == Some("id:999") {
                    return ([(header::CONTENT_TYPE, "application/json")], "[]").into_response();
                }
                ([(header::CONTENT_TYPE, "application/json")], MOEBOORU_POSTS).into_response()
            }),
        );
        let listen = server(router).await;
        let (yandere, key) = service("yandere", listen);
        let result = yandere
            .search_moebooru(&key, "landscape", 1, 1, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.provider, "yandere");
        assert_eq!(result.next_page, Some(2));
        assert_eq!(result.posts[0].id, 2468);
        assert_eq!(result.posts[0].file_extension.as_deref(), Some("webp"));
        assert_eq!(result.posts[0].created_at.as_deref(), Some("1785240000"));
        assert!(
            result.posts[0]
                .page_url
                .as_str()
                .ends_with("/post/show/2468")
        );

        let detail = yandere
            .get_moebooru_post(&key, 2468, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(
            detail.original_md5.as_deref(),
            Some("d256310bfab43e08b6422e311cd9b2c9")
        );
        let missing = yandere
            .get_moebooru_post(&key, 999, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(missing.code(), crate::ErrorCode::ResourceNotFound);

        let (danbooru, key) = service("danbooru", listen);
        let error = danbooru
            .search_moebooru(&key, "", 1, 40, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(error.code(), crate::ErrorCode::InvalidInput);
    }

    #[tokio::test]
    async fn maps_tag_suggestions_for_all_four_protocols() {
        let router = Router::new()
            .route(
                "/tags.json",
                get(|Query(query): Query<HashMap<String, String>>| async move {
                    assert_eq!(
                        query.get("search[name_matches]").map(String::as_str),
                        Some("blue*")
                    );
                    ([(header::CONTENT_TYPE, "application/json")], TAGS_JSON)
                }),
            )
            .route(
                "/index.php",
                get(|Query(query): Query<HashMap<String, String>>| async move {
                    assert_eq!(query.get("s").map(String::as_str), Some("tag"));
                    assert_eq!(query.get("name_pattern").map(String::as_str), Some("blue%"));
                    if query.get("json").map(String::as_str) == Some("1") {
                        return (
                            [(header::CONTENT_TYPE, "application/json")],
                            r#"{"tag":[{"name":"blue_sky","type":"0","count":"1234"}]}"#,
                        )
                            .into_response();
                    }
                    ([(header::CONTENT_TYPE, "application/xml")], TAGS_XML).into_response()
                }),
            )
            .route(
                "/tag.json",
                get(|Query(query): Query<HashMap<String, String>>| async move {
                    assert_eq!(query.get("name").map(String::as_str), Some("blue*"));
                    (
                        [(header::CONTENT_TYPE, "application/json")],
                        r#"[{"name":"blue_artist","type":1,"count":56}]"#,
                    )
                }),
            );
        let listen = server(router).await;

        let (danbooru, key) = service("danbooru", listen);
        let result = danbooru
            .tag_suggestions(&key, " blue ", 20, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.query, "blue");
        assert_eq!(result.suggestions[0].category, "general");
        assert_eq!(result.suggestions[1].category, "artist");

        let (gelbooru, key) = service("gelbooru", listen);
        let result = gelbooru
            .tag_suggestions(&key, "blue", 20, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.suggestions[0].count, 1234);

        let (rule34, key) = service("rule34", listen);
        let result = rule34
            .tag_suggestions(&key, "blue", 20, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.suggestions[1].category, "character");

        let (yandere, key) = service("yandere", listen);
        let result = yandere
            .tag_suggestions(&key, "blue", 20, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.suggestions[0].tag, "blue_artist");
        assert_eq!(result.suggestions[0].category, "artist");

        let error = yandere
            .tag_suggestions(&key, " ", 20, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(error.code(), crate::ErrorCode::InvalidInput);
    }

    #[tokio::test]
    async fn maps_e621_search_detail_and_provider_specific_tags() {
        let router = Router::new()
            .route(
                "/posts.json",
                get(|Query(query): Query<HashMap<String, String>>| async move {
                    assert_eq!(query.get("tags").map(String::as_str), Some("fox"));
                    assert_eq!(query.get("page").map(String::as_str), Some("1"));
                    assert_eq!(query.get("limit").map(String::as_str), Some("1"));
                    ([(header::CONTENT_TYPE, "application/json")], E621_POSTS)
                }),
            )
            .route(
                "/posts/13579.json",
                get(|| async {
                    let value: serde_json::Value = serde_json::from_str(E621_POSTS).unwrap();
                    let post = &value["posts"][0];
                    (
                        [(header::CONTENT_TYPE, "application/json")],
                        serde_json::json!({"post": post}).to_string(),
                    )
                }),
            );
        let listen = server(router).await;
        let (e621, key) = service("e621", listen);
        let result = e621
            .search_e621(&key, "fox", 1, 1, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.provider, "e621");
        assert_eq!(result.next_page, Some(2));
        let post = &result.posts[0];
        assert_eq!(post.id, 13579);
        assert_eq!(post.score, 47);
        assert_eq!(post.original.byte_length, Some(456789));
        assert_eq!(post.provider_tags["species"], ["fox"]);
        assert_eq!(post.artist_tags, ["fixture_artist"]);

        let detail = e621
            .get_e621_post(&key, 13579, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(detail.file_extension.as_deref(), Some("webp"));
        assert_eq!(
            detail.original_md5.as_deref(),
            Some("d256310bfab43e08b6422e311cd9b2c9")
        );

        let (e926, key) = service("e926", listen);
        let detail = e926
            .get_e621_post(&key, 13579, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(detail.provider, "e926");
    }

    #[tokio::test]
    async fn maps_philomena_search_detail_and_api_key() {
        let router = Router::new()
            .route(
                "/api/v1/json/search/images",
                get(|Query(query): Query<HashMap<String, String>>| async move {
                    assert_eq!(query.get("q").map(String::as_str), Some("landscape"));
                    assert_eq!(query.get("per_page").map(String::as_str), Some("1"));
                    assert_eq!(query.get("key").map(String::as_str), Some("fixture-key"));
                    (
                        [(header::CONTENT_TYPE, "application/json")],
                        PHILOMENA_IMAGES,
                    )
                }),
            )
            .route(
                "/api/v1/json/images/97531",
                get(|Query(query): Query<HashMap<String, String>>| async move {
                    assert_eq!(query.get("key").map(String::as_str), Some("fixture-key"));
                    let value: serde_json::Value = serde_json::from_str(PHILOMENA_IMAGES).unwrap();
                    (
                        [(header::CONTENT_TYPE, "application/json")],
                        serde_json::json!({"image": &value["images"][0]}).to_string(),
                    )
                }),
            );
        let listen = server(router).await;
        let profile = ProviderProfileConfig {
            provider: "derpibooru".to_owned(),
            profile: "default".to_owned(),
            base_url: Url::parse(&format!("http://{listen}/")).unwrap(),
            api_key: Some("fixture-key".to_owned()),
            ..ProviderProfileConfig::default()
        };
        let sessions = Arc::new(
            SessionRegistry::new(
                &BTreeMap::from([("default".to_owned(), profile)]),
                &NetworkConfig::default(),
            )
            .unwrap(),
        );
        let service = BooruService::new(sessions);
        let key = ProfileKey::new("derpibooru", "default");
        let result = service
            .search_philomena(&key, "landscape", 1, 1, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.total_count, Some(1));
        assert_eq!(result.posts[0].id, 97531);
        assert_eq!(result.posts[0].general_tags[2], "blue sky");
        assert_eq!(result.posts[0].rating, "true");
        assert_eq!(result.posts[0].original_md5, None);

        let detail = service
            .get_philomena_post(&key, 97531, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(detail.file_extension.as_deref(), Some("webp"));
        assert!(detail.page_url.as_str().ends_with("/images/97531"));
    }

    #[tokio::test]
    async fn maps_paheal_legacy_xml_search_and_detail() {
        let router = Router::new().route(
            "/api/danbooru/find_posts/index.xml",
            get(|Query(query): Query<HashMap<String, String>>| async move {
                if query.get("id").map(String::as_str) == Some("999") {
                    return ([(header::CONTENT_TYPE, "application/xml")], "<posts />")
                        .into_response();
                }
                ([(header::CONTENT_TYPE, "application/xml")], PAHEAL_POSTS).into_response()
            }),
        );
        let listen = server(router).await;
        let (paheal, key) = service("paheal", listen);
        let result = paheal
            .search_paheal(&key, "landscape", 1, 1, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(result.next_page, Some(2));
        assert_eq!(result.posts[0].id, 86420);
        assert_eq!(result.posts[0].general_tags, ["landscape", "blue_sky"]);
        assert!(
            result.posts[0]
                .page_url
                .as_str()
                .ends_with("/post/view/86420")
        );
        assert_eq!(result.posts[0].original_md5, None);

        let detail = paheal
            .get_paheal_post(&key, 86420, CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(detail.file_extension.as_deref(), Some("webp"));
        let missing = paheal
            .get_paheal_post(&key, 999, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(missing.code(), crate::ErrorCode::ResourceNotFound);
    }

    #[tokio::test]
    async fn rejects_invalid_md5_and_non_json() {
        let invalid = r#"[{"id":1,"md5":"not-md5","file_url":"https://cdn.example/a.jpg"}]"#;
        let router = Router::new()
            .route(
                "/posts.json",
                get(move || async move { ([(header::CONTENT_TYPE, "application/json")], invalid) }),
            )
            .route(
                "/posts/1.json",
                get(|| async { ([(header::CONTENT_TYPE, "text/html")], "<html></html>") }),
            );
        let listen = server(router).await;
        let (service, key) = service("danbooru", listen);
        let error = service
            .search_danbooru(&key, "", 1, 40, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(error.code(), crate::ErrorCode::UnexpectedResponse);
        let error = service
            .get_danbooru_post(&key, 1, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(error.code(), crate::ErrorCode::UnexpectedResponse);
    }

    #[tokio::test]
    async fn maps_provider_http_errors() {
        let router = Router::new().route(
            "/posts.json",
            get(|| async { (StatusCode::TOO_MANY_REQUESTS, "slow down") }),
        );
        let listen = server(router).await;
        let (service, key) = service("danbooru", listen);
        let error = service
            .search_danbooru(&key, "", 1, 40, CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(error.code(), crate::ErrorCode::RateLimited);
        assert!(error.retryable());
    }
}
