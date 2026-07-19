//! Content-addressed image resources and the Runtime-owned image cache.

use crate::{CoreError, ErrorCode, ImageConfig, ProfileKey, session::SessionRegistry};
use bytes::Bytes;
use md5::{Digest, Md5};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, HashMap},
    fmt,
    path::{Path, PathBuf},
    str::FromStr,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};
use tokio::{
    io::AsyncWriteExt,
    sync::{Mutex, Semaphore, mpsc, watch},
    task::JoinHandle,
};
use tokio_util::sync::CancellationToken;
use url::Url;

const FORMATS: &[&str] = &["jpg", "png", "gif", "webp", "avif"];

/// A real 128-bit image-content MD5 rendered as 32 lowercase hexadecimal characters.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ContentMd5([u8; 16]);

impl ContentMd5 {
    fn digest(bytes: &[u8]) -> Self {
        Self(Md5::digest(bytes).into())
    }
}

impl FromStr for ContentMd5 {
    type Err = CoreError;

    fn from_str(input: &str) -> Result<Self, Self::Err> {
        if input.len() != 32 || !input.bytes().all(|value| value.is_ascii_hexdigit()) {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "content MD5 must contain exactly 32 hexadecimal characters",
                false,
            ));
        }
        let mut digest = [0_u8; 16];
        for (index, byte) in digest.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&input[index * 2..index * 2 + 2], 16).map_err(|_| {
                CoreError::new(ErrorCode::InvalidInput, "content MD5 is invalid", false)
            })?;
        }
        Ok(Self(digest))
    }
}

impl fmt::Display for ContentMd5 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        for byte in self.0 {
            write!(formatter, "{byte:02x}")?;
        }
        Ok(())
    }
}

/// Stable identity used to merge and persist resources whose content MD5 is not known beforehand.
#[derive(Clone, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub struct ResourceKey {
    /// Provider implementation identifier.
    pub provider: String,
    /// Provider media identifier.
    pub media: String,
    /// Zero-based page index.
    pub page: u32,
    /// Provider-neutral representation name such as `original`.
    pub variant: String,
}

impl ResourceKey {
    /// Creates a stable resource identity after validating path-independent components.
    pub fn new(
        provider: impl Into<String>,
        media: impl Into<String>,
        page: u32,
        variant: impl Into<String>,
    ) -> Result<Self, CoreError> {
        let key = Self {
            provider: provider.into(),
            media: media.into(),
            page,
            variant: variant.into(),
        };
        if [&key.provider, &key.media, &key.variant]
            .iter()
            .any(|value| value.trim().is_empty() || value.len() > 128)
        {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "resource key components must contain 1 to 128 characters",
                false,
            ));
        }
        Ok(key)
    }
}

/// Location that satisfied one image fetch.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceSource {
    /// Existing immutable bytes in the Runtime memory cache.
    Memory,
    /// A verified content-addressed disk blob.
    Disk,
    /// A Provider network transfer.
    Network,
}

/// Safe control-plane description of immutable image bytes.
#[derive(Clone, Debug, Serialize)]
pub struct ImageResourceDescriptor {
    /// Verified real-content MD5.
    pub content_md5: ContentMd5,
    /// Canonical image extension without a leading dot.
    pub extension: String,
    /// MIME type derived from magic bytes.
    pub mime_type: String,
    /// Exact byte length.
    pub byte_length: usize,
    /// Layer that satisfied this caller.
    pub source: ResourceSource,
    /// Whether a content-addressed disk blob exists.
    pub cache_persisted: bool,
}

/// Immutable binary image resource returned to embedded callers.
#[derive(Clone, Debug)]
pub struct ImageResource {
    descriptor: ImageResourceDescriptor,
    bytes: Bytes,
}

impl ImageResource {
    /// Returns the safe descriptor shared with control adapters.
    #[must_use]
    pub fn descriptor(&self) -> &ImageResourceDescriptor {
        &self.descriptor
    }

    /// Returns a cheap clone of the immutable image bytes.
    #[must_use]
    pub fn bytes(&self) -> Bytes {
        self.bytes.clone()
    }
}

#[derive(Clone)]
pub(crate) struct ImageFetchSpec {
    pub(crate) profile: ProfileKey,
    pub(crate) url: Url,
    pub(crate) expected_md5: Option<ContentMd5>,
    pub(crate) resource_key: Option<ResourceKey>,
    pub(crate) expected_bytes: Option<u64>,
    pub(crate) referer: Option<Url>,
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
enum FetchKey {
    Content(ContentMd5),
    Resource(ResourceKey),
}

#[derive(Clone)]
pub(crate) struct ImageProgress {
    pub(crate) phase: &'static str,
    pub(crate) bytes_done: u64,
    pub(crate) bytes_total: Option<u64>,
    pub(crate) source: Option<ResourceSource>,
    pub(crate) shared: bool,
}

#[derive(Clone)]
struct TransferState {
    progress: ImageProgress,
    result: Option<Result<ImageResource, CoreError>>,
}

struct SharedTransfer {
    state: watch::Receiver<TransferState>,
    cancellation: CancellationToken,
    subscribers: AtomicUsize,
}

struct Subscriber {
    transfer: Arc<SharedTransfer>,
}

impl Drop for Subscriber {
    fn drop(&mut self) {
        if self.transfer.subscribers.fetch_sub(1, Ordering::AcqRel) == 1 {
            self.transfer.cancellation.cancel();
        }
    }
}

struct MemoryEntry {
    resource: ImageResource,
    last_used: u64,
}

#[derive(Default)]
struct MemoryCache {
    entries: HashMap<ContentMd5, MemoryEntry>,
    bytes: usize,
    clock: u64,
}

pub(crate) struct ImageService {
    config: ImageConfig,
    cache_root: PathBuf,
    sessions: Arc<SessionRegistry>,
    memory: Mutex<MemoryCache>,
    aliases: Mutex<BTreeMap<ResourceKey, ContentMd5>>,
    inflight: Mutex<HashMap<FetchKey, Arc<SharedTransfer>>>,
    inflight_bytes: Arc<Semaphore>,
    write_tx: mpsc::Sender<CacheWrite>,
    writer_shutdown: CancellationToken,
    writer: Mutex<Option<JoinHandle<()>>>,
}

struct CacheWrite {
    resource: ImageResource,
    alias: Option<ResourceKey>,
}

impl ImageService {
    pub(crate) fn new(
        config: ImageConfig,
        cache_root: PathBuf,
        sessions: Arc<SessionRegistry>,
    ) -> Result<Arc<Self>, CoreError> {
        let aliases = load_aliases(&cache_root)?;
        let (write_tx, write_rx) = mpsc::channel(config.cache_write_queue);
        let writer_shutdown = CancellationToken::new();
        let service = Arc::new(Self {
            inflight_bytes: Arc::new(Semaphore::new(config.max_inflight_bytes)),
            config,
            cache_root,
            sessions,
            memory: Mutex::new(MemoryCache::default()),
            aliases: Mutex::new(aliases),
            inflight: Mutex::new(HashMap::new()),
            write_tx,
            writer_shutdown,
            writer: Mutex::new(None),
        });
        let writer = tokio::spawn(run_cache_writer(service.clone(), write_rx));
        *service
            .writer
            .try_lock()
            .expect("new image writer lock is uncontended") = Some(writer);
        Ok(service)
    }

    pub(crate) async fn fetch<F>(
        self: &Arc<Self>,
        spec: ImageFetchSpec,
        cancellation: CancellationToken,
        mut progress: F,
    ) -> Result<ImageResource, CoreError>
    where
        F: FnMut(ImageProgress) + Send,
    {
        let known_md5 = match (&spec.expected_md5, &spec.resource_key) {
            (Some(md5), _) => Some(*md5),
            (None, Some(key)) => self.aliases.lock().await.get(key).copied(),
            (None, None) => {
                return Err(CoreError::new(
                    ErrorCode::InvalidInput,
                    "image fetch requires an expected MD5 or stable resource key",
                    false,
                ));
            }
        };
        progress(ImageProgress {
            phase: "checking_memory",
            bytes_done: 0,
            bytes_total: spec.expected_bytes,
            source: Some(ResourceSource::Memory),
            shared: false,
        });
        if let Some(md5) = known_md5 {
            if let Some(resource) = self.memory_get(md5).await {
                return Ok(with_source(resource, ResourceSource::Memory));
            }
            progress(ImageProgress {
                phase: "checking_disk",
                bytes_done: 0,
                bytes_total: spec.expected_bytes,
                source: Some(ResourceSource::Disk),
                shared: false,
            });
            if let Some(resource) = self.disk_get(md5).await? {
                self.memory_insert(resource.clone()).await;
                return Ok(with_source(resource, ResourceSource::Disk));
            }
        }

        let (subscriber, mut state) = self.join_or_start(spec).await;
        loop {
            let current = state.borrow().clone();
            progress(current.progress);
            if let Some(result) = current.result {
                return result;
            }
            tokio::select! {
                biased;
                () = cancellation.cancelled() => {
                    drop(subscriber);
                    return Err(CoreError::new(ErrorCode::Cancelled, "image fetch was cancelled", false));
                }
                changed = state.changed() => if changed.is_err() {
                    return Err(CoreError::new(ErrorCode::Internal, "shared image transfer stopped without a result", false));
                }
            }
        }
    }

    pub(crate) async fn resource(
        &self,
        md5: ContentMd5,
        extension: &str,
    ) -> Result<ImageResource, CoreError> {
        let extension = normalize_extension(extension)?;
        if let Some(resource) = self.memory_get(md5).await {
            if resource.descriptor.extension == extension {
                return Ok(with_source(resource, ResourceSource::Memory));
            }
        }
        let resource = self.disk_get(md5).await?.ok_or_else(|| {
            CoreError::new(
                ErrorCode::ResourceNotFound,
                "image resource was not found",
                false,
            )
        })?;
        if resource.descriptor.extension != extension {
            return Err(CoreError::new(
                ErrorCode::ResourceNotFound,
                "image resource extension does not match its content",
                false,
            ));
        }
        self.memory_insert(resource.clone()).await;
        Ok(with_source(resource, ResourceSource::Disk))
    }

    pub(crate) async fn shutdown(&self, deadline: std::time::Duration) -> Result<(), CoreError> {
        self.writer_shutdown.cancel();
        let Some(mut writer) = self.writer.lock().await.take() else {
            return Ok(());
        };
        tokio::time::timeout(deadline, &mut writer)
            .await
            .map_err(|_| {
                CoreError::new(
                    ErrorCode::DeadlineExceeded,
                    "image cache writer shutdown deadline exceeded",
                    false,
                )
            })?
            .map_err(|_| CoreError::new(ErrorCode::Internal, "image cache writer panicked", false))
    }

    async fn join_or_start(
        self: &Arc<Self>,
        spec: ImageFetchSpec,
    ) -> (Subscriber, watch::Receiver<TransferState>) {
        let key = spec
            .expected_md5
            .map(FetchKey::Content)
            .or_else(|| spec.resource_key.clone().map(FetchKey::Resource))
            .expect("fetch identity was validated");
        let mut inflight = self.inflight.lock().await;
        if let Some(transfer) = inflight.get(&key) {
            transfer.subscribers.fetch_add(1, Ordering::Relaxed);
            return (
                Subscriber {
                    transfer: transfer.clone(),
                },
                transfer.state.clone(),
            );
        }
        let cancellation = CancellationToken::new();
        let initial = TransferState {
            progress: ImageProgress {
                phase: "fetching",
                bytes_done: 0,
                bytes_total: spec.expected_bytes,
                source: Some(ResourceSource::Network),
                shared: false,
            },
            result: None,
        };
        let (state_tx, state_rx) = watch::channel(initial);
        let transfer = Arc::new(SharedTransfer {
            state: state_rx.clone(),
            cancellation,
            subscribers: AtomicUsize::new(1),
        });
        inflight.insert(key.clone(), transfer.clone());
        drop(inflight);

        let service = self.clone();
        let worker_transfer = transfer.clone();
        tokio::spawn(async move {
            let result = service
                .fetch_network(&spec, &worker_transfer, &state_tx)
                .await;
            let final_progress = match &result {
                Ok(resource) => ImageProgress {
                    phase: "ready_in_memory",
                    bytes_done: resource.descriptor.byte_length as u64,
                    bytes_total: Some(resource.descriptor.byte_length as u64),
                    source: Some(ResourceSource::Network),
                    shared: worker_transfer.subscribers.load(Ordering::Relaxed) > 1,
                },
                Err(_) => state_tx.borrow().progress.clone(),
            };
            state_tx.send_replace(TransferState {
                progress: final_progress,
                result: Some(result),
            });
            service.inflight.lock().await.remove(&key);
        });

        (Subscriber { transfer }, state_rx)
    }

    async fn fetch_network(
        &self,
        spec: &ImageFetchSpec,
        transfer: &SharedTransfer,
        state: &watch::Sender<TransferState>,
    ) -> Result<ImageResource, CoreError> {
        let permits = u32::try_from(self.config.max_image_bytes).map_err(|_| {
            CoreError::new(
                ErrorCode::InvalidConfig,
                "image byte limit is too large",
                false,
            )
        })?;
        let _budget = tokio::select! {
            biased;
            () = transfer.cancellation.cancelled() => return Err(cancelled()),
            permit = self.inflight_bytes.clone().acquire_many_owned(permits) => permit.map_err(|_| {
                CoreError::new(ErrorCode::NotReady, "image service is shutting down", true)
            })?,
        };
        let shared = || transfer.subscribers.load(Ordering::Relaxed) > 1;
        let response = self
            .sessions
            .get_absolute(
                &spec.profile,
                &spec.url,
                spec.referer.as_ref(),
                self.config.max_image_bytes,
                transfer.cancellation.clone(),
                |done, total| {
                    state.send_replace(TransferState {
                        progress: ImageProgress {
                            phase: "fetching",
                            bytes_done: done as u64,
                            bytes_total: total.or(spec.expected_bytes),
                            source: Some(ResourceSource::Network),
                            shared: shared(),
                        },
                        result: None,
                    });
                },
            )
            .await?;
        state.send_replace(TransferState {
            progress: ImageProgress {
                phase: "verifying",
                bytes_done: response.body.len() as u64,
                bytes_total: Some(response.body.len() as u64),
                source: Some(ResourceSource::Network),
                shared: shared(),
            },
            result: None,
        });
        if spec
            .expected_bytes
            .is_some_and(|expected| expected != response.body.len() as u64)
        {
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "image byte length does not match Provider metadata",
                false,
            ));
        }
        let actual_md5 = ContentMd5::digest(&response.body);
        if spec
            .expected_md5
            .is_some_and(|expected| actual_md5 != expected)
        {
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "image content MD5 does not match Provider metadata",
                false,
            ));
        }
        let (extension, mime_type) = detect_format(&response.body)?;
        let resource = ImageResource {
            descriptor: ImageResourceDescriptor {
                content_md5: actual_md5,
                extension: extension.to_owned(),
                mime_type: mime_type.to_owned(),
                byte_length: response.body.len(),
                source: ResourceSource::Network,
                cache_persisted: false,
            },
            bytes: response.body,
        };
        self.memory_insert(resource.clone()).await;
        if let Some(key) = &spec.resource_key {
            self.aliases.lock().await.insert(key.clone(), actual_md5);
        }
        let write = CacheWrite {
            resource: resource.clone(),
            alias: spec.resource_key.clone(),
        };
        if self.write_tx.try_send(write).is_err() {
            tracing::warn!(content_md5 = %actual_md5, "image cache write queue is full; resource remains available in memory");
        }
        Ok(resource)
    }

    async fn memory_get(&self, md5: ContentMd5) -> Option<ImageResource> {
        let mut cache = self.memory.lock().await;
        cache.clock = cache.clock.wrapping_add(1);
        let clock = cache.clock;
        cache.entries.get_mut(&md5).map(|entry| {
            entry.last_used = clock;
            entry.resource.clone()
        })
    }

    async fn memory_insert(&self, resource: ImageResource) {
        let mut cache = self.memory.lock().await;
        cache.clock = cache.clock.wrapping_add(1);
        let clock = cache.clock;
        if let Some(previous) = cache.entries.remove(&resource.descriptor.content_md5) {
            cache.bytes = cache.bytes.saturating_sub(previous.resource.bytes.len());
        }
        cache.bytes = cache.bytes.saturating_add(resource.bytes.len());
        cache.entries.insert(
            resource.descriptor.content_md5,
            MemoryEntry {
                resource,
                last_used: clock,
            },
        );
        while cache.bytes > self.config.memory_cache_bytes {
            let Some(oldest) = cache
                .entries
                .iter()
                .min_by_key(|(_, entry)| entry.last_used)
                .map(|(md5, _)| *md5)
            else {
                break;
            };
            if let Some(removed) = cache.entries.remove(&oldest) {
                cache.bytes = cache.bytes.saturating_sub(removed.resource.bytes.len());
            }
        }
    }

    async fn disk_get(&self, md5: ContentMd5) -> Result<Option<ImageResource>, CoreError> {
        for extension in FORMATS {
            let path = cache_path(&self.cache_root, md5, extension);
            let metadata = match tokio::fs::metadata(&path).await {
                Ok(metadata) => metadata,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
                Err(error) => return Err(io_error("inspect image cache", &path, error)),
            };
            if metadata.len() > self.config.max_image_bytes as u64 {
                if let Err(error) = tokio::fs::remove_file(&path).await {
                    tracing::warn!(path = %path.display(), %error, "failed to remove oversized image cache blob");
                }
                continue;
            }
            let bytes = match tokio::fs::read(&path).await {
                Ok(bytes) => bytes,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
                Err(error) => return Err(io_error("read image cache", &path, error)),
            };
            if bytes.len() > self.config.max_image_bytes
                || ContentMd5::digest(&bytes) != md5
                || !detect_format(&bytes).is_ok_and(|format| format.0 == *extension)
            {
                if let Err(error) = tokio::fs::remove_file(&path).await {
                    tracing::warn!(path = %path.display(), %error, "failed to remove stale image cache blob");
                }
                continue;
            }
            let (_, mime_type) = detect_format(&bytes)?;
            return Ok(Some(ImageResource {
                descriptor: ImageResourceDescriptor {
                    content_md5: md5,
                    extension: (*extension).to_owned(),
                    mime_type: mime_type.to_owned(),
                    byte_length: bytes.len(),
                    source: ResourceSource::Disk,
                    cache_persisted: true,
                },
                bytes: Bytes::from(bytes),
            }));
        }
        Ok(None)
    }

    async fn persist(&self, resource: &ImageResource) -> Result<(), CoreError> {
        let path = cache_path(
            &self.cache_root,
            resource.descriptor.content_md5,
            &resource.descriptor.extension,
        );
        if tokio::fs::try_exists(&path)
            .await
            .map_err(|error| io_error("inspect image cache", &path, error))?
        {
            return Ok(());
        }
        let parent = path.parent().expect("cache blob always has a parent");
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|error| io_error("create image cache shard", parent, error))?;
        let staging = path.with_extension(format!("{}.tmp", resource.descriptor.extension));
        let mut file = tokio::fs::File::create(&staging)
            .await
            .map_err(|error| io_error("create staged image cache", &staging, error))?;
        file.write_all(&resource.bytes)
            .await
            .map_err(|error| io_error("write staged image cache", &staging, error))?;
        file.sync_all()
            .await
            .map_err(|error| io_error("flush staged image cache", &staging, error))?;
        drop(file);
        tokio::fs::rename(&staging, &path)
            .await
            .map_err(|error| io_error("publish image cache", &path, error))?;
        Ok(())
    }
}

async fn run_cache_writer(service: Arc<ImageService>, mut writes: mpsc::Receiver<CacheWrite>) {
    let mut persisted_aliases = load_aliases(&service.cache_root).unwrap_or_default();
    loop {
        let write = tokio::select! {
            biased;
            write = writes.recv() => write,
            () = service.writer_shutdown.cancelled() => {
                writes.close();
                writes.recv().await
            }
        };
        let Some(write) = write else {
            break;
        };
        let md5 = write.resource.descriptor.content_md5;
        if let Err(error) = service.persist(&write.resource).await {
            tracing::warn!(content_md5 = %md5, %error, "failed to persist image cache blob");
            continue;
        }
        if let Some(alias) = write.alias {
            persisted_aliases.insert(alias, md5);
            if let Err(error) = persist_aliases(&service.cache_root, &persisted_aliases).await {
                tracing::warn!(content_md5 = %md5, %error, "failed to persist image resource aliases");
            }
        }
        let mut resource = write.resource;
        resource.descriptor.cache_persisted = true;
        service.memory_insert(resource).await;
    }
}

fn load_aliases(root: &Path) -> Result<BTreeMap<ResourceKey, ContentMd5>, CoreError> {
    let path = root.join("image_aliases.json");
    let input = match std::fs::read(&path) {
        Ok(input) => input,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(BTreeMap::new()),
        Err(error) => return Err(io_error("read image aliases", &path, error)),
    };
    let stored: Vec<(ResourceKey, String)> = serde_json::from_slice(&input).map_err(|_| {
        CoreError::new(
            ErrorCode::Parse,
            format!("failed to parse image aliases {}", path.display()),
            false,
        )
    })?;
    stored
        .into_iter()
        .map(|(key, md5)| Ok((key, ContentMd5::from_str(&md5)?)))
        .collect()
}

async fn persist_aliases(
    root: &Path,
    aliases: &BTreeMap<ResourceKey, ContentMd5>,
) -> Result<(), CoreError> {
    let path = root.join("image_aliases.json");
    let staging = root.join("image_aliases.json.tmp");
    let stored: Vec<_> = aliases
        .iter()
        .map(|(key, md5)| (key, md5.to_string()))
        .collect();
    let bytes = serde_json::to_vec(&stored).map_err(|_| {
        CoreError::new(
            ErrorCode::Internal,
            "failed to serialize image aliases",
            false,
        )
    })?;
    let mut file = tokio::fs::File::create(&staging)
        .await
        .map_err(|error| io_error("create staged image aliases", &staging, error))?;
    file.write_all(&bytes)
        .await
        .map_err(|error| io_error("write staged image aliases", &staging, error))?;
    file.sync_all()
        .await
        .map_err(|error| io_error("flush staged image aliases", &staging, error))?;
    drop(file);
    tokio::fs::rename(&staging, &path)
        .await
        .map_err(|error| io_error("publish image aliases", &path, error))
}

fn with_source(mut resource: ImageResource, source: ResourceSource) -> ImageResource {
    resource.descriptor.source = source;
    resource
}

fn cache_path(root: &Path, md5: ContentMd5, extension: &str) -> PathBuf {
    let digest = md5.to_string();
    root.join("files")
        .join(&digest[0..2])
        .join(&digest[2..4])
        .join(format!("{digest}.{extension}"))
}

fn detect_format(bytes: &[u8]) -> Result<(&'static str, &'static str), CoreError> {
    if bytes.starts_with(&[0xff, 0xd8, 0xff]) {
        Ok(("jpg", "image/jpeg"))
    } else if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        Ok(("png", "image/png"))
    } else if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        Ok(("gif", "image/gif"))
    } else if bytes.len() >= 12 && bytes.starts_with(b"RIFF") && &bytes[8..12] == b"WEBP" {
        Ok(("webp", "image/webp"))
    } else if bytes.len() >= 12 && &bytes[4..8] == b"ftyp" && &bytes[8..12] == b"avif" {
        Ok(("avif", "image/avif"))
    } else {
        Err(CoreError::new(
            ErrorCode::UnexpectedResponse,
            "image response has an unsupported or invalid file signature",
            false,
        ))
    }
}

fn normalize_extension(extension: &str) -> Result<&str, CoreError> {
    let extension = extension.trim().trim_start_matches('.');
    let extension = if extension.eq_ignore_ascii_case("jpeg") {
        "jpg"
    } else {
        extension
    };
    FORMATS
        .iter()
        .copied()
        .find(|candidate| extension.eq_ignore_ascii_case(candidate))
        .ok_or_else(|| {
            CoreError::new(
                ErrorCode::InvalidInput,
                "image resource extension is unsupported",
                false,
            )
        })
}

fn cancelled() -> CoreError {
    CoreError::new(ErrorCode::Cancelled, "image transfer was cancelled", false)
}

fn io_error(action: &str, path: &Path, error: std::io::Error) -> CoreError {
    CoreError::new(
        ErrorCode::Io,
        format!("failed to {action} {}: {error}", path.display()),
        false,
    )
}

#[cfg(test)]
mod tests {
    use super::{ContentMd5, cache_path, detect_format};
    use std::{path::Path, str::FromStr};

    #[test]
    fn content_md5_is_strict_and_paths_are_sharded() {
        let md5 = ContentMd5::from_str("D256310BFAB43E08B6422E311CD9B2C9").unwrap();
        assert_eq!(md5.to_string(), "d256310bfab43e08b6422e311cd9b2c9");
        assert_eq!(
            cache_path(Path::new("Cache"), md5, "webp"),
            Path::new("Cache/files/d2/56/d256310bfab43e08b6422e311cd9b2c9.webp")
        );
        assert!(ContentMd5::from_str("not-md5").is_err());
    }

    #[test]
    fn image_format_comes_from_magic_bytes() {
        assert_eq!(detect_format(b"\xff\xd8\xffpayload").unwrap().0, "jpg");
        assert!(detect_format(b"not an image").is_err());
    }
}
