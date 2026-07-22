//! Provider profile registry and immutable HTTP session generations.

use crate::{CoreError, ErrorCode, NetworkConfig, ProviderProfileConfig};
use bytes::{Bytes, BytesMut};
use reqwest::{Client, StatusCode, header};
use secrecy::{ExposeSecret, SecretString};
use serde::Serialize;
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fmt,
    sync::{
        Arc, RwLock,
        atomic::{AtomicUsize, Ordering},
    },
    time::{Duration, Instant},
};
use tokio::{
    io::AsyncWriteExt,
    sync::{Mutex, Semaphore},
};
use tokio_util::sync::CancellationToken;
use url::Url;

const REDIRECT_DENIED: &str = "fvcore_redirect_denied";
const EH_PUBLIC_HOST: &str = "e-hentai.org";
const EH_PUBLIC_API_HOST: &str = "api.e-hentai.org";

pub(crate) enum ApiAuth {
    None,
    Basic,
    GelbooruQuery,
}

/// Stable Provider profile identity.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, serde::Deserialize, Serialize)]
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
    /// Whether an API user and key were loaded for this generation.
    pub has_api_credentials: bool,
    /// Maximum concurrent requests for this generation.
    pub max_concurrent_requests: usize,
    /// Minimum delay between request starts, in milliseconds.
    pub min_request_interval_ms: u64,
    /// Requests currently holding a concurrency permit.
    pub active_requests: usize,
    /// Requests waiting for a concurrency permit.
    pub queued_requests: usize,
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

pub(crate) struct DownloadResponse {
    pub(crate) bytes_done: u64,
    pub(crate) bytes_total: Option<u64>,
    pub(crate) resumed: bool,
    pub(crate) accept_ranges: bool,
    pub(crate) etag: Option<String>,
    pub(crate) last_modified: Option<String>,
}

pub(crate) struct DownloadRequest<'a> {
    pub(crate) url: &'a Url,
    pub(crate) referer: &'a Url,
    pub(crate) offset: u64,
    pub(crate) path: &'a std::path::Path,
}

struct SessionGeneration {
    key: ProfileKey,
    number: u64,
    config: ProviderProfileConfig,
    network: NetworkConfig,
    client: Client,
    allowed_hosts: HashSet<String>,
    cookie: Option<SecretString>,
    api_user: Option<SecretString>,
    api_key: Option<SecretString>,
    concurrency: Semaphore,
    queued_requests: AtomicUsize,
    rate_limit: Mutex<Option<Instant>>,
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
        let cookie = load_secret(config.cookie_env.as_deref(), "Cookie")?;
        let api_user = load_secret(config.api_user_env.as_deref(), "API user")?;
        let api_key = load_secret(config.api_key_env.as_deref(), "API key")?;
        let mut state = self.state.write().map_err(lock_error)?;
        let generation = state.next_generations.get(&key).copied().unwrap_or(1);
        let session = Arc::new(SessionGeneration::new(
            key.clone(),
            generation,
            config,
            network,
            cookie,
            api_user,
            api_key,
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
        let session = self.session(key)?;
        session.get(relative_path, cancellation).await
    }

    pub(crate) async fn get_with_query(
        &self,
        key: &ProfileKey,
        relative_path: &str,
        query: &[(String, String)],
        auth: ApiAuth,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        let session = self.session(key)?;
        session
            .get_with_query(relative_path, query, auth, cancellation)
            .await
    }

    pub(crate) async fn get_absolute<F>(
        &self,
        key: &ProfileKey,
        url: &Url,
        referer: Option<&Url>,
        max_bytes: usize,
        cancellation: CancellationToken,
        progress: F,
    ) -> Result<NetworkResponse, CoreError>
    where
        F: FnMut(usize, Option<u64>) + Send,
    {
        let session = self.session(key)?;
        session
            .get_absolute(url, referer, max_bytes, cancellation, progress)
            .await
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

    pub(crate) async fn get_pixiv_ajax(
        &self,
        key: &ProfileKey,
        relative_path: &str,
        query: &[(String, String)],
        referer_path: &str,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        let session = self.session(key)?;
        session
            .get_pixiv_ajax(relative_path, query, referer_path, cancellation)
            .await
    }

    pub(crate) async fn post_eh_api(
        &self,
        key: &ProfileKey,
        payload: &serde_json::Value,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        let session = self.session(key)?;
        session.post_eh_api(payload, cancellation).await
    }

    pub(crate) async fn post_eh_archive(
        &self,
        key: &ProfileKey,
        path: &str,
        form_body: &str,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        self.session(key)?
            .post_eh_archive(path, form_body, cancellation)
            .await
    }

    pub(crate) async fn download_to<F>(
        &self,
        key: &ProfileKey,
        request: DownloadRequest<'_>,
        cancellation: CancellationToken,
        progress: F,
    ) -> Result<DownloadResponse, CoreError>
    where
        F: FnMut(u64, Option<u64>) + Send,
    {
        self.session(key)?
            .download_to(request, cancellation, progress)
            .await
    }

    fn session(&self, key: &ProfileKey) -> Result<Arc<SessionGeneration>, CoreError> {
        let state = self.state.read().map_err(lock_error)?;
        state.sessions.get(key).cloned().ok_or_else(|| {
            CoreError::new(
                ErrorCode::ProfileNotFound,
                format!("Provider profile {key} was not found"),
                false,
            )
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
        api_user: Option<SecretString>,
        api_key: Option<SecretString>,
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
        if config.provider == "eh" && base_host.eq_ignore_ascii_case(EH_PUBLIC_HOST) {
            allowed_hosts.insert(EH_PUBLIC_API_HOST.to_owned());
        }
        let redirect_hosts = allowed_hosts.clone();
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
                    .is_some_and(|host| redirect_hosts.contains(&host.to_ascii_lowercase()));
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
        let max_concurrent_requests = config.max_concurrent_requests;
        Ok(Self {
            key,
            number,
            config,
            network,
            client,
            allowed_hosts,
            cookie,
            api_user,
            api_key,
            concurrency: Semaphore::new(max_concurrent_requests),
            queued_requests: AtomicUsize::new(0),
            rate_limit: Mutex::new(None),
        })
    }

    fn snapshot(&self) -> ProfileSnapshot {
        ProfileSnapshot {
            key: self.key.clone(),
            generation: self.number,
            base_url: self.config.base_url.to_string(),
            has_cookie: self.cookie.is_some(),
            has_api_credentials: self.api_user.is_some() && self.api_key.is_some(),
            max_concurrent_requests: self.config.max_concurrent_requests,
            min_request_interval_ms: self.config.min_request_interval_ms,
            active_requests: self
                .config
                .max_concurrent_requests
                .saturating_sub(self.concurrency.available_permits()),
            queued_requests: self.queued_requests.load(Ordering::Relaxed),
        }
    }

    async fn get(
        &self,
        relative_path: &str,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        self.get_with_query(relative_path, &[], ApiAuth::None, cancellation)
            .await
    }

    async fn get_with_query(
        &self,
        relative_path: &str,
        query: &[(String, String)],
        auth: ApiAuth,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        let url = safe_join(&self.config.base_url, relative_path)?;
        let mut request = self.client.get(url).query(query);
        match auth {
            ApiAuth::None => {}
            ApiAuth::Basic => {
                if let (Some(user), Some(key)) = (&self.api_user, &self.api_key) {
                    request = request.basic_auth(user.expose_secret(), Some(key.expose_secret()));
                }
            }
            ApiAuth::GelbooruQuery => {
                if let (Some(user), Some(key)) = (&self.api_user, &self.api_key) {
                    request = request.query(&[
                        ("user_id", user.expose_secret()),
                        ("api_key", key.expose_secret()),
                    ]);
                }
            }
        }
        if let Some(cookie) = &self.cookie {
            request = request.header(header::COOKIE, cookie.expose_secret());
        }
        self.execute(
            request,
            self.network.max_response_bytes,
            cancellation,
            |_, _| {},
        )
        .await
    }

    async fn get_pixiv_ajax(
        &self,
        relative_path: &str,
        query: &[(String, String)],
        referer_path: &str,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        let url = safe_join(&self.config.base_url, relative_path)?;
        let referer = safe_join(&self.config.base_url, referer_path)?;
        let mut request = self
            .client
            .get(url)
            .query(query)
            .header(header::ACCEPT, "application/json, text/plain, */*")
            .header("x-requested-with", "XMLHttpRequest")
            .header(header::REFERER, referer.as_str());
        if let Some(cookie) = &self.cookie {
            let exposed = cookie.expose_secret();
            request = request.header(header::COOKIE, exposed);
            if let Some(user_id) = pixiv_user_id(exposed) {
                request = request.header("x-user-id", user_id);
            }
        }
        self.execute(
            request,
            self.network.max_response_bytes,
            cancellation,
            |_, _| {},
        )
        .await
    }

    async fn get_absolute<F>(
        &self,
        url: &Url,
        referer: Option<&Url>,
        max_bytes: usize,
        cancellation: CancellationToken,
        progress: F,
    ) -> Result<NetworkResponse, CoreError>
    where
        F: FnMut(usize, Option<u64>) + Send,
    {
        self.validate_absolute(url, referer)?;
        let mut request = self.client.get(url.clone());
        if let Some(referer) = referer {
            request = request.header(header::REFERER, referer.as_str());
        }
        if url.host_str() == self.config.base_url.host_str() {
            if let Some(cookie) = &self.cookie {
                request = request.header(header::COOKIE, cookie.expose_secret());
            }
        }
        self.execute(request, max_bytes, cancellation, progress)
            .await
    }

    async fn post_eh_api(
        &self,
        payload: &serde_json::Value,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        if self.key.provider != "eh" {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "EH API requests require an EH profile",
                false,
            ));
        }
        let url = eh_api_url(&self.config.base_url)?;
        self.validate_absolute(&url, Some(&self.config.base_url))?;
        let mut request = self
            .client
            .post(url)
            .header(header::ACCEPT, "application/json")
            .header(header::REFERER, self.config.base_url.as_str())
            .json(payload);
        if let Some(cookie) = &self.cookie {
            request = request.header(header::COOKIE, cookie.expose_secret());
        }
        self.execute(
            request,
            self.network.max_response_bytes,
            cancellation,
            |_, _| {},
        )
        .await
    }

    async fn post_eh_archive(
        &self,
        path: &str,
        form_body: &str,
        cancellation: CancellationToken,
    ) -> Result<NetworkResponse, CoreError> {
        if self.key.provider != "eh" {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "EH Archive requests require an EH profile",
                false,
            ));
        }
        let url = safe_join(&self.config.base_url, path)?;
        let mut request = self
            .client
            .post(url)
            .header(header::CONTENT_TYPE, "application/x-www-form-urlencoded")
            .header(header::REFERER, self.config.base_url.as_str())
            .body(form_body.to_owned());
        if let Some(cookie) = &self.cookie {
            request = request.header(header::COOKIE, cookie.expose_secret());
        }
        self.execute(
            request,
            self.network.max_response_bytes,
            cancellation,
            |_, _| {},
        )
        .await
    }

    async fn download_to<F>(
        &self,
        request: DownloadRequest<'_>,
        cancellation: CancellationToken,
        mut progress: F,
    ) -> Result<DownloadResponse, CoreError>
    where
        F: FnMut(u64, Option<u64>) + Send,
    {
        let DownloadRequest {
            url,
            referer,
            offset,
            path,
        } = request;
        if self.key.provider != "eh"
            || !matches!(url.scheme(), "http" | "https")
            || !url.username().is_empty()
            || url.password().is_some()
            || referer.scheme() != self.config.base_url.scheme()
            || referer.host_str() != self.config.base_url.host_str()
        {
            return Err(CoreError::new(
                ErrorCode::AccessDenied,
                "EH Archive URL or Referer violated the trusted submission policy",
                false,
            ));
        }
        self.queued_requests.fetch_add(1, Ordering::Relaxed);
        let permit = tokio::select! {
            biased;
            () = cancellation.cancelled() => Err(cancelled()),
            permit = self.concurrency.acquire() => permit.map_err(|_| CoreError::new(
                ErrorCode::NotReady, "Provider session is shutting down", true)),
        };
        self.queued_requests.fetch_sub(1, Ordering::Relaxed);
        let permit = permit?;
        self.wait_for_rate_limit(&cancellation).await?;
        let mut request = self
            .client
            .get(url.clone())
            .header(header::REFERER, referer.as_str());
        if offset > 0 {
            request = request.header(header::RANGE, format!("bytes={offset}-"));
        }
        if url.host_str() == self.config.base_url.host_str() {
            if let Some(cookie) = &self.cookie {
                request = request.header(header::COOKIE, cookie.expose_secret());
            }
        }
        let mut response = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(cancelled()),
            response = request.send() => response.map_err(map_transport_error)?,
        };
        let status = response.status();
        map_status(status)?;
        let resumed = offset > 0 && status == StatusCode::PARTIAL_CONTENT;
        let start = if resumed { offset } else { 0 };
        let total = response
            .content_length()
            .map(|length| length.saturating_add(start));
        let accept_ranges = response
            .headers()
            .get(header::ACCEPT_RANGES)
            .and_then(|value| value.to_str().ok())
            .is_some_and(|value| value.eq_ignore_ascii_case("bytes"))
            || resumed;
        let etag = response
            .headers()
            .get(header::ETAG)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        let last_modified = response
            .headers()
            .get(header::LAST_MODIFIED)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        let mut options = tokio::fs::OpenOptions::new();
        options.create(true).write(true);
        if resumed {
            options.append(true);
        } else {
            options.truncate(true);
        }
        let mut file = options.open(path).await.map_err(|error| {
            CoreError::new(
                ErrorCode::Io,
                format!(
                    "failed to open Archive part file {}: {error}",
                    path.display()
                ),
                false,
            )
        })?;
        let mut done = start;
        progress(done, total);
        while let Some(chunk) = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(cancelled()),
            chunk = response.chunk() => chunk.map_err(map_transport_error)?,
        } {
            file.write_all(&chunk).await.map_err(|error| {
                CoreError::new(
                    ErrorCode::Io,
                    format!(
                        "failed to write Archive part file {}: {error}",
                        path.display()
                    ),
                    false,
                )
            })?;
            done = done.saturating_add(chunk.len() as u64);
            progress(done, total);
        }
        file.flush().await.map_err(|error| {
            CoreError::new(
                ErrorCode::Io,
                format!(
                    "failed to flush Archive part file {}: {error}",
                    path.display()
                ),
                false,
            )
        })?;
        drop(permit);
        Ok(DownloadResponse {
            bytes_done: done,
            bytes_total: total,
            resumed,
            accept_ranges,
            etag,
            last_modified,
        })
    }

    fn validate_absolute(&self, url: &Url, referer: Option<&Url>) -> Result<(), CoreError> {
        if url.scheme() != self.config.base_url.scheme()
            || !url
                .host_str()
                .is_some_and(|host| self.allowed_hosts.contains(&host.to_ascii_lowercase()))
            || !url.username().is_empty()
            || url.password().is_some()
        {
            return Err(CoreError::new(
                ErrorCode::AccessDenied,
                "URL is outside the Provider profile's allowed origin policy",
                false,
            ));
        }
        if referer.is_some_and(|value| {
            value.scheme() != self.config.base_url.scheme()
                || value.host_str() != self.config.base_url.host_str()
        }) {
            return Err(CoreError::new(
                ErrorCode::AccessDenied,
                "Referer is outside the Provider profile origin",
                false,
            ));
        }
        Ok(())
    }

    async fn execute<F>(
        &self,
        request: reqwest::RequestBuilder,
        max_bytes: usize,
        cancellation: CancellationToken,
        mut progress: F,
    ) -> Result<NetworkResponse, CoreError>
    where
        F: FnMut(usize, Option<u64>) + Send,
    {
        self.queued_requests.fetch_add(1, Ordering::Relaxed);
        let permit = tokio::select! {
            biased;
            () = cancellation.cancelled() => Err(cancelled()),
            permit = self.concurrency.acquire() => permit.map_err(|_| CoreError::new(
                    ErrorCode::NotReady,
                    "Provider session is shutting down",
                    true,
                )),
        };
        self.queued_requests.fetch_sub(1, Ordering::Relaxed);
        let permit = permit?;
        self.wait_for_rate_limit(&cancellation).await?;
        let response = tokio::select! {
            biased;
            () = cancellation.cancelled() => return Err(cancelled()),
            response = request.send() => response.map_err(map_transport_error)?,
        };
        let status = response.status();
        map_status(status)?;
        if response
            .content_length()
            .is_some_and(|length| length > max_bytes as u64)
        {
            return Err(response_too_large(max_bytes));
        }
        let final_url = response.url().clone();
        let content_type = response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        let mut response = response;
        let mut body = BytesMut::new();
        let total = response.content_length();
        progress(0, total);
        loop {
            let chunk = tokio::select! {
                biased;
                () = cancellation.cancelled() => return Err(cancelled()),
                chunk = response.chunk() => chunk.map_err(map_transport_error)?,
            };
            let Some(chunk) = chunk else {
                break;
            };
            if body.len().saturating_add(chunk.len()) > max_bytes {
                return Err(response_too_large(max_bytes));
            }
            body.extend_from_slice(&chunk);
            progress(body.len(), total);
        }
        let result = NetworkResponse {
            profile: self.key.clone(),
            generation: self.number,
            status: status.as_u16(),
            final_url,
            body: body.freeze(),
            content_type,
        };
        drop(permit);
        Ok(result)
    }

    async fn wait_for_rate_limit(&self, cancellation: &CancellationToken) -> Result<(), CoreError> {
        let interval = Duration::from_millis(self.config.min_request_interval_ms);
        if interval.is_zero() {
            return Ok(());
        }
        let mut next_start = self.rate_limit.lock().await;
        let now = Instant::now();
        if let Some(allowed_at) = *next_start {
            if allowed_at > now {
                tokio::select! {
                    biased;
                    () = cancellation.cancelled() => return Err(cancelled()),
                    () = tokio::time::sleep_until(tokio::time::Instant::from_std(allowed_at)) => {}
                }
            }
        }
        *next_start = Some(Instant::now() + interval);
        Ok(())
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

fn eh_api_url(base: &Url) -> Result<Url, CoreError> {
    let mut url = safe_join(base, "api.php")?;
    if base.scheme() == "https"
        && base
            .host_str()
            .is_some_and(|host| host.eq_ignore_ascii_case(EH_PUBLIC_HOST))
    {
        url.set_host(Some(EH_PUBLIC_API_HOST)).map_err(|_| {
            CoreError::new(
                ErrorCode::InvalidConfig,
                "failed to construct the E-Hentai API URL",
                false,
            )
        })?;
        url.set_path("/api.php");
        url.set_query(None);
        url.set_fragment(None);
    }
    Ok(url)
}

fn load_secret(variable: Option<&str>, label: &str) -> Result<Option<SecretString>, CoreError> {
    variable
        .map(|name| {
            std::env::var(name).map(SecretString::from).map_err(|_| {
                CoreError::new(
                    ErrorCode::InvalidConfig,
                    format!("required {label} environment variable {name} is not set"),
                    false,
                )
            })
        })
        .transpose()
}

fn pixiv_user_id(cookie: &str) -> Option<&str> {
    cookie.split(';').map(str::trim).find_map(|part| {
        let value = part.strip_prefix("PHPSESSID=")?;
        let end = value.find(['_', '%']).unwrap_or(value.len());
        let user_id = &value[..end];
        (!user_id.is_empty() && user_id.bytes().all(|byte| byte.is_ascii_digit()))
            .then_some(user_id)
    })
}

fn map_status(status: StatusCode) -> Result<(), CoreError> {
    let (code, retryable) = match status {
        StatusCode::BAD_REQUEST | StatusCode::UNPROCESSABLE_ENTITY => {
            (ErrorCode::InvalidInput, false)
        }
        StatusCode::UNAUTHORIZED => (ErrorCode::AuthenticationRequired, false),
        StatusCode::FORBIDDEN => (ErrorCode::AccessDenied, false),
        StatusCode::NOT_FOUND => (ErrorCode::ResourceNotFound, false),
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
    use super::{EH_PUBLIC_API_HOST, ProfileKey, SessionRegistry, eh_api_url};
    use crate::{ErrorCode, NetworkConfig, ProviderProfileConfig};
    use axum::{Router, http::StatusCode, response::Redirect, routing::get};
    use std::{
        collections::BTreeMap,
        sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        },
        time::{Duration, Instant},
    };
    use tokio::net::TcpListener;
    use tokio_util::sync::CancellationToken;
    use url::Url;

    #[test]
    fn extracts_pixiv_user_id_without_exposing_the_cookie() {
        assert_eq!(
            super::pixiv_user_id("foo=bar; PHPSESSID=12345_abcd; x=y"),
            Some("12345")
        );
        assert_eq!(
            super::pixiv_user_id("PHPSESSID=12345%5Ftoken"),
            Some("12345")
        );
        assert_eq!(super::pixiv_user_id("PHPSESSID=invalid"), None);
    }

    #[test]
    fn selects_the_dedicated_public_eh_image_api_origin() {
        assert_eq!(
            eh_api_url(&Url::parse("https://e-hentai.org/").unwrap())
                .unwrap()
                .as_str(),
            "https://api.e-hentai.org/api.php"
        );
        assert_eq!(
            eh_api_url(&Url::parse("https://exhentai.org/").unwrap())
                .unwrap()
                .as_str(),
            "https://exhentai.org/api.php"
        );
        assert_eq!(
            eh_api_url(&Url::parse("http://127.0.0.1:8080/").unwrap())
                .unwrap()
                .as_str(),
            "http://127.0.0.1:8080/api.php"
        );
    }

    #[test]
    fn public_eh_profile_allows_its_dedicated_api_host() {
        let profile = ProviderProfileConfig {
            provider: "eh".to_owned(),
            base_url: Url::parse("https://e-hentai.org/").unwrap(),
            ..ProviderProfileConfig::default()
        };
        let profiles = BTreeMap::from([("eh/default".to_owned(), profile)]);
        let registry = SessionRegistry::new(&profiles, &NetworkConfig::default()).unwrap();
        let session = registry.session(&ProfileKey::new("eh", "default")).unwrap();

        assert!(session.allowed_hosts.contains(EH_PUBLIC_API_HOST));
    }

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

    #[tokio::test]
    async fn limits_concurrency_and_request_start_rate() {
        let active = Arc::new(AtomicUsize::new(0));
        let maximum = Arc::new(AtomicUsize::new(0));
        let router = Router::new().route(
            "/slow",
            get({
                let active = active.clone();
                let maximum = maximum.clone();
                move || {
                    let active = active.clone();
                    let maximum = maximum.clone();
                    async move {
                        let current = active.fetch_add(1, Ordering::SeqCst) + 1;
                        maximum.fetch_max(current, Ordering::SeqCst);
                        tokio::time::sleep(Duration::from_millis(20)).await;
                        active.fetch_sub(1, Ordering::SeqCst);
                        "ok"
                    }
                }
            }),
        );
        let listen = server(router).await;
        let mut profile = profile(listen);
        profile.max_concurrent_requests = 1;
        profile.min_request_interval_ms = 30;
        let registry = Arc::new(registry(profile, NetworkConfig::default()));
        let key = ProfileKey::new("test", "default");
        let started = Instant::now();
        let first = tokio::spawn({
            let registry = registry.clone();
            let key = key.clone();
            async move { registry.get(&key, "slow", CancellationToken::new()).await }
        });
        let second = tokio::spawn({
            let registry = registry.clone();
            let key = key.clone();
            async move { registry.get(&key, "slow", CancellationToken::new()).await }
        });
        first.await.unwrap().unwrap();
        second.await.unwrap().unwrap();
        assert_eq!(maximum.load(Ordering::SeqCst), 1);
        assert!(started.elapsed() >= Duration::from_millis(50));
    }

    #[tokio::test]
    async fn queued_request_can_be_cancelled() {
        let listen = server(Router::new().route(
            "/slow",
            get(|| async {
                tokio::time::sleep(Duration::from_millis(100)).await;
                "ok"
            }),
        ))
        .await;
        let mut profile = profile(listen);
        profile.max_concurrent_requests = 1;
        let registry = Arc::new(registry(profile, NetworkConfig::default()));
        let key = ProfileKey::new("test", "default");
        let first = tokio::spawn({
            let registry = registry.clone();
            let key = key.clone();
            async move { registry.get(&key, "slow", CancellationToken::new()).await }
        });
        tokio::time::sleep(Duration::from_millis(10)).await;
        let cancellation = CancellationToken::new();
        let second = tokio::spawn({
            let registry = registry.clone();
            let key = key.clone();
            let cancellation = cancellation.clone();
            async move { registry.get(&key, "slow", cancellation).await }
        });
        tokio::time::sleep(Duration::from_millis(10)).await;
        cancellation.cancel();
        assert_eq!(
            second.await.unwrap().unwrap_err().code(),
            ErrorCode::Cancelled
        );
        first.await.unwrap().unwrap();
    }
}
