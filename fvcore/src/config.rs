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
    /// Configured Provider profiles. Defaults to an empty map.
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
            profiles: BTreeMap::new(),
        }
    }
}

impl CoreConfig {
    /// Parses TOML configuration from a UTF-8 string.
    pub fn from_toml(input: &str) -> Result<Self, CoreError> {
        toml::from_str(input).map_err(|error| {
            CoreError::new(
                ErrorCode::Parse,
                format!("failed to parse TOML configuration: {error}"),
                false,
            )
        })
    }

    /// Reads and parses a TOML configuration file.
    pub fn from_toml_file(path: &Path) -> Result<Self, CoreError> {
        let input = std::fs::read_to_string(path).map_err(|error| {
            CoreError::new(
                ErrorCode::Io,
                format!("failed to read configuration {}: {error}", path.display()),
                false,
            )
        })?;
        Self::from_toml(&input)
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

/// Integrated HTTP control-plane configuration.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct ControlConfig {
    /// Whether the Runtime should listen for HTTP requests. Defaults to `false`.
    pub enabled: bool,
    /// Address used when HTTP listening is enabled. Defaults to `127.0.0.1:8787`.
    pub listen: SocketAddr,
}

impl Default for ControlConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            listen: default_control_listen(),
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
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{CoreConfig, StorageConfig};
    use std::path::PathBuf;

    #[test]
    fn defaults_are_valid() {
        CoreConfig::default().validate().unwrap();
    }

    #[test]
    fn rejects_unknown_fields() {
        let result = CoreConfig::from_toml("unknown = true");
        assert!(result.is_err());
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
}
