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
const ALIAS_SCHEMA_VERSION: u32 = 1;

/// Read-only accounting for the Runtime-owned image cache.
#[derive(Clone, Debug, Serialize)]
pub struct ImageCacheSnapshot {
    /// Bytes retained by the memory LRU.
    pub memory_bytes: usize,
    /// Configured memory LRU limit.
    pub memory_limit_bytes: usize,
    /// Number of memory LRU entries.
    pub memory_entries: usize,
    /// Bytes currently held by network image responses.
    pub inflight_bytes: usize,
    /// Configured global in-flight byte limit.
    pub inflight_limit_bytes: usize,
    /// Number of active shared transfers.
    pub active_transfers: usize,
    /// Number of stable resource aliases.
    pub alias_count: usize,
    /// Pending cache writes.
    pub write_queue_depth: usize,
    /// Configured cache write queue capacity.
    pub write_queue_capacity: usize,
    /// Valid content-addressed blobs found on disk.
    pub disk_blob_count: usize,
    /// Bytes occupied by valid disk blobs.
    pub disk_bytes: u64,
    /// Cache staging files awaiting maintenance.
    pub staging_file_count: usize,
    /// Blob files whose path, digest or magic format is invalid.
    pub invalid_blob_count: usize,
}

/// Result of one explicit image cache maintenance pass.
#[derive(Clone, Debug, Serialize)]
pub struct ImageCacheMaintenance {
    /// Staging files removed.
    pub removed_staging_files: usize,
    /// Bytes released by removed staging files.
    pub released_bytes: u64,
    /// Aliases removed because their content blob no longer exists.
    pub removed_stale_aliases: usize,
    /// Invalid blob files removed after content audit.
    pub removed_invalid_blobs: usize,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredAliases {
    schema_version: u32,
    aliases: Vec<(ResourceKey, String)>,
}

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
    disk_maintenance: Mutex<()>,
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
        remove_staging_files(&cache_root)?;
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
            disk_maintenance: Mutex::new(()),
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

    pub(crate) async fn snapshot(&self) -> Result<ImageCacheSnapshot, CoreError> {
        let memory = self.memory.lock().await;
        let memory_bytes = memory.bytes;
        let memory_entries = memory.entries.len();
        drop(memory);
        let root = self.cache_root.clone();
        let scan = tokio::task::spawn_blocking(move || scan_cache(&root))
            .await
            .map_err(|_| {
                CoreError::new(ErrorCode::Internal, "image cache scan panicked", false)
            })??;
        Ok(ImageCacheSnapshot {
            memory_bytes,
            memory_limit_bytes: self.config.memory_cache_bytes,
            memory_entries,
            inflight_bytes: self
                .config
                .max_inflight_bytes
                .saturating_sub(self.inflight_bytes.available_permits()),
            inflight_limit_bytes: self.config.max_inflight_bytes,
            active_transfers: self.inflight.lock().await.len(),
            alias_count: self.aliases.lock().await.len(),
            write_queue_depth: self.write_tx.max_capacity() - self.write_tx.capacity(),
            write_queue_capacity: self.write_tx.max_capacity(),
            disk_blob_count: scan.valid_blobs,
            disk_bytes: scan.valid_bytes,
            staging_file_count: scan.staging.len(),
            invalid_blob_count: scan.invalid.len(),
        })
    }

    pub(crate) async fn maintain(&self) -> Result<ImageCacheMaintenance, CoreError> {
        let _maintenance = self.disk_maintenance.lock().await;
        let root = self.cache_root.clone();
        let scan = tokio::task::spawn_blocking(move || scan_cache(&root))
            .await
            .map_err(|_| {
                CoreError::new(ErrorCode::Internal, "image cache scan panicked", false)
            })??;
        let removals = scan
            .staging
            .iter()
            .chain(&scan.invalid)
            .cloned()
            .collect::<Vec<_>>();
        let released_bytes = tokio::task::spawn_blocking(move || {
            let mut released = 0_u64;
            for (path, bytes) in removals {
                std::fs::remove_file(&path)
                    .map_err(|error| io_error("remove invalid image cache file", &path, error))?;
                released = released.saturating_add(bytes);
            }
            Ok::<_, CoreError>(released)
        })
        .await
        .map_err(|_| {
            CoreError::new(
                ErrorCode::Internal,
                "image cache maintenance panicked",
                false,
            )
        })??;
        let mut aliases = self.aliases.lock().await;
        let before = aliases.len();
        aliases.retain(|_, md5| {
            FORMATS
                .iter()
                .any(|extension| cache_path(&self.cache_root, *md5, extension).is_file())
        });
        let removed_stale_aliases = before - aliases.len();
        if removed_stale_aliases > 0 {
            persist_aliases(&self.cache_root, &aliases).await?;
        }
        Ok(ImageCacheMaintenance {
            removed_staging_files: scan.staging.len(),
            removed_invalid_blobs: scan.invalid.len(),
            released_bytes,
            removed_stale_aliases,
        })
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
        let shared = || transfer.subscribers.load(Ordering::Relaxed) > 1;
        let response = self
            .sessions
            .get_absolute(
                &spec.profile,
                &spec.url,
                spec.referer.as_ref(),
                crate::session::BodyLimit::budgeted(
                    self.config.max_image_bytes,
                    self.inflight_bytes.clone(),
                ),
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
        let crate::session::NetworkResponse {
            body, byte_budget, ..
        } = response;
        state.send_replace(TransferState {
            progress: ImageProgress {
                phase: "verifying",
                bytes_done: body.len() as u64,
                bytes_total: Some(body.len() as u64),
                source: Some(ResourceSource::Network),
                shared: shared(),
            },
            result: None,
        });
        if spec
            .expected_bytes
            .is_some_and(|expected| expected != body.len() as u64)
        {
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "image byte length does not match Provider metadata",
                false,
            ));
        }
        let actual_md5 = ContentMd5::digest(&body);
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
        let (extension, mime_type) = detect_format(&body)?;
        let resource = ImageResource {
            descriptor: ImageResourceDescriptor {
                content_md5: actual_md5,
                extension: extension.to_owned(),
                mime_type: mime_type.to_owned(),
                byte_length: body.len(),
                source: ResourceSource::Network,
                cache_persisted: false,
            },
            bytes: body,
        };
        self.memory_insert(resource.clone()).await;
        drop(byte_budget);
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
        let _maintenance = self.disk_maintenance.lock().await;
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
            let _maintenance = service.disk_maintenance.lock().await;
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
    let value: serde_json::Value = serde_json::from_slice(&input).map_err(|_| {
        CoreError::new(
            ErrorCode::Parse,
            format!("failed to parse image aliases {}", path.display()),
            false,
        )
    })?;
    let stored = if value.is_array() {
        let aliases: Vec<(ResourceKey, String)> = serde_json::from_slice(&input).map_err(|_| {
            CoreError::new(
                ErrorCode::Parse,
                format!("failed to parse image aliases {}", path.display()),
                false,
            )
        })?;
        persist_aliases_sync(root, &aliases)?;
        StoredAliases {
            schema_version: ALIAS_SCHEMA_VERSION,
            aliases,
        }
    } else if value.is_object() {
        serde_json::from_slice(&input).map_err(|_| {
            CoreError::new(
                ErrorCode::Parse,
                format!("failed to parse image aliases {}", path.display()),
                false,
            )
        })?
    } else {
        return Err(CoreError::new(
            ErrorCode::Parse,
            format!("failed to parse image aliases {}", path.display()),
            false,
        ));
    };
    if stored.schema_version != ALIAS_SCHEMA_VERSION {
        return Err(CoreError::new(
            ErrorCode::Parse,
            format!("unsupported image alias schema {}", stored.schema_version),
            false,
        ));
    }
    stored
        .aliases
        .into_iter()
        .map(|(key, md5)| Ok((key, ContentMd5::from_str(&md5)?)))
        .collect()
}

fn persist_aliases_sync(root: &Path, aliases: &[(ResourceKey, String)]) -> Result<(), CoreError> {
    let path = root.join("image_aliases.json");
    let staging = root.join("image_aliases.json.tmp");
    let bytes = serde_json::to_vec(&StoredAliases {
        schema_version: ALIAS_SCHEMA_VERSION,
        aliases: aliases.to_vec(),
    })
    .map_err(|error| {
        CoreError::new(
            ErrorCode::Internal,
            format!("failed to serialize image aliases: {error}"),
            false,
        )
    })?;
    std::fs::write(&staging, bytes)
        .map_err(|error| io_error("write staged image aliases", &staging, error))?;
    std::fs::rename(&staging, &path)
        .map_err(|error| io_error("publish image aliases", &path, error))
}

async fn persist_aliases(
    root: &Path,
    aliases: &BTreeMap<ResourceKey, ContentMd5>,
) -> Result<(), CoreError> {
    let path = root.join("image_aliases.json");
    let staging = root.join("image_aliases.json.tmp");
    let stored = StoredAliases {
        schema_version: ALIAS_SCHEMA_VERSION,
        aliases: aliases
            .iter()
            .map(|(key, md5)| (key.clone(), md5.to_string()))
            .collect(),
    };
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

fn remove_staging_files(root: &Path) -> Result<(), CoreError> {
    for (path, _) in scan_staging(root)? {
        std::fs::remove_file(&path)
            .map_err(|error| io_error("remove staged image cache file", &path, error))?;
    }
    Ok(())
}

fn scan_staging(root: &Path) -> Result<Vec<(PathBuf, u64)>, CoreError> {
    let mut staging = Vec::new();
    let mut directories = vec![root.to_path_buf()];
    while let Some(directory) = directories.pop() {
        let entries = match std::fs::read_dir(&directory) {
            Ok(entries) => entries,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(error) => return Err(io_error("scan image cache staging", &directory, error)),
        };
        for entry in entries {
            let entry =
                entry.map_err(|error| io_error("scan image cache staging", &directory, error))?;
            let path = entry.path();
            let file_type = entry
                .file_type()
                .map_err(|error| io_error("inspect image cache staging", &path, error))?;
            if file_type.is_dir() {
                directories.push(path);
            } else if file_type.is_file() {
                let name = entry.file_name();
                let name = name.to_string_lossy();
                if path == root.join("image_aliases.json.tmp")
                    || (path.starts_with(root.join("files")) && name.ends_with(".tmp"))
                {
                    let length = entry
                        .metadata()
                        .map_err(|error| io_error("inspect image cache staging", &path, error))?
                        .len();
                    staging.push((path, length));
                }
            }
        }
    }
    Ok(staging)
}

struct CacheScan {
    valid_blobs: usize,
    valid_bytes: u64,
    staging: Vec<(PathBuf, u64)>,
    invalid: Vec<(PathBuf, u64)>,
}

fn scan_cache(root: &Path) -> Result<CacheScan, CoreError> {
    let mut blobs = 0;
    let mut bytes = 0_u64;
    let mut staging = Vec::new();
    let mut invalid = Vec::new();
    let mut directories = vec![root.to_path_buf()];
    while let Some(directory) = directories.pop() {
        let entries = match std::fs::read_dir(&directory) {
            Ok(entries) => entries,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(error) => return Err(io_error("scan image cache", &directory, error)),
        };
        for entry in entries {
            let entry = entry.map_err(|error| io_error("scan image cache", &directory, error))?;
            let path = entry.path();
            let file_type = entry
                .file_type()
                .map_err(|error| io_error("inspect image cache entry", &path, error))?;
            if file_type.is_dir() {
                directories.push(path);
            } else if file_type.is_file() {
                let length = entry
                    .metadata()
                    .map_err(|error| io_error("inspect image cache entry", &path, error))?
                    .len();
                let name = entry.file_name();
                let name = name.to_string_lossy();
                if path == root.join("image_aliases.json.tmp")
                    || (path.starts_with(root.join("files")) && name.ends_with(".tmp"))
                {
                    staging.push((path, length));
                } else if path.starts_with(root.join("files")) {
                    if valid_blob_path_and_content(root, &path) {
                        blobs += 1;
                        bytes = bytes.saturating_add(length);
                    } else {
                        invalid.push((path, length));
                    }
                }
            }
        }
    }
    Ok(CacheScan {
        valid_blobs: blobs,
        valid_bytes: bytes,
        staging,
        invalid,
    })
}

fn valid_blob_path_and_content(root: &Path, path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    let Some((digest, extension)) = name.rsplit_once('.') else {
        return false;
    };
    let Ok(expected_md5) = ContentMd5::from_str(digest) else {
        return false;
    };
    if cache_path(root, expected_md5, extension) != path {
        return false;
    }
    let Ok(content) = std::fs::read(path) else {
        return false;
    };
    detect_format(&content).is_ok_and(|(actual_extension, _)| actual_extension == extension)
        && ContentMd5::digest(&content) == expected_md5
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

pub(crate) fn detect_format(bytes: &[u8]) -> Result<(&'static str, &'static str), CoreError> {
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

fn io_error(action: &str, path: &Path, error: std::io::Error) -> CoreError {
    CoreError::new(
        ErrorCode::Io,
        format!("failed to {action} {}: {error}", path.display()),
        false,
    )
}

#[cfg(test)]
mod tests {
    use super::{
        ContentMd5, ResourceKey, StoredAliases, cache_path, detect_format, load_aliases,
        remove_staging_files, scan_cache,
    };
    use std::{path::Path, str::FromStr};
    use tempfile::TempDir;

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

    #[test]
    fn alias_schema_is_strict_and_startup_removes_staging() {
        let temp = TempDir::new().unwrap();
        let aliases = StoredAliases {
            schema_version: 1,
            aliases: vec![(
                ResourceKey::new("eh", "1:token", 0, "viewer").unwrap(),
                "d256310bfab43e08b6422e311cd9b2c9".to_owned(),
            )],
        };
        std::fs::write(
            temp.path().join("image_aliases.json"),
            serde_json::to_vec(&aliases).unwrap(),
        )
        .unwrap();
        assert_eq!(load_aliases(temp.path()).unwrap().len(), 1);
        std::fs::write(temp.path().join("image_aliases.json.tmp"), b"partial").unwrap();
        remove_staging_files(temp.path()).unwrap();
        assert!(!temp.path().join("image_aliases.json.tmp").exists());
        std::fs::write(temp.path().join("image_aliases.json"), b"[]").unwrap();
        assert!(load_aliases(temp.path()).unwrap().is_empty());
        let migrated: serde_json::Value =
            serde_json::from_slice(&std::fs::read(temp.path().join("image_aliases.json")).unwrap())
                .unwrap();
        assert_eq!(migrated["schema_version"], 1);
    }

    #[test]
    fn cache_scan_audits_digest_shards_extension_and_magic() {
        let temp = TempDir::new().unwrap();
        let jpeg = b"\xff\xd8\xfffixture";
        let md5 = ContentMd5::digest(jpeg);
        let valid = cache_path(temp.path(), md5, "jpg");
        std::fs::create_dir_all(valid.parent().unwrap()).unwrap();
        std::fs::write(&valid, jpeg).unwrap();
        let invalid = temp
            .path()
            .join("files/00/00/00000000000000000000000000000000.jpg");
        std::fs::create_dir_all(invalid.parent().unwrap()).unwrap();
        std::fs::write(&invalid, jpeg).unwrap();

        let scan = scan_cache(temp.path()).unwrap();
        assert_eq!(scan.valid_blobs, 1);
        assert_eq!(scan.valid_bytes, jpeg.len() as u64);
        assert_eq!(scan.invalid.len(), 1);
    }
}
