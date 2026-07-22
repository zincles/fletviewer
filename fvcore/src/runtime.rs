//! Core Runtime lifecycle and embedded handle.

use crate::{
    ArchiveTaskSnapshot, BooruOriginalFetchRequest, ContentMd5, CoreConfig, CoreError,
    CoreSnapshot, EhArchiveDownloadRequest, EhPageFetchRequest, ErrorCode, EventBatch,
    EventSubscription, FakeOperationRequest, ImageResource, OperationId, OperationSnapshot,
    PixivPageFetchRequest, ProfileKey, ProfileProbeSnapshot, ProfileSnapshot,
    ProviderProfileConfig, RuntimeId, RuntimeState, StorageSnapshot,
    archive::ArchiveService,
    control,
    gallery::GalleryService,
    image::ImageService,
    operation_service::{OperationCompletion, OperationMessage, OperationService},
    provider::booru::BooruService,
    provider::eh::EhService,
    session::SessionRegistry,
    storage::StorageService,
};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{mpsc, oneshot, watch};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

enum CoreCommand {
    Snapshot {
        reply: oneshot::Sender<CoreSnapshot>,
    },
    EffectiveConfig {
        reply: oneshot::Sender<crate::EffectiveConfigSnapshot>,
    },
    SetControlListen {
        listen: std::net::SocketAddr,
        reply: oneshot::Sender<()>,
    },
    StartFake {
        request: FakeOperationRequest,
        reply: oneshot::Sender<Result<OperationSnapshot, CoreError>>,
    },
    StartBooruOriginal {
        request: BooruOriginalFetchRequest,
        reply: oneshot::Sender<Result<OperationSnapshot, CoreError>>,
    },
    StartPixivPage {
        request: PixivPageFetchRequest,
        reply: oneshot::Sender<Result<OperationSnapshot, CoreError>>,
    },
    StartEhPage {
        request: EhPageFetchRequest,
        reply: oneshot::Sender<Result<OperationSnapshot, CoreError>>,
    },
    GetOperation {
        id: OperationId,
        reply: oneshot::Sender<Result<OperationSnapshot, CoreError>>,
    },
    ListOperations {
        reply: oneshot::Sender<Vec<OperationSnapshot>>,
    },
    CancelOperation {
        id: OperationId,
        reply: oneshot::Sender<Result<OperationSnapshot, CoreError>>,
    },
    EventsAfter {
        cursor: u64,
        reply: oneshot::Sender<EventBatch>,
    },
    SubscribeEvents {
        cursor: u64,
        reply: oneshot::Sender<Result<EventSubscription, CoreError>>,
    },
    ReplaceProfile {
        config: Box<ProviderProfileConfig>,
        reply: oneshot::Sender<Result<ProfileSnapshot, CoreError>>,
    },
}

struct RuntimeData {
    id: RuntimeId,
    config: CoreConfig,
    started_at: Instant,
    state: RuntimeState,
    revision: u64,
    control_listen: Option<std::net::SocketAddr>,
    storage: StorageSnapshot,
    operations: OperationService,
    sessions: Arc<SessionRegistry>,
}

impl RuntimeData {
    fn snapshot(&self, queued_commands: usize) -> CoreSnapshot {
        let (active, queued, retained, latest_sequence) = self.operations.counts();
        let profiles = self.sessions.snapshots().unwrap_or_default();
        CoreSnapshot {
            runtime_id: self.id,
            instance_name: self.config.instance_name.clone(),
            state: self.state,
            revision: self.revision,
            uptime_seconds: self.started_at.elapsed().as_secs(),
            control_enabled: self.control_listen.is_some(),
            control_listen: self.control_listen.map(|listen| listen.to_string()),
            queued_commands,
            storage: self.storage.clone(),
            active_operations: active,
            queued_operations: queued,
            retained_operations: retained,
            latest_event_sequence: latest_sequence,
            profiles,
        }
    }
}

/// Builder used by executables and embedding applications.
pub struct CoreBuilder {
    config: CoreConfig,
}

impl CoreBuilder {
    /// Creates a builder for an already materialized configuration.
    #[must_use]
    pub fn new(config: CoreConfig) -> Self {
        Self { config }
    }

    /// Validates configuration and starts the supervised Runtime actor.
    pub async fn build(self) -> Result<CoreRuntime, CoreError> {
        self.config.validate()?;
        let command_capacity = self.config.command_capacity;
        let shutdown_seconds = self.config.shutdown_seconds;
        let control_config = self.config.control.clone();
        let operation_config = self.config.operations.clone();
        let event_config = self.config.events.clone();
        let storage = StorageService::open(&self.config.storage)?;
        let storage_snapshot = storage.snapshot()?;
        let cache_path = storage.cache_path();
        let downloads_path = storage.downloads_path();
        let sessions = Arc::new(SessionRegistry::new(
            &self.config.profiles,
            &self.config.network,
        )?);
        let (command_tx, command_rx) = mpsc::channel(command_capacity);
        let (message_tx, message_rx) = mpsc::channel(command_capacity);
        let (state_tx, state_rx) = watch::channel(RuntimeState::Starting);
        let shutdown = CancellationToken::new();
        let actor_shutdown = shutdown.clone();
        let runtime_id = RuntimeId::new();
        let images = ImageService::new(self.config.images.clone(), cache_path, sessions.clone())?;
        let archives = ArchiveService::open(
            downloads_path.clone(),
            sessions.clone(),
            shutdown.child_token(),
            message_tx.clone(),
        )
        .await?;
        let galleries = GalleryService::open(
            downloads_path,
            archives.clone(),
            storage.gallery_registry(),
            self.config.images.max_image_bytes,
            self.config.images.max_inflight_bytes,
        )
        .await?;
        let data = RuntimeData {
            id: runtime_id,
            config: self.config,
            started_at: Instant::now(),
            state: RuntimeState::Starting,
            revision: 0,
            control_listen: None,
            storage: storage_snapshot,
            operations: OperationService::new(
                runtime_id,
                operation_config,
                &event_config,
                message_tx,
                sessions.clone(),
                images.clone(),
            ),
            sessions: sessions.clone(),
        };
        let mut actor = tokio::spawn(run_actor(
            data,
            command_rx,
            message_rx,
            state_tx,
            actor_shutdown,
        ));
        let handle = CoreHandle {
            command_tx,
            state_rx,
            shutdown: shutdown.clone(),
            shutdown_seconds,
            sessions,
            images,
            archives,
            galleries,
        };
        handle.wait_ready().await?;
        let control = if control_config.enabled {
            match control::start(
                control_config.listen,
                control_config.webui_enabled,
                handle.clone(),
                shutdown.clone(),
            )
            .await
            {
                Ok(server) => Some(server),
                Err(error) => {
                    shutdown.cancel();
                    let _ = (&mut actor).await;
                    return Err(error);
                }
            }
        } else {
            None
        };
        if let Some(server) = &control {
            if let Err(error) = handle.set_control_listen(server.listen).await {
                shutdown.cancel();
                if let Some(server) = control {
                    let _ = server.task.await;
                }
                let _ = (&mut actor).await;
                return Err(error);
            }
        }
        Ok(CoreRuntime {
            handle,
            shutdown,
            actor: Some(actor),
            control,
            storage: Some(storage),
        })
    }
}

/// Cloneable embedded interface to one Runtime.
#[derive(Clone)]
pub struct CoreHandle {
    command_tx: mpsc::Sender<CoreCommand>,
    state_rx: watch::Receiver<RuntimeState>,
    shutdown: CancellationToken,
    shutdown_seconds: u64,
    sessions: Arc<SessionRegistry>,
    images: Arc<ImageService>,
    archives: Arc<ArchiveService>,
    galleries: Arc<GalleryService>,
}

impl CoreHandle {
    /// Returns an immutable Runtime snapshot.
    pub async fn snapshot(&self) -> Result<CoreSnapshot, CoreError> {
        let (reply, response) = oneshot::channel();
        self.command_tx
            .try_send(CoreCommand::Snapshot { reply })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => {
                    CoreError::new(ErrorCode::Overloaded, "runtime command queue is full", true)
                }
                mpsc::error::TrySendError::Closed(_) => CoreError::new(
                    ErrorCode::NotReady,
                    "runtime is not accepting commands",
                    false,
                ),
            })?;
        response.await.map_err(|_| {
            CoreError::new(
                ErrorCode::Internal,
                "runtime dropped the snapshot response",
                false,
            )
        })
    }

    /// Returns the effective configuration without secret or proxy values.
    pub async fn effective_config(&self) -> Result<crate::EffectiveConfigSnapshot, CoreError> {
        self.request(|reply| CoreCommand::EffectiveConfig { reply })
            .await
    }

    /// Requests graceful shutdown without waiting for completion.
    pub fn request_shutdown(&self) {
        self.shutdown.cancel();
    }

    /// Returns the last observed lifecycle state.
    #[must_use]
    pub fn state(&self) -> RuntimeState {
        *self.state_rx.borrow()
    }

    /// Starts a deterministic fake operation for Foundation validation.
    pub async fn start_fake_operation(
        &self,
        request: FakeOperationRequest,
    ) -> Result<OperationSnapshot, CoreError> {
        self.request(|reply| CoreCommand::StartFake { request, reply })
            .await?
    }

    /// Starts a cancellable fetch for one Provider-declared Booru original.
    pub async fn start_booru_original_fetch(
        &self,
        request: BooruOriginalFetchRequest,
    ) -> Result<OperationSnapshot, CoreError> {
        self.request(|reply| CoreCommand::StartBooruOriginal { request, reply })
            .await?
    }

    /// Fetches Pixiv illustration detail and page metadata through the shared profile.
    pub async fn pixiv_illust(
        &self,
        key: &ProfileKey,
        illust_id: &str,
    ) -> Result<crate::PixivIllust, CoreError> {
        crate::provider::pixiv::PixivService::new(self.sessions.clone())
            .illust(key, illust_id, self.shutdown.child_token())
            .await
    }

    /// Starts a cancellable original image fetch for one Pixiv illustration page.
    pub async fn start_pixiv_page_fetch(
        &self,
        request: PixivPageFetchRequest,
    ) -> Result<OperationSnapshot, CoreError> {
        self.request(|reply| CoreCommand::StartPixivPage { request, reply })
            .await?
    }

    /// Starts a cancellable original-image fetch for one EH gallery page.
    pub async fn start_eh_page_fetch(
        &self,
        request: EhPageFetchRequest,
    ) -> Result<OperationSnapshot, CoreError> {
        self.request(|reply| CoreCommand::StartEhPage { request, reply })
            .await?
    }

    /// Creates and starts one persistent EH Archive task after explicit caller authorization.
    pub async fn start_eh_archive_download(
        &self,
        request: EhArchiveDownloadRequest,
    ) -> Result<ArchiveTaskSnapshot, CoreError> {
        self.archives.start(request).await
    }

    /// Returns all persistent EH Archive task snapshots in creation order.
    pub async fn archive_tasks(&self) -> Vec<ArchiveTaskSnapshot> {
        self.archives.list().await
    }

    /// Returns one persistent EH Archive task snapshot.
    pub async fn archive_task(&self, id: uuid::Uuid) -> Result<ArchiveTaskSnapshot, CoreError> {
        self.archives.get(id).await
    }

    /// Cancels one active EH Archive task without deleting its resumable part file.
    pub async fn cancel_archive_task(
        &self,
        id: uuid::Uuid,
    ) -> Result<ArchiveTaskSnapshot, CoreError> {
        self.archives.cancel(id).await
    }

    /// Retries a failed EH Archive download using only its durable, unexpired signed URL.
    pub async fn retry_archive_task(
        &self,
        id: uuid::Uuid,
    ) -> Result<ArchiveTaskSnapshot, CoreError> {
        self.archives.retry(id).await
    }

    /// Returns committed local galleries after idempotently consuming completed Archive tasks.
    pub async fn local_galleries(&self) -> Result<Vec<crate::LocalGallerySummary>, CoreError> {
        self.galleries.consume_pending().await;
        self.galleries.list().await
    }

    /// Returns safe metadata and naturally sorted pages for one local gallery ZIP.
    pub async fn local_gallery(
        &self,
        id: uuid::Uuid,
        offset: u32,
        limit: u32,
    ) -> Result<crate::LocalGalleryDetail, CoreError> {
        self.galleries.consume_pending().await;
        self.galleries.detail(id, offset, limit).await
    }

    /// Extracts one bounded immutable image page from a local gallery ZIP.
    pub async fn local_gallery_page(
        &self,
        id: uuid::Uuid,
        page_id: u32,
    ) -> Result<crate::LocalGalleryResource, CoreError> {
        self.galleries.page(id, page_id).await
    }

    /// Returns one bounded immutable cover image from a local gallery.
    pub async fn local_gallery_cover(
        &self,
        id: uuid::Uuid,
    ) -> Result<crate::LocalGalleryResource, CoreError> {
        self.galleries.cover(id).await
    }

    /// Opens a bounded stream for one local gallery's unchanged original ZIP.
    pub async fn local_gallery_export(
        &self,
        id: uuid::Uuid,
    ) -> Result<crate::LocalGalleryExport, CoreError> {
        self.galleries.export(id).await
    }

    /// Scans every managed local gallery and reports registration and integrity status.
    pub async fn local_gallery_inventory(&self) -> Result<crate::LocalGalleryInventory, CoreError> {
        self.galleries.inventory().await
    }

    /// Registers one healthy scan candidate by gallery ID without accepting a caller path.
    pub async fn import_local_gallery(
        &self,
        id: uuid::Uuid,
    ) -> Result<crate::LocalGallerySummary, CoreError> {
        self.galleries.import(id).await
    }

    /// Deterministically creates or replaces a local gallery's derived `ComicInfo.xml`.
    pub async fn generate_local_gallery_comic_info(
        &self,
        id: uuid::Uuid,
    ) -> Result<crate::ComicInfoSnapshot, CoreError> {
        self.galleries.generate_comic_info(id).await
    }

    /// Deletes a derived `ComicInfo.xml` without changing its authoritative ZIP or JSON inputs.
    pub async fn delete_local_gallery_comic_info(&self, id: uuid::Uuid) -> Result<(), CoreError> {
        self.galleries.delete_comic_info(id).await
    }

    /// Previews a local gallery deletion and returns a short-lived one-use confirmation token.
    pub async fn prepare_local_gallery_delete(
        &self,
        id: uuid::Uuid,
    ) -> Result<crate::LocalGalleryDeleteConfirmation, CoreError> {
        self.galleries.prepare_delete(id).await
    }

    /// Permanently deletes a local gallery after an unchanged preview is explicitly confirmed.
    pub async fn delete_local_gallery(
        &self,
        id: uuid::Uuid,
        request: crate::LocalGalleryDeleteRequest,
    ) -> Result<crate::LocalGalleryDeleteResult, CoreError> {
        self.galleries.delete(id, request).await
    }

    /// Returns immutable image bytes by their verified content address.
    pub async fn image_resource(
        &self,
        md5: ContentMd5,
        extension: &str,
    ) -> Result<ImageResource, CoreError> {
        self.images.resource(md5, extension).await
    }

    /// Returns one operation snapshot.
    pub async fn operation(&self, id: OperationId) -> Result<OperationSnapshot, CoreError> {
        self.request(|reply| CoreCommand::GetOperation { id, reply })
            .await?
    }

    /// Lists active and retained terminal operations.
    pub async fn operations(&self) -> Result<Vec<OperationSnapshot>, CoreError> {
        self.request(|reply| CoreCommand::ListOperations { reply })
            .await
    }

    /// Cooperatively cancels a queued or running operation.
    pub async fn cancel_operation(&self, id: OperationId) -> Result<OperationSnapshot, CoreError> {
        self.request(|reply| CoreCommand::CancelOperation { id, reply })
            .await?
    }

    /// Replays retained events after the provided sequence cursor.
    pub async fn events_after(&self, cursor: u64) -> Result<EventBatch, CoreError> {
        self.request(|reply| CoreCommand::EventsAfter { cursor, reply })
            .await
    }

    /// Subscribes to retained and future events after a sequence cursor.
    pub async fn subscribe_events(&self, cursor: u64) -> Result<EventSubscription, CoreError> {
        self.request(|reply| CoreCommand::SubscribeEvents { cursor, reply })
            .await?
    }

    /// Returns safe snapshots of all configured Provider session generations.
    pub fn profiles(&self) -> Result<Vec<ProfileSnapshot>, CoreError> {
        self.sessions.snapshots()
    }

    /// Replaces one profile with a new immutable session generation.
    pub async fn replace_profile(
        &self,
        config: ProviderProfileConfig,
    ) -> Result<ProfileSnapshot, CoreError> {
        self.request(|reply| CoreCommand::ReplaceProfile {
            config: Box::new(config),
            reply,
        })
        .await?
    }

    /// Probes the configured root of one Provider profile with bounded response buffering.
    pub async fn probe_profile(&self, key: &ProfileKey) -> Result<ProfileProbeSnapshot, CoreError> {
        self.sessions.probe(key, self.shutdown.child_token()).await
    }

    /// Searches one Danbooru profile through its public JSON API.
    pub async fn search_danbooru(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u64,
        limit: u32,
    ) -> Result<crate::BooruSearchResult, CoreError> {
        BooruService::new(self.sessions.clone())
            .search_danbooru(key, query, page, limit, self.shutdown.child_token())
            .await
    }

    /// Fetches one Danbooru post through its public JSON API.
    pub async fn danbooru_post(
        &self,
        key: &ProfileKey,
        post_id: u64,
    ) -> Result<crate::BooruPost, CoreError> {
        BooruService::new(self.sessions.clone())
            .get_danbooru_post(key, post_id, self.shutdown.child_token())
            .await
    }

    /// Searches one Gelbooru profile through its public JSON DAPI.
    pub async fn search_gelbooru(
        &self,
        key: &ProfileKey,
        query: &str,
        page: u64,
        limit: u32,
    ) -> Result<crate::BooruSearchResult, CoreError> {
        BooruService::new(self.sessions.clone())
            .search_gelbooru(key, query, page, limit, self.shutdown.child_token())
            .await
    }

    /// Fetches one Gelbooru post through its public JSON DAPI.
    pub async fn gelbooru_post(
        &self,
        key: &ProfileKey,
        post_id: u64,
    ) -> Result<crate::BooruPost, CoreError> {
        BooruService::new(self.sessions.clone())
            .get_gelbooru_post(key, post_id, self.shutdown.child_token())
            .await
    }

    /// Fetches one EH front-page listing using the shared profile session.
    pub async fn eh_home(
        &self,
        key: &ProfileKey,
        cursor: Option<crate::EhPageCursor>,
    ) -> Result<crate::EhHomePage, CoreError> {
        EhService::new(self.sessions.clone())
            .home(key, cursor, self.shutdown.child_token())
            .await
    }

    /// Fetches parsed metadata for one EH gallery using the shared profile session.
    pub async fn eh_gallery_detail(
        &self,
        key: &ProfileKey,
        gallery: crate::EhGalleryRef,
    ) -> Result<crate::EhGalleryDetail, CoreError> {
        EhService::new(self.sessions.clone())
            .gallery_detail(key, gallery, self.shutdown.child_token())
            .await
    }

    /// Fetches one zero-based page of EH gallery thumbnails.
    pub async fn eh_thumbnails(
        &self,
        key: &ProfileKey,
        gallery: crate::EhGalleryRef,
        page: u32,
    ) -> Result<crate::EhThumbnailPage, CoreError> {
        EhService::new(self.sessions.clone())
            .thumbnails(key, gallery, page, self.shutdown.child_token())
            .await
    }

    /// Resolves the remote original-image URL and reload nonce for one EH gallery page.
    pub async fn eh_resolve_original(
        &self,
        key: &ProfileKey,
        gallery: crate::EhGalleryRef,
        page: u32,
        nl: Option<&str>,
    ) -> Result<crate::EhImageResolution, CoreError> {
        EhService::new(self.sessions.clone())
            .resolve_original(key, gallery, page, nl, self.shutdown.child_token())
            .await
    }

    /// Lists official Archive options for one EH gallery using the shared profile session.
    pub async fn eh_archive_options(
        &self,
        key: &ProfileKey,
        gallery: crate::EhGalleryRef,
    ) -> Result<crate::EhArchiveOptions, CoreError> {
        EhService::new(self.sessions.clone())
            .archive_options(key, gallery, self.shutdown.child_token())
            .await
    }

    async fn request<T>(
        &self,
        command: impl FnOnce(oneshot::Sender<T>) -> CoreCommand,
    ) -> Result<T, CoreError> {
        let (reply, response) = oneshot::channel();
        self.command_tx
            .try_send(command(reply))
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => {
                    CoreError::new(ErrorCode::Overloaded, "runtime command queue is full", true)
                }
                mpsc::error::TrySendError::Closed(_) => CoreError::new(
                    ErrorCode::NotReady,
                    "runtime is not accepting commands",
                    false,
                ),
            })?;
        response.await.map_err(|_| {
            CoreError::new(
                ErrorCode::Internal,
                "runtime dropped a command response",
                false,
            )
        })
    }

    async fn wait_ready(&self) -> Result<(), CoreError> {
        let mut states = self.state_rx.clone();
        loop {
            match *states.borrow_and_update() {
                RuntimeState::Ready => return Ok(()),
                RuntimeState::Stopping | RuntimeState::Stopped => {
                    return Err(CoreError::new(
                        ErrorCode::NotReady,
                        "runtime stopped during initialization",
                        false,
                    ));
                }
                RuntimeState::Starting => {}
            }
            states.changed().await.map_err(|_| {
                CoreError::new(
                    ErrorCode::Internal,
                    "runtime state channel closed during initialization",
                    false,
                )
            })?;
        }
    }

    async fn set_control_listen(&self, listen: std::net::SocketAddr) -> Result<(), CoreError> {
        let (reply, response) = oneshot::channel();
        self.command_tx
            .send(CoreCommand::SetControlListen { listen, reply })
            .await
            .map_err(|_| {
                CoreError::new(
                    ErrorCode::NotReady,
                    "runtime stopped while publishing HTTP control address",
                    false,
                )
            })?;
        response.await.map_err(|_| {
            CoreError::new(
                ErrorCode::Internal,
                "runtime dropped the HTTP control address response",
                false,
            )
        })
    }
}

/// Owner of all supervised Core services.
pub struct CoreRuntime {
    handle: CoreHandle,
    shutdown: CancellationToken,
    actor: Option<JoinHandle<()>>,
    control: Option<control::ControlServer>,
    storage: Option<StorageService>,
}

impl CoreRuntime {
    /// Returns a cloneable handle for commands and queries.
    #[must_use]
    pub fn handle(&self) -> CoreHandle {
        self.handle.clone()
    }

    /// Returns the actual HTTP listen address, including an assigned port.
    #[must_use]
    pub fn control_listen(&self) -> Option<std::net::SocketAddr> {
        self.control.as_ref().map(|server| server.listen)
    }

    /// Gracefully stops the Runtime and waits for its actor to finish.
    pub async fn shutdown(mut self) -> Result<(), CoreError> {
        self.shutdown.cancel();
        let deadline = Duration::from_secs(self.handle.shutdown_seconds);
        let started = Instant::now();
        let mut timed_out = false;
        if let Some(control) = self.control.take() {
            let mut task = control.task;
            let remaining = deadline.saturating_sub(started.elapsed());
            match tokio::time::timeout(remaining, &mut task).await {
                Ok(result) => result.map_err(|_| {
                    CoreError::new(ErrorCode::Internal, "HTTP control task panicked", false)
                })?,
                Err(_) => {
                    task.abort();
                    let _ = task.await;
                    timed_out = true;
                }
            }
        }
        if let Some(actor) = self.actor.take() {
            let mut actor = actor;
            let remaining = deadline.saturating_sub(started.elapsed());
            match tokio::time::timeout(remaining, &mut actor).await {
                Ok(result) => result.map_err(|_| {
                    CoreError::new(ErrorCode::Internal, "runtime actor panicked", false)
                })?,
                Err(_) => {
                    actor.abort();
                    let _ = actor.await;
                    timed_out = true;
                }
            }
        }
        let remaining = deadline.saturating_sub(started.elapsed());
        if let Err(error) = self.handle.archives.shutdown(remaining).await {
            tracing::warn!(%error, "Archive service did not stop cleanly");
            timed_out = true;
        }
        let remaining = deadline.saturating_sub(started.elapsed());
        if let Err(error) = self.handle.images.shutdown(remaining).await {
            tracing::warn!(%error, "image service did not drain cleanly");
            timed_out = true;
        }
        self.storage.take();
        if timed_out {
            Err(CoreError::new(
                ErrorCode::DeadlineExceeded,
                "Runtime shutdown deadline exceeded",
                false,
            ))
        } else {
            Ok(())
        }
    }
}

impl Drop for CoreRuntime {
    fn drop(&mut self) {
        self.shutdown.cancel();
    }
}

async fn run_actor(
    mut data: RuntimeData,
    mut commands: mpsc::Receiver<CoreCommand>,
    mut messages: mpsc::Receiver<OperationMessage>,
    states: watch::Sender<RuntimeState>,
    shutdown: CancellationToken,
) {
    data.state = RuntimeState::Ready;
    data.revision += 1;
    states.send_replace(RuntimeState::Ready);

    loop {
        tokio::select! {
            biased;
            () = shutdown.cancelled() => break,
            command = commands.recv() => match command {
                Some(CoreCommand::Snapshot { reply }) => {
                    let _ = reply.send(data.snapshot(commands.len()));
                }
                Some(CoreCommand::EffectiveConfig { reply }) => {
                    let profiles = data.sessions.snapshots().unwrap_or_default();
                    let _ = reply.send(data.config.effective_snapshot(data.storage.clone(), &profiles));
                }
                Some(CoreCommand::SetControlListen { listen, reply }) => {
                    data.control_listen = Some(listen);
                    data.revision += 1;
                    let _ = reply.send(());
                }
                Some(CoreCommand::StartFake { request, reply }) => {
                    let _ = reply.send(data.operations.start_fake(request, &shutdown));
                }
                Some(CoreCommand::StartBooruOriginal { request, reply }) => {
                    let _ = reply.send(data.operations.start_booru_original(request, &shutdown));
                }
                Some(CoreCommand::StartPixivPage { request, reply }) => {
                    let _ = reply.send(data.operations.start_pixiv_page(request, &shutdown));
                }
                Some(CoreCommand::StartEhPage { request, reply }) => {
                    let _ = reply.send(data.operations.start_eh_page(request, &shutdown));
                }
                Some(CoreCommand::GetOperation { id, reply }) => {
                    let _ = reply.send(data.operations.get(id));
                }
                Some(CoreCommand::ListOperations { reply }) => {
                    let _ = reply.send(data.operations.list());
                }
                Some(CoreCommand::CancelOperation { id, reply }) => {
                    let _ = reply.send(data.operations.cancel(id));
                }
                Some(CoreCommand::EventsAfter { cursor, reply }) => {
                    let _ = reply.send(data.operations.events_after(cursor));
                }
                Some(CoreCommand::SubscribeEvents { cursor, reply }) => {
                    let batch = data.operations.events_after(cursor);
                    let result = if batch.resync_required {
                        Err(CoreError::new(
                            ErrorCode::NotReady,
                            "event cursor is no longer retained; resync from snapshots",
                            true,
                        ))
                    } else {
                        Ok(EventSubscription::new(
                            batch.events,
                            data.operations.subscribe(),
                        ))
                    };
                    let _ = reply.send(result);
                }
                Some(CoreCommand::ReplaceProfile { config, reply }) => {
                    let config = *config;
                    let result = data
                        .sessions
                        .replace(config.clone(), data.config.network.clone());
                    if result.is_ok() {
                        if let Some((_, current)) = data.config.profiles.iter_mut().find(|(_, current)| {
                            current.provider == config.provider && current.profile == config.profile
                        }) {
                            *current = config;
                        } else {
                            data.config.profiles.insert(
                                format!("{}/{}", config.provider, config.profile),
                                config,
                            );
                        }
                        data.revision += 1;
                    }
                    let _ = reply.send(result);
                }
                None => break,
            },
            message = messages.recv() => if let Some(message) = message {
                match message {
                    OperationMessage::Progress { id, progress } => data.operations.progress(id, progress),
                    OperationMessage::Completion { id, result } => {
                        data.operations.complete(OperationCompletion { id, result });
                    }
                    OperationMessage::ArchiveTask(task) => data.operations.archive_event(task),
                }
            },
        }
    }

    data.state = RuntimeState::Stopping;
    data.revision += 1;
    states.send_replace(RuntimeState::Stopping);
    data.state = RuntimeState::Stopped;
    data.revision += 1;
    states.send_replace(RuntimeState::Stopped);
}

#[cfg(test)]
mod tests {
    use super::CoreBuilder;
    use crate::{
        BooruOriginalFetchRequest, ContentMd5, CoreConfig, EhPageFetchRequest, ErrorCode,
        EventConfig, FakeOperationRequest, OperationConfig, OperationState, PixivPageFetchRequest,
        ProfileKey, ProviderProfileConfig, ResourceSource, RuntimeState, StorageConfig,
    };
    use md5::{Digest, Md5};
    use std::{
        str::FromStr,
        sync::{
            Arc,
            atomic::{AtomicUsize, Ordering},
        },
        time::Duration,
    };
    use tempfile::TempDir;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use url::Url;

    fn config(temp: &TempDir) -> CoreConfig {
        CoreConfig {
            storage: StorageConfig {
                data: temp.path().join("Data"),
                cache: temp.path().join("Cache"),
                downloads: temp.path().join("Downloads"),
                temp: temp.path().join("Temp"),
            },
            ..CoreConfig::default()
        }
    }

    async fn wait_terminal(
        handle: &super::CoreHandle,
        id: crate::OperationId,
    ) -> crate::OperationSnapshot {
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                let snapshot = handle.operation(id).await.unwrap();
                if snapshot.state.is_terminal() {
                    return snapshot;
                }
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap()
    }

    async fn http_request(listen: std::net::SocketAddr, request: &[u8]) -> Vec<u8> {
        let mut stream = tokio::net::TcpStream::connect(listen).await.unwrap();
        stream.write_all(request).await.unwrap();
        let mut response = Vec::new();
        stream.read_to_end(&mut response).await.unwrap();
        response
    }

    fn test_jpeg() -> Vec<u8> {
        let mut bytes = b"\xff\xd8\xff\xe0JFIF\0".to_vec();
        bytes.extend(std::iter::repeat_n(0x5a, 128 * 1024));
        bytes.extend_from_slice(b"\xff\xd9");
        bytes
    }

    fn test_zip() -> Vec<u8> {
        let mut cursor = std::io::Cursor::new(Vec::new());
        {
            let mut zip = zip::ZipWriter::new(&mut cursor);
            zip.start_file("10.jpg", zip::write::SimpleFileOptions::default())
                .unwrap();
            std::io::Write::write_all(&mut zip, &test_jpeg()).unwrap();
            zip.start_file("2.png", zip::write::SimpleFileOptions::default())
                .unwrap();
            std::io::Write::write_all(&mut zip, b"\x89PNG\r\n\x1a\nfixture").unwrap();
            zip.start_file("../hidden.jpg", zip::write::SimpleFileOptions::default())
                .unwrap();
            std::io::Write::write_all(&mut zip, &test_jpeg()).unwrap();
            zip.finish().unwrap();
        }
        cursor.into_inner()
    }

    fn md5_hex(bytes: &[u8]) -> String {
        format!("{:x}", Md5::digest(bytes))
    }

    async fn image_provider(
        image: Arc<Vec<u8>>,
        declared_md5: String,
        requests: Arc<AtomicUsize>,
    ) -> std::net::SocketAddr {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let listen = listener.local_addr().unwrap();
        let router = axum::Router::new()
            .route(
                "/posts/{file}",
                axum::routing::get({
                    let declared_md5 = declared_md5.clone();
                    let image_bytes = image.len();
                    move |axum::extract::Path(file): axum::extract::Path<String>| {
                        let declared_md5 = declared_md5.clone();
                        async move {
                            let post_id = file.trim_end_matches(".json").parse::<u64>().unwrap();
                            axum::Json(serde_json::json!({
                                "id": post_id,
                                "md5": declared_md5,
                                "file_ext": "jpeg",
                                "file_size": image_bytes,
                                "file_url": format!("http://{listen}/images/{post_id}.jpeg")
                            }))
                        }
                    }
                }),
            )
            .route(
                "/images/{file}",
                axum::routing::get({
                    let image = image.clone();
                    move || {
                        let image = image.clone();
                        let requests = requests.clone();
                        async move {
                            requests.fetch_add(1, Ordering::SeqCst);
                            tokio::time::sleep(Duration::from_millis(30)).await;
                            (
                                [(axum::http::header::CONTENT_TYPE, "image/jpeg")],
                                image.as_ref().clone(),
                            )
                        }
                    }
                }),
            );
        tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
        listen
    }

    fn danbooru_profile(listen: std::net::SocketAddr) -> ProviderProfileConfig {
        ProviderProfileConfig {
            provider: "danbooru".to_owned(),
            base_url: Url::parse(&format!("http://{listen}/")).unwrap(),
            ..ProviderProfileConfig::default()
        }
    }

    async fn pixiv_provider(
        image: Arc<Vec<u8>>,
        requests: Arc<AtomicUsize>,
    ) -> std::net::SocketAddr {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let listen = listener.local_addr().unwrap();
        let router = axum::Router::new()
            .route(
                "/ajax/illust/{illust_id}",
                axum::routing::get(
                    |axum::extract::Path(illust_id): axum::extract::Path<String>,
                     headers: axum::http::HeaderMap| async move {
                        assert_eq!(
                            headers
                                .get("x-requested-with")
                                .and_then(|value| value.to_str().ok()),
                            Some("XMLHttpRequest")
                        );
                        axum::Json(serde_json::json!({
                            "error": false,
                            "message": "",
                            "body": {
                                "id": illust_id,
                                "title": "Local Pixiv fixture",
                                "description": "fixture",
                                "illustType": 0,
                                "pageCount": 1,
                                "width": 1200,
                                "height": 1800,
                                "userId": "42",
                                "userName": "Artist",
                                "tags": {"tags": [{"tag": "test"}]}
                            }
                        }))
                    },
                ),
            )
            .route(
                "/ajax/illust/{illust_id}/pages",
                axum::routing::get(move |headers: axum::http::HeaderMap| async move {
                    assert!(
                        headers
                            .get(axum::http::header::REFERER)
                            .and_then(|value| value.to_str().ok())
                            .is_some_and(|value| value.contains("/artworks/12345678"))
                    );
                    axum::Json(serde_json::json!({
                        "error": false,
                        "message": "",
                        "body": [{
                            "urls": {
                                "original": format!("http://{listen}/image.jpg")
                            }
                        }]
                    }))
                }),
            )
            .route(
                "/image.jpg",
                axum::routing::get(move |headers: axum::http::HeaderMap| {
                    let image = image.clone();
                    let requests = requests.clone();
                    async move {
                        assert!(
                            headers
                                .get(axum::http::header::REFERER)
                                .and_then(|value| value.to_str().ok())
                                .is_some_and(|value| value.contains("/artworks/12345678"))
                        );
                        requests.fetch_add(1, Ordering::SeqCst);
                        tokio::time::sleep(Duration::from_millis(30)).await;
                        (
                            [(axum::http::header::CONTENT_TYPE, "image/jpeg")],
                            image.as_ref().clone(),
                        )
                    }
                }),
            );
        tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
        listen
    }

    fn pixiv_profile(listen: std::net::SocketAddr) -> ProviderProfileConfig {
        ProviderProfileConfig {
            provider: "pixiv".to_owned(),
            base_url: Url::parse(&format!("http://{listen}/")).unwrap(),
            ..ProviderProfileConfig::default()
        }
    }

    #[tokio::test]
    async fn starts_queries_and_stops() {
        let temp = TempDir::new().unwrap();
        let runtime = CoreBuilder::new(config(&temp)).build().await.unwrap();
        let handle = runtime.handle();
        let snapshot = handle.snapshot().await.unwrap();
        assert_eq!(snapshot.state, RuntimeState::Ready);
        runtime.shutdown().await.unwrap();
        assert_eq!(handle.state(), RuntimeState::Stopped);
    }

    #[tokio::test]
    async fn serves_integrated_http_status() {
        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config.control.enabled = true;
        config.control.listen = "127.0.0.1:0".parse().unwrap();
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let listen = runtime.control_listen().unwrap();
        assert_ne!(listen.port(), 0);
        let snapshot = runtime.handle().snapshot().await.unwrap();
        assert_eq!(
            snapshot.control_listen.as_deref(),
            Some(listen.to_string().as_str())
        );

        let mut stream = tokio::net::TcpStream::connect(listen).await.unwrap();
        stream
            .write_all(
                b"GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await
            .unwrap();
        let mut response = Vec::new();
        stream.read_to_end(&mut response).await.unwrap();
        let response = String::from_utf8(response).unwrap();
        assert!(response.starts_with("HTTP/1.1 200 OK"));
        assert!(response.ends_with("ready\n"));

        let body = r#"{"duration_ms":10,"outcome":"succeed"}"#;
        let mut stream = tokio::net::TcpStream::connect(listen).await.unwrap();
        let request = format!(
            "POST /api/v1/operations HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        stream.write_all(request.as_bytes()).await.unwrap();
        let mut response = Vec::new();
        stream.read_to_end(&mut response).await.unwrap();
        let response = String::from_utf8(response).unwrap();
        assert!(response.starts_with("HTTP/1.1 202 Accepted"));
        assert!(response.contains("\"kind\":\"fake\""));
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn webui_can_be_disabled_without_disabling_the_control_api() {
        let temp = TempDir::new().unwrap();
        let mut core_config = config(&temp);
        core_config.control.enabled = true;
        core_config.control.webui_enabled = false;
        core_config.control.listen = "127.0.0.1:0".parse().unwrap();
        let runtime = CoreBuilder::new(core_config).build().await.unwrap();
        let listen = runtime.control_listen().unwrap();
        let root = http_request(
            listen,
            b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        )
        .await;
        assert!(
            String::from_utf8(root)
                .unwrap()
                .starts_with("HTTP/1.1 404 Not Found")
        );
        let api = http_request(
            listen,
            b"GET /api/v1/runtime HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        )
        .await;
        assert!(
            String::from_utf8(api)
                .unwrap()
                .starts_with("HTTP/1.1 200 OK")
        );
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn dashboard_contains_runtime_storage_profiles_and_operations() {
        let temp = TempDir::new().unwrap();
        let mut core_config = config(&temp);
        core_config.instance_name = "dashboard <test>".to_owned();
        core_config.control.enabled = true;
        core_config.control.listen = "127.0.0.1:0".parse().unwrap();
        core_config.profiles.insert(
            "danbooru".to_owned(),
            ProviderProfileConfig {
                provider: "danbooru".to_owned(),
                ..ProviderProfileConfig::default()
            },
        );
        let runtime = CoreBuilder::new(core_config).build().await.unwrap();
        let operation = runtime
            .handle()
            .start_fake_operation(FakeOperationRequest {
                duration_ms: 1,
                ..FakeOperationRequest::default()
            })
            .await
            .unwrap();
        wait_terminal(&runtime.handle(), operation.id).await;
        let response = http_request(
            runtime.control_listen().unwrap(),
            b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        )
        .await;
        let response = String::from_utf8(response).unwrap();
        assert!(response.starts_with("HTTP/1.1 200 OK"));
        assert!(response.contains("dashboard &lt;test&gt;"));
        assert!(response.contains("<html lang=\"zh-CN\">"));
        assert!(response.contains("<h2>存储</h2>"));
        assert!(response.contains("<h2>Provider 会话</h2>"));
        assert!(response.contains("danbooru/default"));
        assert!(response.contains("<h2>Booru 搜索</h2>"));
        assert!(response.contains("<h2>EH 主页</h2>"));
        assert!(response.contains("<h2>最近操作</h2>"));
        assert!(response.contains(&operation.id.to_string()));
        assert!(response.contains("<meta http-equiv=\"refresh\" content=\"5\">"));
        assert!(response.contains("每 5 秒自动刷新"));
        assert!(response.contains("立即刷新"));
        assert!(!response.contains("Runtime JSON"));
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn webui_refreshes_only_nonterminal_operation_views() {
        let temp = TempDir::new().unwrap();
        let mut core_config = config(&temp);
        core_config.control.enabled = true;
        core_config.control.listen = "127.0.0.1:0".parse().unwrap();
        let runtime = CoreBuilder::new(core_config).build().await.unwrap();
        let operation = runtime
            .handle()
            .start_fake_operation(FakeOperationRequest {
                duration_ms: 10_000,
                ..FakeOperationRequest::default()
            })
            .await
            .unwrap();
        let listen = runtime.control_listen().unwrap();
        let list = String::from_utf8(
            http_request(
                listen,
                b"GET /ui/operations HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(list.contains("<meta http-equiv=\"refresh\" content=\"2\">"));
        assert!(list.contains("每 2 秒自动刷新"));
        let request = format!(
            "GET /ui/operation?id={} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            operation.id
        );
        let detail = String::from_utf8(http_request(listen, request.as_bytes()).await).unwrap();
        assert!(detail.contains("<meta http-equiv=\"refresh\" content=\"1\">"));
        assert!(detail.contains("每 1 秒自动刷新"));

        runtime
            .handle()
            .cancel_operation(operation.id)
            .await
            .unwrap();
        wait_terminal(&runtime.handle(), operation.id).await;
        let list = String::from_utf8(
            http_request(
                listen,
                b"GET /ui/operations HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(!list.contains("http-equiv=\"refresh\""));
        assert!(list.contains("自动刷新已停止"));
        let detail = String::from_utf8(http_request(listen, request.as_bytes()).await).unwrap();
        assert!(!detail.contains("http-equiv=\"refresh\""));
        assert!(detail.contains("自动刷新已停止"));
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn serves_danbooru_through_integrated_http() {
        let provider_listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let provider_listen = provider_listener.local_addr().unwrap();
        let provider_router = axum::Router::new().route(
            "/posts.json",
            axum::routing::get(|| async {
                (
                    [(axum::http::header::CONTENT_TYPE, "application/json")],
                    r#"[{"id":9,"md5":"d256310bfab43e08b6422e311cd9b2c9","file_ext":"jpg","file_url":"https://cdn.example/9.jpg"}]"#,
                )
            }),
        );
        tokio::spawn(async move {
            axum::serve(provider_listener, provider_router)
                .await
                .unwrap()
        });

        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config.control.enabled = true;
        config.control.listen = "127.0.0.1:0".parse().unwrap();
        config.profiles.insert(
            "danbooru".to_owned(),
            ProviderProfileConfig {
                provider: "danbooru".to_owned(),
                base_url: Url::parse(&format!("http://{provider_listen}/")).unwrap(),
                ..ProviderProfileConfig::default()
            },
        );
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let listen = runtime.control_listen().unwrap();
        let mut stream = tokio::net::TcpStream::connect(listen).await.unwrap();
        stream
            .write_all(
                b"GET /api/v1/providers/danbooru/default/posts?tags=test&page=1&limit=40 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await
            .unwrap();
        let mut response = Vec::new();
        stream.read_to_end(&mut response).await.unwrap();
        let response = String::from_utf8(response).unwrap();
        assert!(response.starts_with("HTTP/1.1 200 OK"));
        assert!(response.contains("\"provider\":\"danbooru\""));
        assert!(response.contains("\"id\":9"));
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn serves_eh_home_through_api_and_webui() {
        const EH_HOME: &str = include_str!("../tests/fixtures/eh/home_compact.html");
        let provider_listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let provider_listen = provider_listener.local_addr().unwrap();
        let fixture = EH_HOME
            .replace(
                "https://e-hentai.org/",
                &format!("http://{provider_listen}/"),
            )
            .replace("Fixture &amp; Gallery One", "Fixture &lt;Gallery&gt; One");
        let provider_router = axum::Router::new().route(
            "/",
            axum::routing::get(move || {
                let fixture = fixture.clone();
                async move {
                    (
                        [(axum::http::header::CONTENT_TYPE, "text/html; charset=utf-8")],
                        fixture,
                    )
                }
            }),
        );
        tokio::spawn(async move {
            axum::serve(provider_listener, provider_router)
                .await
                .unwrap()
        });

        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config.control.enabled = true;
        config.control.listen = "127.0.0.1:0".parse().unwrap();
        config.profiles.insert(
            "eh".to_owned(),
            ProviderProfileConfig {
                provider: "eh".to_owned(),
                base_url: Url::parse(&format!("http://{provider_listen}/")).unwrap(),
                ..ProviderProfileConfig::default()
            },
        );
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let listen = runtime.control_listen().unwrap();
        let api = http_request(
            listen,
            b"GET /api/v1/providers/eh/default/galleries HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        )
        .await;
        let api = String::from_utf8(api).unwrap();
        assert!(api.starts_with("HTTP/1.1 200 OK"));
        assert!(api.contains("\"gid\":1234567"));
        assert!(api.contains("\"direction\":\"next\""));

        let webui = http_request(
            listen,
            b"GET /ui/eh?profile=default HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        )
        .await;
        let webui = String::from_utf8(webui).unwrap();
        assert!(webui.starts_with("HTTP/1.1 200 OK"));
        assert!(webui.contains("<h1>EH 主页</h1>"));
        assert!(webui.contains("Fixture &lt;Gallery&gt; One"));
        assert!(!webui.contains("Fixture <Gallery> One"));
        assert!(webui.contains("direction=next&amp;gid=1234565"));
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn serves_eh_detail_and_thumbnails_through_api_and_webui() {
        const DETAIL: &str = include_str!("../tests/fixtures/eh/gallery_detail.html");
        const THUMBNAILS: &str = include_str!("../tests/fixtures/eh/thumbnails.html");
        let provider_listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let provider_listen = provider_listener.local_addr().unwrap();
        let provider_router = axum::Router::new().route(
            "/g/123456/abcdef1234/",
            axum::routing::get(
                |axum::extract::RawQuery(query): axum::extract::RawQuery| async move {
                    (
                        [(axum::http::header::CONTENT_TYPE, "text/html; charset=utf-8")],
                        if query.as_deref() == Some("p=1") {
                            THUMBNAILS
                        } else {
                            DETAIL
                        },
                    )
                },
            ),
        );
        tokio::spawn(async move {
            axum::serve(provider_listener, provider_router)
                .await
                .unwrap()
        });
        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config.control.enabled = true;
        config.control.listen = "127.0.0.1:0".parse().unwrap();
        config.profiles.insert(
            "eh".to_owned(),
            ProviderProfileConfig {
                provider: "eh".to_owned(),
                base_url: Url::parse(&format!("http://{provider_listen}/")).unwrap(),
                ..ProviderProfileConfig::default()
            },
        );
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let listen = runtime.control_listen().unwrap();
        let detail = String::from_utf8(
            http_request(
                listen,
                b"GET /api/v1/providers/eh/default/galleries/123456/abcdef1234 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(detail.starts_with("HTTP/1.1 200 OK"));
        assert!(detail.contains("\"title\":\"Fixture Gallery Title\""));
        let thumbs = String::from_utf8(
            http_request(
                listen,
                b"GET /api/v1/providers/eh/default/galleries/123456/abcdef1234/thumbnails?page=1 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(thumbs.starts_with("HTTP/1.1 200 OK"));
        assert!(thumbs.contains("sprite.webp@x=200-300&y=0-140"));
        let webui = String::from_utf8(
            http_request(
                listen,
                b"GET /ui/eh/gallery?profile=default&gid=123456&token=abcdef1234&page=1 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(webui.starts_with("HTTP/1.1 200 OK"));
        assert!(webui.contains("Fixture Gallery Title"));
        assert!(webui.contains("缩略图第 2 页"));
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn eh_original_fetch_resolves_api_and_uses_image_service() {
        const THUMBNAILS: &str = include_str!("../tests/fixtures/eh/thumbnails.html");
        const SHOWKEY: &str = include_str!("../tests/fixtures/eh/image_showkey.html");
        let image = Arc::new(test_jpeg());
        let requests = Arc::new(AtomicUsize::new(0));
        let provider_listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let provider_listen = provider_listener.local_addr().unwrap();
        let fixture = THUMBNAILS
            .replace(
                "https://e-hentai.org/",
                &format!("http://{provider_listen}/"),
            )
            .replace("https://ehgt.org/", &format!("http://{provider_listen}/"));
        let provider_router = axum::Router::new()
            .route(
                "/g/123456/abcdef1234/",
                axum::routing::get(move || {
                    let fixture = fixture.clone();
                    async move {
                        (
                            [(axum::http::header::CONTENT_TYPE, "text/html; charset=utf-8")],
                            fixture,
                        )
                    }
                }),
            )
            .route(
                "/s/aaa111/123456-1",
                axum::routing::get(|| async {
                    (
                        [(axum::http::header::CONTENT_TYPE, "text/html; charset=utf-8")],
                        SHOWKEY,
                    )
                }),
            )
            .route(
                "/api.php",
                axum::routing::post(
                    move |axum::Json(payload): axum::Json<serde_json::Value>| async move {
                        assert_eq!(payload["method"], "showpage");
                        assert_eq!(payload["gid"], 123456);
                        assert_eq!(payload["imgkey"], "aaa111");
                        assert_eq!(payload["showkey"], "fixture-showkey");
                        axum::Json(serde_json::json!({
                            "i3": format!("<img src=\"http://{provider_listen}/original.jpg\" style=\"max-width:100%\">"),
                            "i6": "<a onclick=\"return nl('next-nonce')\">reload</a>"
                        }))
                    },
                ),
            )
            .route(
                "/original.jpg",
                axum::routing::get({
                    let image = image.clone();
                    let requests = requests.clone();
                    move |headers: axum::http::HeaderMap| {
                        let image = image.clone();
                        let requests = requests.clone();
                        async move {
                            assert!(
                                headers
                                    .get(axum::http::header::REFERER)
                                    .and_then(|value| value.to_str().ok())
                                    .is_some_and(|value| value.starts_with("http://127.0.0.1:"))
                            );
                            requests.fetch_add(1, Ordering::SeqCst);
                            (
                                [(axum::http::header::CONTENT_TYPE, "image/jpeg")],
                                image.as_ref().clone(),
                            )
                        }
                    }
                }),
            );
        tokio::spawn(async move {
            axum::serve(provider_listener, provider_router)
                .await
                .unwrap()
        });
        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config.control.enabled = true;
        config.control.listen = "127.0.0.1:0".parse().unwrap();
        config.profiles.insert(
            "eh".to_owned(),
            ProviderProfileConfig {
                provider: "eh".to_owned(),
                base_url: Url::parse(&format!("http://{provider_listen}/")).unwrap(),
                ..ProviderProfileConfig::default()
            },
        );
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let request = EhPageFetchRequest {
            profile: ProfileKey::new("eh", "default"),
            gallery: crate::EhGalleryRef {
                gid: 123456,
                token: "abcdef1234".to_owned(),
            },
            page: 0,
            nl: None,
        };
        let first = runtime
            .handle()
            .start_eh_page_fetch(request.clone())
            .await
            .unwrap();
        let second = runtime.handle().start_eh_page_fetch(request).await.unwrap();
        let first = wait_terminal(&runtime.handle(), first.id).await;
        let second = wait_terminal(&runtime.handle(), second.id).await;
        assert_eq!(first.state, OperationState::Completed);
        assert_eq!(second.state, OperationState::Completed);
        assert_eq!(
            first.resource.unwrap().content_md5,
            second.resource.unwrap().content_md5
        );
        assert_eq!(requests.load(Ordering::SeqCst), 1);

        let listen = runtime.control_listen().unwrap();
        let api = String::from_utf8(
            http_request(
                listen,
                b"POST /api/v1/providers/eh/default/galleries/123456/abcdef1234/pages/0/fetch HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(api.starts_with("HTTP/1.1 202 Accepted"));
        let form = "profile=default&gid=123456&token=abcdef1234&page=0";
        let request = format!(
            "POST /ui/eh/fetch HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{form}",
            form.len()
        );
        let webui = String::from_utf8(http_request(listen, request.as_bytes()).await).unwrap();
        assert!(webui.starts_with("HTTP/1.1 303 See Other"));
        assert!(webui.contains("location: /ui/operation?id="));
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn serves_persistent_eh_archive_tasks_through_api_and_webui() {
        const SUBMITTED: &str = include_str!("../tests/fixtures/eh/archive_submitted.html");
        const INTERMEDIATE: &str = include_str!("../tests/fixtures/eh/archive_intermediate.html");
        let archive_bytes = test_zip();
        let archive = Arc::new(archive_bytes.clone());
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let provider_listen = listener.local_addr().unwrap();
        let router = axum::Router::new()
            .route(
                "/g/123456/abcdef1234/",
                axum::routing::get(|| async {
                    (
                        [(axum::http::header::CONTENT_TYPE, "text/html")],
                        "<h1 id=\"gn\">Runtime Archive Fixture</h1>",
                    )
                }),
            )
            .route(
                "/archiver.php",
                axum::routing::post(|| async {
                    ([(axum::http::header::CONTENT_TYPE, "text/html")], SUBMITTED)
                }),
            )
            .route(
                "/archive-intermediate",
                axum::routing::get(|| async {
                    (
                        [(axum::http::header::CONTENT_TYPE, "text/html")],
                        INTERMEDIATE,
                    )
                }),
            )
            .route(
                "/signed/archive.zip",
                axum::routing::get(move || {
                    let archive = archive.clone();
                    async move {
                        (
                            [
                                (axum::http::header::CONTENT_TYPE, "application/zip"),
                                (axum::http::header::ACCEPT_RANGES, "bytes"),
                            ],
                            archive.as_ref().clone(),
                        )
                    }
                }),
            );
        tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config.control.enabled = true;
        config.control.listen = "127.0.0.1:0".parse().unwrap();
        config.profiles.insert(
            "eh".to_owned(),
            ProviderProfileConfig {
                provider: "eh".to_owned(),
                base_url: Url::parse(&format!("http://{provider_listen}/")).unwrap(),
                ..ProviderProfileConfig::default()
            },
        );
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let listen = runtime.control_listen().unwrap();
        let started = String::from_utf8(
            http_request(
                listen,
                b"POST /api/v1/providers/eh/default/galleries/123456/abcdef1234/archives/resample/download HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(
            started.starts_with("HTTP/1.1 202 Accepted"),
            "unexpected response: {started}"
        );
        assert!(!started.contains("signed/archive.zip"));
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                let tasks = runtime.handle().archive_tasks().await;
                if tasks.first().is_some_and(|task| task.state.is_terminal()) {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        let api = String::from_utf8(
            http_request(
                listen,
                b"GET /api/v1/archive-tasks HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(api.starts_with("HTTP/1.1 200 OK"));
        assert!(api.contains("\"state\":\"completed\""));
        assert!(!api.contains("signed/archive.zip"));
        let events = runtime.handle().events_after(0).await.unwrap();
        assert!(events.events.iter().any(|event| matches!(
            &event.subject,
            crate::CoreEventSubject::ArchiveTask { task }
                if task.state == crate::ArchiveTaskState::Completed
        )));
        let galleries = String::from_utf8(
            http_request(
                listen,
                b"GET /api/v1/local-galleries HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(galleries.starts_with("HTTP/1.1 200 OK"));
        assert!(galleries.contains("\"gid\":123456"));
        let gallery_id = runtime.handle().archive_tasks().await[0].id;
        assert!(galleries.contains(&format!("\"id\":\"{gallery_id}\"")));
        assert!(!galleries.contains("archive_filename"));
        assert!(!galleries.contains("directory"));
        assert!(!galleries.contains("archive.zip"));
        let healthy_inventory = runtime.handle().local_gallery_inventory().await.unwrap();
        assert_eq!(healthy_inventory.registered_healthy, 1);
        assert_eq!(healthy_inventory.registered_damaged, 0);
        assert_eq!(healthy_inventory.unregistered_importable, 0);
        assert_eq!(healthy_inventory.invalid, 0);
        let copied_directory = temp
            .path()
            .join("Downloads/EHArchieve/[654321][copied1234] Copied Gallery");
        std::fs::create_dir(&copied_directory).unwrap();
        let copied_id = uuid::Uuid::now_v7();
        let copied_archive = copied_directory.join("copied.zip");
        std::fs::write(&copied_archive, &archive_bytes).unwrap();
        let copied_now = time::OffsetDateTime::now_utc()
            .format(&time::format_description::well_known::Rfc3339)
            .unwrap();
        std::fs::write(
            copied_directory.join("gallery.json"),
            serde_json::to_vec_pretty(&serde_json::json!({
                "schema_version": 1,
                "download_task_id": copied_id,
                "gid": 654321,
                "token": "copied1234",
                "title": "Copied Gallery",
                "directory": "/ignored/source/path",
                "archive_filename": "copied.zip",
                "cover_filename": null,
                "archive_bytes": archive_bytes.len(),
                "created_at": copied_now,
                "updated_at": copied_now
            }))
            .unwrap(),
        )
        .unwrap();
        let invalid_directory = temp
            .path()
            .join("Downloads/EHArchieve/invalid local gallery");
        std::fs::create_dir(&invalid_directory).unwrap();
        std::fs::write(invalid_directory.join("gallery.json"), b"not json").unwrap();
        let inventory = runtime.handle().local_gallery_inventory().await.unwrap();
        assert_eq!(inventory.registered_healthy, 1);
        assert_eq!(
            inventory.unregistered_importable, 1,
            "unexpected inventory: {:?}",
            inventory.entries
        );
        assert_eq!(inventory.invalid, 1);
        assert!(inventory.entries.iter().all(|entry| {
            !serde_json::to_string(entry)
                .unwrap()
                .contains(temp.path().to_string_lossy().as_ref())
        }));
        assert!(
            runtime
                .handle()
                .local_gallery(copied_id, 0, 100)
                .await
                .is_err()
        );
        let inventory_api = String::from_utf8(
            http_request(
                listen,
                b"GET /api/v1/local-gallery-inventory HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(inventory_api.starts_with("HTTP/1.1 200 OK"));
        assert!(inventory_api.contains("\"unregistered_importable\":1"));
        assert!(inventory_api.contains("\"invalid\":1"));
        let local_data = String::from_utf8(
            http_request(
                listen,
                b"GET /ui/local-data HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(local_data.starts_with("HTTP/1.1 200 OK"));
        assert!(local_data.contains("未登记可导入"));
        assert!(local_data.contains("格式无效"));
        assert!(local_data.contains("导入登记"));
        let import = String::from_utf8(
            http_request(
                listen,
                format!(
                    "POST /api/v1/local-gallery-inventory/{copied_id}/import HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert!(import.starts_with("HTTP/1.1 200 OK"));
        assert!(
            runtime
                .handle()
                .local_gallery(copied_id, 0, 100)
                .await
                .is_ok()
        );
        let after_import = runtime.handle().local_gallery_inventory().await.unwrap();
        assert_eq!(after_import.registered_healthy, 2);
        assert_eq!(after_import.unregistered_importable, 0);
        std::fs::write(copied_archive, b"damaged").unwrap();
        let damaged = runtime.handle().local_gallery_inventory().await.unwrap();
        assert_eq!(damaged.registered_healthy, 1);
        assert_eq!(damaged.registered_damaged, 1);
        assert!(damaged.entries.iter().any(|entry| {
            entry.gallery_id == Some(copied_id)
                && entry
                    .issues
                    .iter()
                    .any(|issue| issue.code == "archive_length_mismatch")
        }));
        std::fs::remove_dir_all(copied_directory).unwrap();
        let missing = runtime.handle().local_gallery_inventory().await.unwrap();
        assert!(missing.entries.iter().any(|entry| {
            entry.gallery_id == Some(copied_id)
                && entry
                    .issues
                    .iter()
                    .any(|issue| issue.code == "directory_missing")
        }));
        let detail = String::from_utf8(
            http_request(
                listen,
                format!(
                    "GET /api/v1/local-galleries/{gallery_id}?offset=0&limit=100 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert!(detail.starts_with("HTTP/1.1 200 OK"));
        assert!(detail.contains("\"total_pages\":2"));
        assert!(detail.contains("\"id\":0,\"number\":1,\"filename\":\"2.png\""));
        assert!(detail.contains("\"id\":1,\"number\":2,\"filename\":\"10.jpg\""));
        assert!(!detail.contains("hidden.jpg"));
        assert!(!detail.contains("directory"));
        let page = http_request(
            listen,
            format!(
                "GET /api/v1/local-galleries/{gallery_id}/pages/0 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            )
            .as_bytes(),
        )
        .await;
        assert!(page.starts_with(b"HTTP/1.1 200 OK"));
        assert!(
            page.windows("content-type: image/png".len())
                .any(|window| window == b"content-type: image/png")
        );
        assert!(page.windows(8).any(|window| window == b"\x89PNG\r\n\x1a\n"));
        let local_webui = String::from_utf8(
            http_request(
                listen,
                format!(
                    "GET /ui/local-gallery?id={gallery_id}&offset=0 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert!(local_webui.starts_with("HTTP/1.1 200 OK"));
        assert!(local_webui.contains("Runtime Archive Fixture"));
        assert!(local_webui.contains("第 1 页"));
        assert!(local_webui.contains(&format!("/api/v1/local-galleries/{gallery_id}/cover")));
        assert!(local_webui.contains(&format!("/api/v1/local-galleries/{gallery_id}/export")));
        assert!(local_webui.contains("不暴露服务器存储路径"));
        assert!(local_webui.contains("预览永久删除"));
        assert!(!local_webui.contains("archive.zip"));
        let config_api = String::from_utf8(
            http_request(
                listen,
                b"GET /api/v1/config HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(config_api.starts_with("HTTP/1.1 200 OK"));
        assert!(config_api.contains("\"proxy_configured\":false"));
        assert!(!config_api.contains("signed/archive.zip"));
        let config_webui = String::from_utf8(
            http_request(
                listen,
                b"GET /ui/config HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(config_webui.starts_with("HTTP/1.1 200 OK"));
        assert!(config_webui.contains("当前生效配置"));
        assert!(config_webui.contains("只读且已脱敏"));
        let mut embedded_export = runtime
            .handle()
            .local_gallery_export(gallery_id)
            .await
            .unwrap();
        assert_eq!(embedded_export.descriptor().gallery_id, gallery_id);
        assert_eq!(embedded_export.descriptor().mime_type, "application/zip");
        assert_eq!(
            embedded_export.descriptor().byte_length,
            archive_bytes.len() as u64
        );
        assert!(
            !serde_json::to_string(embedded_export.descriptor())
                .unwrap()
                .contains("directory")
        );
        let mut embedded_bytes = Vec::new();
        while let Some(chunk) = embedded_export.read_chunk().await.unwrap() {
            assert!(chunk.len() <= 64 * 1024);
            embedded_bytes.extend_from_slice(&chunk);
        }
        assert_eq!(embedded_export.bytes_read(), archive_bytes.len() as u64);
        assert_eq!(embedded_bytes, archive_bytes);
        drop(embedded_export);
        let first_export = runtime
            .handle()
            .local_gallery_export(gallery_id)
            .await
            .unwrap();
        let second_export = runtime
            .handle()
            .local_gallery_export(gallery_id)
            .await
            .unwrap();
        let third_export = runtime.handle().local_gallery_export(gallery_id).await;
        assert!(matches!(
            third_export,
            Err(error) if error.code() == crate::ErrorCode::Overloaded
        ));
        drop((first_export, second_export));
        let exported = http_request(
            listen,
            format!(
                "GET /api/v1/local-galleries/{gallery_id}/export HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            )
            .as_bytes(),
        )
        .await;
        let separator = exported
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .unwrap();
        let export_headers = String::from_utf8(exported[..separator].to_vec())
            .unwrap()
            .to_ascii_lowercase();
        assert!(export_headers.starts_with("http/1.1 200 ok"));
        assert!(export_headers.contains("content-type: application/zip"));
        assert!(export_headers.contains(&format!("content-length: {}", archive_bytes.len())));
        assert!(export_headers.contains("content-disposition: attachment;"));
        assert!(export_headers.contains("filename*=utf-8''archive.zip"));
        assert_eq!(&exported[separator + 4..], archive_bytes.as_slice());
        let delete_preview_form = format!("id={gallery_id}");
        let delete_preview_page = String::from_utf8(
            http_request(
                listen,
                format!(
                    "POST /ui/local-gallery/delete HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{delete_preview_form}",
                    delete_preview_form.len()
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert!(delete_preview_page.starts_with("HTTP/1.1 200 OK"));
        assert!(delete_preview_page.contains("此操作不可撤销"));
        assert!(delete_preview_page.contains("确认永久删除原始 ZIP 和画廊"));
        let cover = http_request(
            listen,
            format!(
                "GET /api/v1/local-galleries/{gallery_id}/cover HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            )
            .as_bytes(),
        )
        .await;
        assert!(cover.starts_with(b"HTTP/1.1 200 OK"));
        assert!(
            cover
                .windows("content-type: image/png".len())
                .any(|window| window == b"content-type: image/png")
        );
        assert!(
            cover
                .windows(8)
                .any(|window| window == b"\x89PNG\r\n\x1a\n")
        );
        let generate = String::from_utf8(
            http_request(
                listen,
                format!(
                    "POST /api/v1/local-galleries/{gallery_id}/comic-info HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert!(generate.starts_with("HTTP/1.1 200 OK"));
        assert!(generate.contains("\"filename\":\"ComicInfo.xml\""));
        assert!(generate.contains("\"page_count\":2"));
        let delete = String::from_utf8(
            http_request(
                listen,
                format!(
                    "DELETE /api/v1/local-galleries/{gallery_id}/comic-info HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert!(delete.starts_with("HTTP/1.1 204 No Content"));
        let regenerate = String::from_utf8(
            http_request(
                listen,
                format!(
                    "POST /api/v1/local-galleries/{gallery_id}/comic-info HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert_eq!(generate, regenerate);
        let webui = String::from_utf8(
            http_request(
                listen,
                b"GET /ui/archive-tasks HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await,
        )
        .unwrap();
        assert!(webui.starts_with("HTTP/1.1 200 OK"));
        assert!(webui.contains("<h1>Archive 任务</h1>"));
        assert!(webui.contains("Consumed"));
        let invalid_payload = "{\"confirmation_token\":\"00000000-0000-0000-0000-000000000000\"}";
        let invalid_delete = String::from_utf8(
            http_request(
                listen,
                format!(
                    "POST /api/v1/local-galleries/{gallery_id}/delete HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{invalid_payload}",
                    invalid_payload.len()
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert!(invalid_delete.starts_with("HTTP/1.1 403 Forbidden"));
        assert!(
            runtime
                .handle()
                .local_gallery(gallery_id, 0, 100)
                .await
                .is_ok()
        );
        let changed_confirmation = runtime
            .handle()
            .prepare_local_gallery_delete(gallery_id)
            .await
            .unwrap();
        let gallery_directory = std::fs::read_dir(temp.path().join("Downloads/EHArchieve"))
            .unwrap()
            .find_map(|entry| {
                let path = entry.ok()?.path();
                let metadata: serde_json::Value =
                    serde_json::from_slice(&std::fs::read(path.join("gallery.json")).ok()?).ok()?;
                (metadata["download_task_id"] == gallery_id.to_string()).then_some(path)
            })
            .unwrap();
        let unexpected = gallery_directory.join("unexpected.txt");
        std::fs::write(&unexpected, b"changed after preview").unwrap();
        let changed_error = runtime
            .handle()
            .delete_local_gallery(
                gallery_id,
                crate::LocalGalleryDeleteRequest {
                    confirmation_token: changed_confirmation.confirmation_token,
                },
            )
            .await
            .unwrap_err();
        assert_eq!(changed_error.code(), crate::ErrorCode::IntegrityMismatch);
        assert!(gallery_directory.is_dir());
        std::fs::remove_file(unexpected).unwrap();
        let preview = String::from_utf8(
            http_request(
                listen,
                format!(
                    "POST /api/v1/local-galleries/{gallery_id}/delete-preview HTTP/1.1\r\nHost: localhost\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert!(preview.starts_with("HTTP/1.1 200 OK"));
        let body = preview.split_once("\r\n\r\n").unwrap().1;
        let confirmation: crate::LocalGalleryDeleteConfirmation =
            serde_json::from_str(body).unwrap();
        assert_eq!(confirmation.gallery_id, gallery_id);
        assert_eq!(confirmation.file_count, 4);
        let payload = format!(
            "{{\"confirmation_token\":\"{}\"}}",
            confirmation.confirmation_token
        );
        let held_export = runtime
            .handle()
            .local_gallery_export(gallery_id)
            .await
            .unwrap();
        let delete_request_bytes = format!(
            "POST /api/v1/local-galleries/{gallery_id}/delete HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{payload}",
            payload.len()
        )
        .into_bytes();
        let mut delete_request =
            tokio::spawn(async move { http_request(listen, &delete_request_bytes).await });
        assert!(
            tokio::time::timeout(Duration::from_millis(20), &mut delete_request)
                .await
                .is_err(),
            "confirmed deletion must wait for an active export"
        );
        drop(held_export);
        let delete = String::from_utf8(delete_request.await.unwrap()).unwrap();
        assert!(delete.starts_with("HTTP/1.1 200 OK"));
        assert!(delete.contains("\"deleted_files\":4"));
        assert!(runtime.handle().local_galleries().await.unwrap().is_empty());
        let consumed = runtime.handle().archive_task(gallery_id).await.unwrap();
        assert_eq!(consumed.state, crate::ArchiveTaskState::Consumed);
        assert!(consumed.final_path.is_none());
        let reused = String::from_utf8(
            http_request(
                listen,
                format!(
                    "POST /api/v1/local-galleries/{gallery_id}/delete HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{payload}",
                    payload.len()
                )
                .as_bytes(),
            )
            .await,
        )
        .unwrap();
        assert!(reused.starts_with("HTTP/1.1 403 Forbidden"));
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn runtime_exclusively_owns_storage_until_shutdown() {
        let temp = TempDir::new().unwrap();
        let config = config(&temp);
        let first = CoreBuilder::new(config.clone()).build().await.unwrap();
        let error = match CoreBuilder::new(config.clone()).build().await {
            Ok(_) => panic!("second Runtime must not own the same storage"),
            Err(error) => error,
        };
        assert_eq!(error.code(), crate::ErrorCode::AlreadyRunning);
        first.shutdown().await.unwrap();
        CoreBuilder::new(config)
            .build()
            .await
            .unwrap()
            .shutdown()
            .await
            .unwrap();
    }

    #[tokio::test]
    async fn booru_original_fetch_is_shared_and_content_addressed() {
        let image = Arc::new(test_jpeg());
        let digest = md5_hex(&image);
        let requests = Arc::new(AtomicUsize::new(0));
        let listen = image_provider(image.clone(), digest.clone(), requests.clone()).await;
        let temp = TempDir::new().unwrap();
        let mut core_config = config(&temp);
        core_config
            .profiles
            .insert("danbooru".to_owned(), danbooru_profile(listen));
        let runtime = CoreBuilder::new(core_config).build().await.unwrap();
        let handle = runtime.handle();
        let request = BooruOriginalFetchRequest {
            profile: ProfileKey::new("danbooru", "default"),
            post_id: 7,
        };
        let first = handle
            .start_booru_original_fetch(request.clone())
            .await
            .unwrap();
        let second = handle
            .start_booru_original_fetch(request.clone())
            .await
            .unwrap();
        let first = wait_terminal(&handle, first.id).await;
        let second = wait_terminal(&handle, second.id).await;
        assert_eq!(first.state, OperationState::Completed);
        assert_eq!(second.state, OperationState::Completed);
        assert_eq!(requests.load(Ordering::SeqCst), 1);
        assert!(first.shared || second.shared);
        let descriptor = first.resource.unwrap();
        assert_eq!(descriptor.extension, "jpg");
        assert_eq!(descriptor.source, ResourceSource::Network);
        assert!(!descriptor.cache_persisted);
        let digest = ContentMd5::from_str(&digest).unwrap();
        assert_eq!(
            handle.image_resource(digest, "jpeg").await.unwrap().bytes(),
            image.as_ref().as_slice()
        );
        let blob = temp.path().join(format!(
            "Cache/files/{}/{}/{}.jpg",
            &digest.to_string()[0..2],
            &digest.to_string()[2..4],
            digest
        ));
        tokio::time::timeout(Duration::from_secs(1), async {
            while !blob.is_file() {
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();

        let cached = handle.start_booru_original_fetch(request).await.unwrap();
        let cached = wait_terminal(&handle, cached.id).await;
        assert_eq!(cached.resource.unwrap().source, ResourceSource::Memory);
        assert_eq!(requests.load(Ordering::SeqCst), 1);
        runtime.shutdown().await.unwrap();

        let mut restart_config = config(&temp);
        restart_config
            .profiles
            .insert("danbooru".to_owned(), danbooru_profile(listen));
        let restarted = CoreBuilder::new(restart_config).build().await.unwrap();
        let restarted_fetch = restarted
            .handle()
            .start_booru_original_fetch(BooruOriginalFetchRequest {
                profile: ProfileKey::new("danbooru", "default"),
                post_id: 7,
            })
            .await
            .unwrap();
        let restarted_fetch = wait_terminal(&restarted.handle(), restarted_fetch.id).await;
        assert_eq!(
            restarted_fetch.resource.unwrap().source,
            ResourceSource::Disk
        );
        assert_eq!(requests.load(Ordering::SeqCst), 1);
        restarted.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn booru_original_rejects_provider_md5_mismatch() {
        let image = Arc::new(test_jpeg());
        let requests = Arc::new(AtomicUsize::new(0));
        let listen = image_provider(
            image,
            "00000000000000000000000000000000".to_owned(),
            requests,
        )
        .await;
        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config
            .profiles
            .insert("danbooru".to_owned(), danbooru_profile(listen));
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let operation = runtime
            .handle()
            .start_booru_original_fetch(BooruOriginalFetchRequest {
                profile: ProfileKey::new("danbooru", "default"),
                post_id: 8,
            })
            .await
            .unwrap();
        let terminal = wait_terminal(&runtime.handle(), operation.id).await;
        assert_eq!(terminal.state, OperationState::Failed);
        assert_eq!(terminal.error.unwrap().code, ErrorCode::IntegrityMismatch);
        assert!(!temp.path().join("Cache/files/00/00").exists());
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn pixiv_unknown_md5_fetch_is_shared_and_alias_survives_restart() {
        let image = Arc::new(test_jpeg());
        let requests = Arc::new(AtomicUsize::new(0));
        let listen = pixiv_provider(image, requests.clone()).await;
        let temp = TempDir::new().unwrap();
        let mut core_config = config(&temp);
        core_config
            .profiles
            .insert("pixiv".to_owned(), pixiv_profile(listen));
        let runtime = CoreBuilder::new(core_config).build().await.unwrap();
        let request = PixivPageFetchRequest {
            profile: ProfileKey::new("pixiv", "default"),
            illust_id: "12345678".to_owned(),
            page: 0,
        };
        let first = runtime
            .handle()
            .start_pixiv_page_fetch(request.clone())
            .await
            .unwrap();
        let second = runtime
            .handle()
            .start_pixiv_page_fetch(request.clone())
            .await
            .unwrap();
        let first = wait_terminal(&runtime.handle(), first.id).await;
        let second = wait_terminal(&runtime.handle(), second.id).await;
        assert!(
            first.error.is_none(),
            "first Pixiv fetch failed: {:?}",
            first.error
        );
        assert!(
            second.error.is_none(),
            "second Pixiv fetch failed: {:?}",
            second.error
        );
        assert_eq!(first.state, OperationState::Completed);
        assert_eq!(second.state, OperationState::Completed);
        assert!(first.shared || second.shared);
        assert_eq!(requests.load(Ordering::SeqCst), 1);
        let md5 = first.resource.unwrap().content_md5;
        runtime.shutdown().await.unwrap();
        assert!(temp.path().join("Cache/image_aliases.json").is_file());

        let mut restart_config = config(&temp);
        restart_config
            .profiles
            .insert("pixiv".to_owned(), pixiv_profile(listen));
        let restarted = CoreBuilder::new(restart_config).build().await.unwrap();
        let cached = restarted
            .handle()
            .start_pixiv_page_fetch(request)
            .await
            .unwrap();
        let cached = wait_terminal(&restarted.handle(), cached.id).await;
        assert_eq!(cached.state, OperationState::Completed);
        let descriptor = cached.resource.unwrap();
        assert_eq!(descriptor.content_md5, md5);
        assert_eq!(descriptor.source, ResourceSource::Disk);
        assert_eq!(requests.load(Ordering::SeqCst), 1);
        restarted.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn cancelling_one_shared_image_subscriber_keeps_the_transfer() {
        let image = Arc::new(test_jpeg());
        let digest = md5_hex(&image);
        let requests = Arc::new(AtomicUsize::new(0));
        let listen = image_provider(image, digest, requests.clone()).await;
        let temp = TempDir::new().unwrap();
        let mut core_config = config(&temp);
        core_config
            .profiles
            .insert("danbooru".to_owned(), danbooru_profile(listen));
        let runtime = CoreBuilder::new(core_config).build().await.unwrap();
        let handle = runtime.handle();
        let request = BooruOriginalFetchRequest {
            profile: ProfileKey::new("danbooru", "default"),
            post_id: 10,
        };
        let cancelled = handle
            .start_booru_original_fetch(request.clone())
            .await
            .unwrap();
        let survivor = handle.start_booru_original_fetch(request).await.unwrap();
        tokio::time::sleep(Duration::from_millis(10)).await;
        handle.cancel_operation(cancelled.id).await.unwrap();
        assert_eq!(
            wait_terminal(&handle, cancelled.id).await.state,
            OperationState::Cancelled
        );
        assert_eq!(
            wait_terminal(&handle, survivor.id).await.state,
            OperationState::Completed
        );
        assert_eq!(requests.load(Ordering::SeqCst), 1);
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn serves_content_addressed_image_resource_over_http() {
        let image = Arc::new(test_jpeg());
        let digest = md5_hex(&image);
        let requests = Arc::new(AtomicUsize::new(0));
        let provider_listen = image_provider(image.clone(), digest.clone(), requests).await;
        let temp = TempDir::new().unwrap();
        let mut core_config = config(&temp);
        core_config.control.enabled = true;
        core_config.control.listen = "127.0.0.1:0".parse().unwrap();
        core_config
            .profiles
            .insert("danbooru".to_owned(), danbooru_profile(provider_listen));
        let runtime = CoreBuilder::new(core_config).build().await.unwrap();
        let handle = runtime.handle();
        let operation = handle
            .start_booru_original_fetch(BooruOriginalFetchRequest {
                profile: ProfileKey::new("danbooru", "default"),
                post_id: 11,
            })
            .await
            .unwrap();
        assert_eq!(
            wait_terminal(&handle, operation.id).await.state,
            OperationState::Completed
        );

        let mut stream = tokio::net::TcpStream::connect(runtime.control_listen().unwrap())
            .await
            .unwrap();
        let request = format!(
            "GET /api/v1/resources/images/{digest}/jpg HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        );
        stream.write_all(request.as_bytes()).await.unwrap();
        let mut response = Vec::new();
        stream.read_to_end(&mut response).await.unwrap();
        let separator = response
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .unwrap();
        let headers = String::from_utf8(response[..separator].to_vec()).unwrap();
        assert!(headers.starts_with("HTTP/1.1 200 OK"));
        assert!(
            headers
                .to_ascii_lowercase()
                .contains("content-type: image/jpeg")
        );
        assert!(headers.contains(&format!("etag: \"{digest}\"")));
        assert_eq!(&response[separator + 4..], image.as_ref().as_slice());
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn diagnostic_webui_starts_a_real_image_fetch() {
        let image = Arc::new(test_jpeg());
        let digest = md5_hex(&image);
        let requests = Arc::new(AtomicUsize::new(0));
        let provider_listen = image_provider(image, digest, requests.clone()).await;
        let temp = TempDir::new().unwrap();
        let mut core_config = config(&temp);
        core_config.control.enabled = true;
        core_config.control.listen = "127.0.0.1:0".parse().unwrap();
        core_config
            .profiles
            .insert("danbooru".to_owned(), danbooru_profile(provider_listen));
        let runtime = CoreBuilder::new(core_config).build().await.unwrap();
        let listen = runtime.control_listen().unwrap();

        let detail = http_request(
            listen,
            b"GET /ui/post?provider=danbooru&profile=default&id=12 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
        )
        .await;
        let detail = String::from_utf8(detail).unwrap();
        assert!(detail.starts_with("HTTP/1.1 200 OK"));
        assert!(detail.contains("获取并校验原图"));
        assert!(
            detail.contains("form-action &#39;self&#39;") || detail.contains("form-action 'self'")
        );

        let body = "provider=danbooru&profile=default&post_id=12";
        let request = format!(
            "POST /ui/fetch HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body,
        );
        let started = http_request(listen, request.as_bytes()).await;
        let started = String::from_utf8(started).unwrap();
        assert!(started.starts_with("HTTP/1.1 303 See Other"));
        assert!(started.contains("location: /ui/operation?id="));
        let operation = tokio::time::timeout(Duration::from_secs(1), async {
            loop {
                if let Some(operation) = runtime.handle().operations().await.unwrap().first() {
                    break operation.clone();
                }
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
        assert_eq!(
            wait_terminal(&runtime.handle(), operation.id).await.state,
            OperationState::Completed
        );
        assert_eq!(requests.load(Ordering::SeqCst), 1);
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn fake_operation_completes_with_revisioned_events() {
        let temp = TempDir::new().unwrap();
        let runtime = CoreBuilder::new(config(&temp)).build().await.unwrap();
        let handle = runtime.handle();
        let started = handle
            .start_fake_operation(FakeOperationRequest {
                duration_ms: 10,
                ..FakeOperationRequest::default()
            })
            .await
            .unwrap();
        let terminal = wait_terminal(&handle, started.id).await;
        assert_eq!(terminal.state, OperationState::Completed);
        assert_eq!(terminal.revision, 3);
        let batch = handle.events_after(0).await.unwrap();
        assert_eq!(batch.events.len(), 3);
        assert_eq!(batch.events[0].sequence, 1);
        assert_eq!(batch.events[2].revision, 3);
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn fake_operation_can_be_cancelled_and_deadlined() {
        let temp = TempDir::new().unwrap();
        let runtime = CoreBuilder::new(config(&temp)).build().await.unwrap();
        let handle = runtime.handle();
        let running = handle
            .start_fake_operation(FakeOperationRequest {
                duration_ms: 5_000,
                ..FakeOperationRequest::default()
            })
            .await
            .unwrap();
        handle.cancel_operation(running.id).await.unwrap();
        assert_eq!(
            wait_terminal(&handle, running.id).await.state,
            OperationState::Cancelled
        );

        let deadline = handle
            .start_fake_operation(FakeOperationRequest {
                duration_ms: 100,
                deadline_ms: Some(5),
                ..FakeOperationRequest::default()
            })
            .await
            .unwrap();
        let terminal = wait_terminal(&handle, deadline.id).await;
        assert_eq!(terminal.state, OperationState::Failed);
        assert_eq!(terminal.error.unwrap().code, ErrorCode::DeadlineExceeded);
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn operation_queue_is_bounded_and_queued_work_can_cancel() {
        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config.operations = OperationConfig {
            max_active: 1,
            max_queued: 1,
            retained_terminal: 4,
            default_deadline_seconds: 30,
        };
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let handle = runtime.handle();
        let request = FakeOperationRequest {
            duration_ms: 5_000,
            ..FakeOperationRequest::default()
        };
        let active = handle.start_fake_operation(request.clone()).await.unwrap();
        let queued = handle.start_fake_operation(request.clone()).await.unwrap();
        let error = handle.start_fake_operation(request).await.unwrap_err();
        assert_eq!(error.code(), ErrorCode::Overloaded);
        let cancelled = handle.cancel_operation(queued.id).await.unwrap();
        assert_eq!(cancelled.state, OperationState::Cancelled);
        handle.cancel_operation(active.id).await.unwrap();
        wait_terminal(&handle, active.id).await;
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn stale_event_cursor_requires_resync() {
        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config.events = EventConfig {
            capacity: 4,
            retained: 1,
        };
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let handle = runtime.handle();
        let operation = handle
            .start_fake_operation(FakeOperationRequest {
                duration_ms: 5,
                ..FakeOperationRequest::default()
            })
            .await
            .unwrap();
        wait_terminal(&handle, operation.id).await;
        let batch = handle.events_after(1).await.unwrap();
        assert!(batch.resync_required);
        assert!(batch.events.is_empty());
        runtime.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn runtime_replaces_profile_generation_and_probes_root() {
        async fn server(body: &'static str) -> std::net::SocketAddr {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let listen = listener.local_addr().unwrap();
            let router =
                axum::Router::new().route("/", axum::routing::get(move || async move { body }));
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

        let first_listen = server("first").await;
        let second_listen = server("second").await;
        let temp = TempDir::new().unwrap();
        let mut config = config(&temp);
        config
            .profiles
            .insert("test/default".to_owned(), profile(first_listen));
        let runtime = CoreBuilder::new(config).build().await.unwrap();
        let handle = runtime.handle();
        let key = ProfileKey::new("test", "default");
        let first = handle.probe_profile(&key).await.unwrap();
        assert_eq!(first.generation, 1);
        assert_eq!(first.response_bytes, 5);
        let replacement = handle
            .replace_profile(profile(second_listen))
            .await
            .unwrap();
        assert_eq!(replacement.generation, 2);
        let second = handle.probe_profile(&key).await.unwrap();
        assert_eq!(second.generation, 2);
        assert_eq!(second.response_bytes, 6);
        runtime.shutdown().await.unwrap();
    }
}
