//! Provider profile registry and immutable HTTP session generations.

use crate::{CoreError, ErrorCode, NetworkConfig, ProviderProfileConfig};
use bytes::{Bytes, BytesMut};
use reqwest::{Client, StatusCode, header};
use secrecy::{ExposeSecret, SecretString};
use serde::Serialize;
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fmt,
    sync::{Arc, RwLock},
    time::Duration,
};
use tokio_util::sync::CancellationToken;
use url::Url;

const REDIRECT_DENIED: &str = "fvcore_redirect_denied";

/// Stable Provider profile identity.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub struct ProfileKey {
    /// Provider implementation identifier.
    pub provider: String,
    /// User-defined profile name.
    pub profile: String,
}

impl ProfileKey {
    /// Constructs a Provider profile key.
    #[must_use]
    pub fn new(provider: impl Into<String>, profile: impl Into<String>) -> Self {
        Self {
            provider: provider.into(),
            profile: profile.into(),
        }
    }
}

impl fmt::Display for ProfileKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}/{}", self.provider, self.profile)
    }
}

/// Safe status of one immutable session generation.
#[derive(Clone, Debug, Serialize)]
pub struct ProfileSnapshot {
    /// Provider/profile identity.
    pub key: ProfileKey,
    /// Monotonically increasing generation within this profile.
    pub generation: u64,
    /// Configured API origin without credentials.
    pub base_url: String,
    /// Whether a Cookie secret was loaded for this generation.
    pub has_cookie: bool,
}

/// Safe result of probing one configured Provider origin.
#[derive(Clone, Debug, Serialize)]
pub struct ProfileProbeSnapshot {
    /// Provider profile used for the probe.
    pub key: ProfileKey,
    /// Immutable session generation used for the full response lifetime.
    pub generation: u64,
    /// Successful HTTP status code.
    pub status: u16,
    /// Number of buffered response bytes.
    pub response_bytes: usize,
    /// Optional response Content-Type.
    pub content_type: Option<String>,
}

/// Bounded in-memory HTTP response returned by a Provider session.
#[derive(Clone, Debug)]
pub(crate) struct NetworkResponse {
    /// Provider profile used for this request.
    pub(crate) profile: ProfileKey,
    /// Immutable session generation held for the full response body lifetime.
    pub(crate) generation: u64,
    /// Final HTTP status code.
    pub(crate) status: u16,
    /// Final URL after validated redirects.
    pub(crate) final_url: Url,
    /// Immutable response bytes.
    pub(crate) body: Bytes,
    /// Optional response Content-Type.
    pub(crate) content_type: Option<String>,
}

struct SessionGeneration {
    key: ProfileKey,
    number: u64,
    config: ProviderProfileConfig,
    network: NetworkConfig,
    client: Client,
    cookie: Option<SecretString>,
}

struct RegistryState {
    sessions: HashMap<ProfileKey, Arc<SessionGeneration>>,
    next_generations: HashMap<ProfileKey, u64>,
}

/// Thread-safe registry that swaps immutable generations without interrupting in-flight requests.
pub(crate) struct SessionRegistry {
    state: RwLock<RegistryState>,
}

impl SessionRegistry {
    pub(crate) fn new(
        profiles: &BTreeMap<String, ProviderProfileConfig>,
        network: &NetworkConfig,
    ) -> Result<Self, CoreError> {
        let registry = Self {
            state: RwLock::new(RegistryState {
                sessions: HashMap::new(),
                next_generations: HashMap::new(),
            }),
        };
        for profile in profiles.values() {
            registry.replace(profile.clone(), network.clone())?;
        }
        Ok(registry)
    }

    pub(crate) fn replace(
        &self,
        config: ProviderProfileConfig,
        network: NetworkConfig,
    ) -> Result<ProfileSnapshot, CoreError> {
        let key = ProfileKey::new(config.provider.clone(), config.profile.clone());
        config.validate(&key.to_string())?;
        let cookie = load_cookie(config.cookie_env.as_deref())?;
        let mut state = self.state.write().map_err(lock_error)?;
        let generation = state.next_generations.get(&key).copied().unwrap_or(1);
        let session = Arc::new(SessionGeneration::new(
            key.clone(),
            generation,
            config,
            network,
            cookie,
        )?);
        state.sessions.insert(key.clone(), session.clone());
        state.next_generations.insert(key, generation + 1);
        Ok(session.snapshot())
    }

    pub(crate) fn snapshots(&self) -> Result<Vec<ProfileSnapshot>, CoreError> {
        let state = self.state.read().map_err(lock_error)?;
        let mut snapshots: Vec<_> = state
            .sessions
            .values()
            .map(|session| session.snapshot())
            .collect();
        snapshots.sort_by(|left, right| left.key.cmp(&right.key));
        Ok(snapshots)
    }

    pub(crate) async fn get(
        &self,
        key: &ProfileKey,
        relative_path: &str,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        let session = {
            let state = self.state.read().map_err(lock_error)?;
            state.sessions.get(key).cloned()
        }
        .ok_or_else(|| {
            CoreError::new(
                ErrorCode::ProfileNotFound,
                format!("Provider profile {key} was not found"),
                false,
            )
        })?;
        session.get(relative_path, cancellation).await
    }

    pub(crate) async fn probe(
        &self,
        key: &ProfileKey,
        cancellation: CancellationToken,
    ) -> Result<ProfileProbeSnapshot, CoreError> {
        let response = self.get(key, "", cancellation).await?;
        debug_assert_eq!(response.profile, *key);
        debug_assert!(response.final_url.has_host());
        Ok(ProfileProbeSnapshot {
            key: response.profile,
            generation: response.generation,
            status: response.status,
            response_bytes: response.body.len(),
            content_type: response.content_type,
        })
    }
}

impl SessionGeneration {
    fn new(
        key: ProfileKey,
        number: u64,
        config: ProviderProfileConfig,
        network: NetworkConfig,
        cookie: Option<SecretString>,
    ) -> Result<Self, CoreError> {
        let base_host = config.base_url.host_str().ok_or_else(|| {
            CoreError::new(
                ErrorCode::InvalidConfig,
                "profile base URL has no host",
                false,
            )
        })?;
        let mut allowed_hosts: HashSet<String> = config
            .allowed_redirect_hosts
            .iter()
            .map(|host| host.to_ascii_lowercase())
            .collect();
        allowed_hosts.insert(base_host.to_ascii_lowercase());
        let base_scheme = config.base_url.scheme().to_owned();
        let redirect_limit = network.max_redirects;
        let mut client_builder = Client::builder()
            .connect_timeout(Duration::from_secs(network.connect_timeout_seconds))
            .timeout(Duration::from_secs(network.request_timeout_seconds))
            .user_agent(config.user_agent.clone())
            .redirect(reqwest::redirect::Policy::custom(move |attempt| {
                if attempt.previous().len() >= redirect_limit {
                    return attempt.error("fvcore_redirect_limit");
                }
                let allowed = attempt
                    .url()
                    .host_str()
                    .is_some_and(|host| allowed_hosts.contains(&host.to_ascii_lowercase()));
                if allowed && attempt.url().scheme() == base_scheme {
                    attempt.follow()
                } else {
                    attempt.error(REDIRECT_DENIED)
                }
            }));
        if let Some(proxy_url) = &network.proxy_url {
            let proxy = reqwest::Proxy::all(proxy_url.as_str()).map_err(|error| {
                CoreError::new(
                    ErrorCode::InvalidConfig,
                    format!("failed to configure HTTP proxy: {error}"),
                    false,
                )
            })?;
            client_builder = client_builder.proxy(proxy);
        }
        let client = client_builder.build().map_err(|error| {
            CoreError::new(
                ErrorCode::InvalidConfig,
                format!("failed to build HTTP client for {key}: {error}"),
                false,
            )
        })?;
        Ok(Self {
            key,
            number,
            config,
            network,
            client,
            cookie,
        })
    }

    fn snapshot(&self) -> ProfileSnapshot {
        ProfileSnapshot {
            key: self.key.clone(),
            generation: self.number,
            base_url: self.config.base_url.to_string(),
            has_cookie: self.cookie.is_some(),
        }
    }

    async fn get(
        &self,
        relative_path: &str,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        let url = safe_join(&self.config.base_url, relative_path)?;
        let mut request = self.client.get(url);
        if let Some(cookie) = &self.cookie {
            request = request.header(header::COOKIE, cookie.expose_secret());
        }
        let response = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(cancelled()),
            response = request.send() => response.map_err(map_transport_error)?,
        };
        let status = response.status();
        map_status(status)?;
        if response
            .content_length()
            .is_some_and(|length| length > self.network.max_response_bytes as u64)
        {
            return Err(response_too_large(self.network.max_response_bytes));
        }
        let final_url = response.url().clone();
        let content_type = response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        let mut response = response;
        let mut body = BytesMut::new();
        loop {
            let chunk = tokio::select! {
                biased;
                () = cancellation.cancelled() => return Err(cancelled()),
                chunk = response.chunk() => chunk.map_err(map_transport_error)?,
            };
            let Some(chunk) = chunk else {
                break;
            };
            if body.len().saturating_add(chunk.len()) > self.network.max_response_bytes {
                return Err(response_too_large(self.network.max_response_bytes));
            }
            body.extend_from_slice(&chunk);
        }
        Ok(NetworkResponse {
            profile: self.key.clone(),
            generation: self.number,
            status: status.as_u16(),
            final_url,
            body: body.freeze(),
            content_type,
        })
    }
}

fn safe_join(base: &Url, relative_path: &str) -> Result<Url, CoreError> {
    if relative_path.starts_with("//") || Url::parse(relative_path).is_ok() {
        return Err(CoreError::new(
            ErrorCode::InvalidInput,
            "network request path must be relative to the Provider profile",
            false,
        ));
    }
    let url = base.join(relative_path).map_err(|_| {
        CoreError::new(
            ErrorCode::InvalidInput,
            "network request path is invalid",
            false,
        )
    })?;
    if url.host_str() != base.host_str() || url.scheme() != base.scheme() {
        return Err(CoreError::new(
            ErrorCode::InvalidInput,
            "network request path escaped the Provider origin",
            false,
        ));
    }
    Ok(url)
}

fn load_cookie(variable: Option<&str>) -> Result<Option<SecretString>, CoreError> {
    variable
        .map(|name| {
            std::env::var(name).map(SecretString::from).map_err(|_| {
                CoreError::new(
                    ErrorCode::InvalidConfig,
                    format!("required Cookie environment variable {name} is not set"),
                    false,
                )
            })
        })
        .transpose()
}

fn map_status(status: StatusCode) -> Result<(), CoreError> {
    let (code, retryable) = match status {
        StatusCode::UNAUTHORIZED => (ErrorCode::AuthenticationRequired, false),
        StatusCode::FORBIDDEN => (ErrorCode::AccessDenied, false),
        StatusCode::TOO_MANY_REQUESTS => (ErrorCode::RateLimited, true),
        status if status.is_server_error() => (ErrorCode::UnexpectedResponse, true),
        status if !status.is_success() => (ErrorCode::UnexpectedResponse, false),
        _ => return Ok(()),
    };
    Err(CoreError::new(
        code,
        format!("Provider returned HTTP status {}", status.as_u16()),
        retryable,
    ))
}

fn map_transport_error(error: reqwest::Error) -> CoreError {
    if error.is_redirect() || error.to_string().contains(REDIRECT_DENIED) {
        return CoreError::new(
            ErrorCode::RedirectDenied,
            "Provider redirect target is not allowed",
            false,
        );
    }
    if error.is_timeout() {
        return CoreError::new(
            ErrorCode::DeadlineExceeded,
            "network request deadline exceeded",
            true,
        );
    }
    CoreError::new(ErrorCode::Network, "network request failed", true)
}

fn response_too_large(limit: usize) -> CoreError {
    CoreError::new(
        ErrorCode::ResponseTooLarge,
        format!("network response exceeds the configured {limit} byte limit"),
        false,
    )
}

fn cancelled() -> CoreError {
    CoreError::new(ErrorCode::Cancelled, "network request was cancelled", false)
}

fn lock_error<T>(_: std::sync::PoisonError<T>) -> CoreError {
    CoreError::new(
        ErrorCode::Internal,
        "Provider session registry lock is poisoned",
        false,
    )
}

#[cfg(test)]
mod tests {
    use super::{ProfileKey, SessionRegistry};
    use crate::{ErrorCode, NetworkConfig, ProviderProfileConfig};
    use axum::{Router, http::StatusCode, response::Redirect, routing::get};
    use std::{collections::BTreeMap, sync::Arc, time::Duration};
    use tokio::net::TcpListener;
    use tokio_util::sync::CancellationToken;
    use url::Url;

    async fn server(router: Router) -> std::net::SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let listen = listener.local_addr().unwrap();
        tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
        listen
    }

    fn profile(listen: std::net::SocketAddr) -> ProviderProfileConfig {
        ProviderProfileConfig {
            provider: "test".to_owned(),
            profile: "default".to_owned(),
            base_url: Url::parse(&format!("http://{listen}/")).unwrap(),
            ..ProviderProfileConfig::default()
        }
    }

    fn registry(profile: ProviderProfileConfig, network: NetworkConfig) -> SessionRegistry {
        let profiles = BTreeMap::from([("test/default".to_owned(), profile)]);
        SessionRegistry::new(&profiles, &network).unwrap()
    }

    #[tokio::test]
    async fn enforces_response_limit_and_cancellation() {
        let listen = server(
            Router::new()
                .route("/large", get(|| async { "0123456789abcdef" }))
                .route(
                    "/slow",
                    get(|| async {
                        tokio::time::sleep(Duration::from_secs(5)).await;
                        "late"
                    }),
                ),
        )
        .await;
        let network = NetworkConfig {
            max_response_bytes: 8,
            ..NetworkConfig::default()
        };
        let registry = Arc::new(registry(profile(listen), network));
        let key = ProfileKey::new("test", "default");
        let error = registry
            .get(&key, "large", CancellationToken::new())
            .await
            .unwrap_err();
        assert_eq!(error.code(), ErrorCode::ResponseTooLarge);

        let cancellation = CancellationToken::new();
        let request = tokio::spawn({
            let registry = registry.clone();
            let key = key.clone();
            let cancellation = cancellation.clone();
            async move { registry.get(&key, "slow", cancellation).await }
        });
        tokio::time::sleep(Duration::from_millis(10)).await;
        cancellation.cancel();
        assert_eq!(
            request.await.unwrap().unwrap_err().code(),
            ErrorCode::Cancelled
        );
    }

    #[tokio::test]
    async fn rejects_cross_host_redirect() {
        let listen = server(Router::new().route(
            "/redirect",
            get(|| async { Redirect::temporary("http://localhost:9/denied") }),
        ))
        .await;
        let registry = registry(profile(listen), NetworkConfig::default());
        let error = registry
            .get(
                &ProfileKey::new("test", "default"),
                "redirect",
                CancellationToken::new(),
            )
            .await
            .unwrap_err();
        assert_eq!(error.code(), ErrorCode::RedirectDenied);
    }

    #[tokio::test]
    async fn maps_stable_http_errors() {
        let listen = server(Router::new().route(
            "/limited",
            get(|| async { (StatusCode::TOO_MANY_REQUESTS, "slow down") }),
        ))
        .await;
        let registry = registry(profile(listen), NetworkConfig::default());
        let error = registry
            .get(
                &ProfileKey::new("test", "default"),
                "limited",
                CancellationToken::new(),
            )
            .await
            .unwrap_err();
        assert_eq!(error.code(), ErrorCode::RateLimited);
        assert!(error.retryable());
    }

    #[tokio::test]
    async fn in_flight_request_keeps_old_generation() {
        let old_listen = server(Router::new().route(
            "/value",
            get(|| async {
                tokio::time::sleep(Duration::from_millis(50)).await;
                "old"
            }),
        ))
        .await;
        let new_listen = server(Router::new().route("/value", get(|| async { "new" }))).await;
        let registry = Arc::new(registry(profile(old_listen), NetworkConfig::default()));
        let key = ProfileKey::new("test", "default");
        let old_request = tokio::spawn({
            let registry = registry.clone();
            let key = key.clone();
            async move { registry.get(&key, "value", CancellationToken::new()).await }
        });
        tokio::time::sleep(Duration::from_millis(10)).await;
        let replacement = registry
            .replace(profile(new_listen), NetworkConfig::default())
            .unwrap();
        assert_eq!(replacement.generation, 2);
        let new_response = registry
            .get(&key, "value", CancellationToken::new())
            .await
            .unwrap();
        let old_response = old_request.await.unwrap().unwrap();
        assert_eq!(old_response.generation, 1);
        assert_eq!(old_response.body, "old");
        assert_eq!(new_response.generation, 2);
        assert_eq!(new_response.body, "new");
    }
}
