//! Booru public API models and protocol implementations.

use crate::{
    CoreError, ErrorCode, ProfileKey,
    session::{ApiAuth, NetworkResponse, SessionRegistry},
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
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
    let original_url = object.get("file_url").and_then(value_url);
    let sample_url = object.get("sample_url").and_then(value_url);
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
            url: object.get("preview_url").and_then(value_url),
            width: object.get("preview_width").and_then(value_u32),
            height: object.get("preview_height").and_then(value_u32),
            byte_length: None,
        },
        general_tags: tags,
        artist_tags: Vec::new(),
        character_tags: Vec::new(),
        copyright_tags: Vec::new(),
        meta_tags: Vec::new(),
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

fn value_url(value: &serde_json::Value) -> Option<Url> {
    let value = value.as_str()?.trim();
    if value.is_empty() {
        None
    } else if value.starts_with("//") {
        Url::parse(&format!("https:{value}")).ok()
    } else {
        Url::parse(value).ok()
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
                    (
                        [(header::CONTENT_TYPE, "application/json")],
                        &DANBOORU_POSTS[1..DANBOORU_POSTS.len() - 2],
                    )
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
