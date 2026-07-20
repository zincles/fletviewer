//! Versioned configuration shared by embedded and executable modes.

use crate::{CoreError, ErrorCode};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, HashSet},
    net::SocketAddr,
    path::{Path, PathBuf},
};
use url::Url;

fn default_schema_version() -> u32 {
    1
}

fn default_command_capacity() -> usize {
    256
}

fn default_shutdown_seconds() -> u64 {
    15
}

fn default_control_listen() -> SocketAddr {
    SocketAddr::from(([127, 0, 0, 1], 8787))
}

fn default_profile_concurrency() -> usize {
    4
}

fn default_max_image_bytes() -> usize {
    32 * 1024 * 1024
}

fn default_memory_cache_bytes() -> usize {
    128 * 1024 * 1024
}

fn default_inflight_image_bytes() -> usize {
    128 * 1024 * 1024
}

fn default_cache_write_queue() -> usize {
    64
}

fn default_profiles() -> BTreeMap<String, ProviderProfileConfig> {
    [
        ("eh", "https://e-hentai.org/", Vec::new()),
        (
            "pixiv",
            "https://www.pixiv.net/",
            vec!["i.pximg.net".to_owned()],
        ),
        (
            "danbooru",
            "https://danbooru.donmai.us/",
            vec!["cdn.donmai.us".to_owned()],
        ),
        (
            "gelbooru",
            "https://gelbooru.com/",
            (1..=4)
                .map(|index| format!("img{index}.gelbooru.com"))
                .collect(),
        ),
    ]
    .into_iter()
    .map(|(provider, base_url, allowed_redirect_hosts)| {
        (
            provider.to_owned(),
            ProviderProfileConfig {
                provider: provider.to_owned(),
                base_url: Url::parse(base_url).expect("default Provider URL is valid"),
                allowed_redirect_hosts,
                ..ProviderProfileConfig::default()
            },
        )
    })
    .collect()
}

/// Complete configuration accepted by [`crate::CoreBuilder`].
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct CoreConfig {
    /// Configuration schema version. Defaults to `1`.
    pub schema_version: u32,
    /// Human-readable instance name shown in diagnostics. Defaults to `"fvcore"`.
    pub instance_name: String,
    /// Maximum number of commands waiting for the Runtime. Defaults to `256`.
    pub command_capacity: usize,
    /// Graceful shutdown deadline in seconds. Defaults to `15`.
    pub shutdown_seconds: u64,
    /// Integrated HTTP control-plane settings. Defaults to [`ControlConfig::default`].
    pub control: ControlConfig,
    /// Persistent and disposable storage domains. Defaults to [`StorageConfig::default`].
    pub storage: StorageConfig,
    /// Long-running operation limits. Defaults to [`OperationConfig::default`].
    pub operations: OperationConfig,
    /// Runtime event retention settings. Defaults to [`EventConfig::default`].
    pub events: EventConfig,
    /// Shared network limits. Defaults to [`NetworkConfig::default`].
    pub network: NetworkConfig,
    /// Image fetch and cache limits. Defaults to [`ImageConfig::default`].
    pub images: ImageConfig,
    /// Configured Provider profiles. Defaults to EH, Pixiv, Danbooru and Gelbooru.
    pub profiles: BTreeMap<String, ProviderProfileConfig>,
}

impl Default for CoreConfig {
    fn default() -> Self {
        Self {
            schema_version: default_schema_version(),
            instance_name: "fvcore".to_owned(),
            command_capacity: default_command_capacity(),
            shutdown_seconds: default_shutdown_seconds(),
            control: ControlConfig::default(),
            storage: StorageConfig::default(),
            operations: OperationConfig::default(),
            events: EventConfig::default(),
            network: NetworkConfig::default(),
            images: ImageConfig::default(),
            profiles: default_profiles(),
        }
    }
}

impl CoreConfig {
    /// Parses strict JSON configuration from a UTF-8 string.
    pub fn from_json(input: &str) -> Result<Self, CoreError> {
        serde_json::from_str(input).map_err(|error| {
            CoreError::new(
                ErrorCode::Parse,
                format!("failed to parse JSON configuration: {error}"),
                false,
            )
        })
    }

    /// Reads and parses a strict JSON configuration file.
    pub fn from_json_file(path: &Path) -> Result<Self, CoreError> {
        let input = std::fs::read_to_string(path).map_err(|error| {
            CoreError::new(
                ErrorCode::Io,
                format!("failed to read configuration {}: {error}", path.display()),
                false,
            )
        })?;
        Self::from_json(&input)
    }

    /// Resolves relative storage domains against one stable configuration directory.
    pub fn resolve_storage_paths(&mut self, base: &Path) {
        for path in [
            &mut self.storage.data,
            &mut self.storage.cache,
            &mut self.storage.downloads,
            &mut self.storage.temp,
        ] {
            if path.is_relative() {
                *path = base.join(&*path);
            }
        }
    }

    /// Validates invariants before Runtime resources are allocated.
    pub fn validate(&self) -> Result<(), CoreError> {
        if self.schema_version != 1 {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                format!("unsupported schema_version {}", self.schema_version),
                false,
            ));
        }
        if self.instance_name.trim().is_empty() {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "instance_name must not be empty",
                false,
            ));
        }
        if self.command_capacity == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "command_capacity must be greater than zero",
                false,
            ));
        }
        if self.shutdown_seconds == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "shutdown_seconds must be greater than zero",
                false,
            ));
        }
        self.storage.validate()?;
        self.operations.validate()?;
        self.events.validate()?;
        self.network.validate()?;
        self.images.validate()?;
        let mut profile_keys = HashSet::new();
        for (key, profile) in &self.profiles {
            profile.validate(key)?;
            if !profile_keys.insert((&profile.provider, &profile.profile)) {
                return Err(CoreError::new(
                    ErrorCode::InvalidConfig,
                    format!(
                        "multiple configuration entries define profile {}/{}",
                        profile.provider, profile.profile
                    ),
                    false,
                ));
            }
        }
        Ok(())
    }
}

/// Hard limits for image fetching and the reconstructable content cache.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct ImageConfig {
    /// Maximum bytes accepted for one image. Defaults to 32 MiB.
    pub max_image_bytes: usize,
    /// Maximum bytes retained by the in-memory image cache. Defaults to 128 MiB.
    pub memory_cache_bytes: usize,
    /// Maximum bytes reserved by concurrent image transfers. Defaults to 128 MiB.
    pub max_inflight_bytes: usize,
    /// Maximum verified resources waiting for disk persistence. Defaults to `64`.
    pub cache_write_queue: usize,
}

impl Default for ImageConfig {
    fn default() -> Self {
        Self {
            max_image_bytes: default_max_image_bytes(),
            memory_cache_bytes: default_memory_cache_bytes(),
            max_inflight_bytes: default_inflight_image_bytes(),
            cache_write_queue: default_cache_write_queue(),
        }
    }
}

impl ImageConfig {
    fn validate(&self) -> Result<(), CoreError> {
        if self.max_image_bytes == 0
            || self.memory_cache_bytes == 0
            || self.max_inflight_bytes < self.max_image_bytes
            || self.cache_write_queue == 0
            || self.max_image_bytes > u32::MAX as usize
            || self.max_inflight_bytes > u32::MAX as usize
        {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "image limits must be nonzero, max_inflight_bytes must cover one image, and byte permits must fit in u32",
                false,
            ));
        }
        Ok(())
    }
}

/// Integrated HTTP control-plane configuration.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct ControlConfig {
    /// Whether the Runtime should listen for HTTP requests. Defaults to `false`.
    pub enabled: bool,
    /// Address used when HTTP listening is enabled. Defaults to `127.0.0.1:8787`.
    pub listen: SocketAddr,
    /// Whether the embedded diagnostic WebUI routes are available. Defaults to `true`.
    pub webui_enabled: bool,
}

impl Default for ControlConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            listen: default_control_listen(),
            webui_enabled: true,
        }
    }
}

/// Explicit paths for Core-owned storage domains.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct StorageConfig {
    /// Durable configuration, database, history and task state.
    /// Defaults to `FletViewer/Data`.
    pub data: PathBuf,
    /// Disposable and reconstructable content cache. Defaults to `FletViewer/Cache`.
    pub cache: PathBuf,
    /// Durable downloads and local gallery files. Defaults to `FletViewer/Downloads`.
    pub downloads: PathBuf,
    /// Disposable staging and diagnostic files. Defaults to `FletViewer/Temp`.
    pub temp: PathBuf,
}

impl Default for StorageConfig {
    fn default() -> Self {
        let root = PathBuf::from("FletViewer");
        Self {
            data: root.join("Data"),
            cache: root.join("Cache"),
            downloads: root.join("Downloads"),
            temp: root.join("Temp"),
        }
    }
}

impl StorageConfig {
    fn validate(&self) -> Result<(), CoreError> {
        let paths = [&self.data, &self.cache, &self.downloads, &self.temp];
        if paths.iter().any(|path| path.as_os_str().is_empty()) {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "storage paths must not be empty",
                false,
            ));
        }
        let distinct: HashSet<_> = paths.iter().collect();
        if distinct.len() != paths.len() {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "data, cache, downloads and temp paths must be distinct",
                false,
            ));
        }
        Ok(())
    }
}

/// Limits for temporary Core operations.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct OperationConfig {
    /// Maximum concurrently running operations. Defaults to `128`.
    pub max_active: usize,
    /// Maximum operations waiting for a worker slot. Defaults to `256`.
    pub max_queued: usize,
    /// Maximum terminal snapshots retained in memory. Defaults to `512`.
    pub retained_terminal: usize,
    /// Default operation deadline in seconds. Defaults to `30`.
    pub default_deadline_seconds: u64,
}

impl Default for OperationConfig {
    fn default() -> Self {
        Self {
            max_active: 128,
            max_queued: 256,
            retained_terminal: 512,
            default_deadline_seconds: 30,
        }
    }
}

impl OperationConfig {
    fn validate(&self) -> Result<(), CoreError> {
        if self.max_active == 0 || self.retained_terminal == 0 || self.default_deadline_seconds == 0
        {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "operation max_active, retained_terminal and default_deadline_seconds must be greater than zero",
                false,
            ));
        }
        Ok(())
    }
}

/// Runtime event journal settings.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct EventConfig {
    /// Live subscriber channel capacity. Defaults to `1024`.
    pub capacity: usize,
    /// Number of events retained for cursor replay. Defaults to `2048`.
    pub retained: usize,
}

impl Default for EventConfig {
    fn default() -> Self {
        Self {
            capacity: 1024,
            retained: 2048,
        }
    }
}

impl EventConfig {
    fn validate(&self) -> Result<(), CoreError> {
        if self.capacity == 0 || self.retained == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "event capacity and retained must be greater than zero",
                false,
            ));
        }
        Ok(())
    }
}

/// Shared HTTP transport limits applied to every Provider profile.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct NetworkConfig {
    /// TCP connect timeout in seconds. Defaults to `10`.
    pub connect_timeout_seconds: u64,
    /// Full request deadline in seconds. Defaults to `30`.
    pub request_timeout_seconds: u64,
    /// Maximum buffered response size in bytes. Defaults to `8388608` (8 MiB).
    pub max_response_bytes: usize,
    /// Maximum redirects followed by one request. Defaults to `5`.
    pub max_redirects: usize,
    /// Optional HTTP(S) proxy applied to Provider traffic. Defaults to `None`.
    pub proxy_url: Option<Url>,
}

impl Default for NetworkConfig {
    fn default() -> Self {
        Self {
            connect_timeout_seconds: 10,
            request_timeout_seconds: 30,
            max_response_bytes: 8 * 1024 * 1024,
            max_redirects: 5,
            proxy_url: None,
        }
    }
}

impl NetworkConfig {
    fn validate(&self) -> Result<(), CoreError> {
        if self.connect_timeout_seconds == 0
            || self.request_timeout_seconds == 0
            || self.max_response_bytes == 0
        {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "network timeouts and max_response_bytes must be greater than zero",
                false,
            ));
        }
        if self.proxy_url.as_ref().is_some_and(|url| {
            !matches!(url.scheme(), "http" | "https") || url.host_str().is_none()
        }) {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                "network proxy_url must be an HTTP(S) URL",
                false,
            ));
        }
        Ok(())
    }
}

/// Immutable inputs used to create one Provider session generation.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct ProviderProfileConfig {
    /// Provider implementation identifier. Defaults to an empty string and must be configured.
    pub provider: String,
    /// Profile name. Defaults to `"default"`.
    pub profile: String,
    /// Provider API origin. Defaults to `http://127.0.0.1/` and must use HTTP or HTTPS.
    pub base_url: Url,
    /// User-Agent sent by this generation. Defaults to `fvcore/<crate version>`.
    pub user_agent: String,
    /// Additional redirect hosts allowed for this profile. Defaults to an empty list.
    pub allowed_redirect_hosts: Vec<String>,
    /// Environment variable containing a Cookie header value. Defaults to `None`.
    pub cookie_env: Option<String>,
    /// Environment variable containing the Provider API user/login. Defaults to `None`.
    pub api_user_env: Option<String>,
    /// Environment variable containing the Provider API key. Defaults to `None`.
    pub api_key_env: Option<String>,
    /// Maximum requests concurrently using this profile generation. Defaults to `4`.
    pub max_concurrent_requests: usize,
    /// Minimum delay between request starts for this profile, in milliseconds. Defaults to `0`.
    pub min_request_interval_ms: u64,
}

impl Default for ProviderProfileConfig {
    fn default() -> Self {
        Self {
            provider: String::new(),
            profile: "default".to_owned(),
            base_url: Url::parse("http://127.0.0.1/").expect("static URL is valid"),
            user_agent: format!("fvcore/{}", crate::VERSION),
            allowed_redirect_hosts: Vec::new(),
            cookie_env: None,
            api_user_env: None,
            api_key_env: None,
            max_concurrent_requests: default_profile_concurrency(),
            min_request_interval_ms: 0,
        }
    }
}

impl ProviderProfileConfig {
    pub(crate) fn validate(&self, key: &str) -> Result<(), CoreError> {
        if self.provider.trim().is_empty() || self.profile.trim().is_empty() {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                format!("profile {key} provider and profile names must not be empty"),
                false,
            ));
        }
        if !matches!(self.base_url.scheme(), "http" | "https") || self.base_url.host_str().is_none()
        {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                format!("profile {key} base_url must be an HTTP(S) origin"),
                false,
            ));
        }
        if self.user_agent.trim().is_empty() {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                format!("profile {key} user_agent must not be empty"),
                false,
            ));
        }
        if self
            .cookie_env
            .as_ref()
            .is_some_and(|name| name.trim().is_empty())
        {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                format!("profile {key} cookie_env must not be empty"),
                false,
            ));
        }
        if self
            .api_user_env
            .as_ref()
            .is_some_and(|name| name.trim().is_empty())
            || self
                .api_key_env
                .as_ref()
                .is_some_and(|name| name.trim().is_empty())
        {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                format!("profile {key} API credential environment names must not be empty"),
                false,
            ));
        }
        if self.api_user_env.is_some() != self.api_key_env.is_some() {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                format!("profile {key} api_user_env and api_key_env must be configured together"),
                false,
            ));
        }
        if self.max_concurrent_requests == 0 {
            return Err(CoreError::new(
                ErrorCode::InvalidConfig,
                format!("profile {key} max_concurrent_requests must be greater than zero"),
                false,
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{CoreConfig, StorageConfig};
    use std::path::PathBuf;

    #[test]
    fn defaults_are_valid() {
        let config = CoreConfig::default();
        config.validate().unwrap();
        assert_eq!(config.profiles.len(), 4);
        assert_eq!(
            config.profiles["eh"].base_url.as_str(),
            "https://e-hentai.org/"
        );
        assert_eq!(
            config.profiles["pixiv"].base_url.as_str(),
            "https://www.pixiv.net/"
        );
        assert_eq!(
            config.profiles["danbooru"].base_url.as_str(),
            "https://danbooru.donmai.us/"
        );
        assert_eq!(
            config.profiles["gelbooru"].base_url.as_str(),
            "https://gelbooru.com/"
        );
    }

    #[test]
    fn rejects_unknown_fields() {
        let result = CoreConfig::from_json(r#"{"unknown":true}"#);
        assert!(result.is_err());
    }

    #[test]
    fn omitted_profiles_keep_the_four_defaults() {
        let config = CoreConfig::from_json(r#"{"instance_name":"custom"}"#).unwrap();
        assert_eq!(config.profiles.len(), 4);
        assert!(config.profiles.contains_key("eh"));
        assert!(config.profiles.contains_key("pixiv"));
        assert!(config.profiles.contains_key("danbooru"));
        assert!(config.profiles.contains_key("gelbooru"));
    }

    #[test]
    fn explicit_profiles_replace_the_default_map() {
        let config = CoreConfig::from_json(
            r#"{"profiles":{"local":{"provider":"danbooru","base_url":"http://127.0.0.1/"}}}"#,
        )
        .unwrap();
        assert_eq!(config.profiles.len(), 1);
        assert!(config.profiles.contains_key("local"));
    }

    #[test]
    fn rejects_duplicate_storage_domains() {
        let config = CoreConfig {
            storage: StorageConfig {
                data: PathBuf::from("same"),
                cache: PathBuf::from("same"),
                downloads: PathBuf::from("downloads"),
                temp: PathBuf::from("temp"),
            },
            ..CoreConfig::default()
        };
        assert!(config.validate().is_err());
    }

    #[test]
    fn validates_profile_credentials_and_limits() {
        let mut missing_key = super::ProviderProfileConfig {
            provider: "danbooru".to_owned(),
            api_user_env: Some("DANBOORU_USER".to_owned()),
            ..super::ProviderProfileConfig::default()
        };
        assert!(missing_key.validate("danbooru").is_err());
        missing_key.api_key_env = Some("DANBOORU_KEY".to_owned());
        assert!(missing_key.validate("danbooru").is_ok());
        missing_key.max_concurrent_requests = 0;
        assert!(missing_key.validate("danbooru").is_err());
    }

    #[test]
    fn validates_image_byte_budgets() {
        let mut config = CoreConfig::default();
        config.images.max_image_bytes = 1024;
        config.images.max_inflight_bytes = 512;
        assert!(config.validate().is_err());
        config.images.max_inflight_bytes = 1024;
        assert!(config.validate().is_ok());
    }
}
