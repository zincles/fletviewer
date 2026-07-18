//! Core Runtime lifecycle and embedded handle.

use crate::{
    CoreConfig, CoreError, CoreSnapshot, ErrorCode, EventBatch, EventSubscription,
    FakeOperationRequest, OperationId, OperationSnapshot, ProfileKey, ProfileProbeSnapshot,
    ProfileSnapshot, ProviderProfileConfig, RuntimeId, RuntimeState, StorageSnapshot, control,
    operation_service::{OperationCompletion, OperationService},
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
    SetControlListen {
        listen: std::net::SocketAddr,
        reply: oneshot::Sender<()>,
    },
    StartFake {
        request: FakeOperationRequest,
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
        config: ProviderProfileConfig,
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
        let sessions = Arc::new(SessionRegistry::new(
            &self.config.profiles,
            &self.config.network,
        )?);
        let (command_tx, command_rx) = mpsc::channel(command_capacity);
        let (completion_tx, completion_rx) = mpsc::channel(command_capacity);
        let (state_tx, state_rx) = watch::channel(RuntimeState::Starting);
        let shutdown = CancellationToken::new();
        let actor_shutdown = shutdown.clone();
        let runtime_id = RuntimeId::new();
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
                completion_tx,
            ),
            sessions: sessions.clone(),
        };
        let mut actor = tokio::spawn(run_actor(
            data,
            command_rx,
            completion_rx,
            state_tx,
            actor_shutdown,
        ));
        let handle = CoreHandle {
            command_tx,
            state_rx,
            shutdown: shutdown.clone(),
            shutdown_seconds,
            sessions,
        };
        handle.wait_ready().await?;
        let control = if control_config.enabled {
            match control::start(control_config.listen, handle.clone(), shutdown.clone()).await {
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
        self.request(|reply| CoreCommand::ReplaceProfile { config, reply })
            .await?
    }

    /// Probes the configured root of one Provider profile with bounded response buffering.
    pub async fn probe_profile(&self, key: &ProfileKey) -> Result<ProfileProbeSnapshot, CoreError> {
        self.sessions.probe(key, self.shutdown.child_token()).await
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
    mut completions: mpsc::Receiver<OperationCompletion>,
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
                Some(CoreCommand::SetControlListen { listen, reply }) => {
                    data.control_listen = Some(listen);
                    data.revision += 1;
                    let _ = reply.send(());
                }
                Some(CoreCommand::StartFake { request, reply }) => {
                    let _ = reply.send(data.operations.start_fake(request, &shutdown));
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
                    let result = data
                        .sessions
                        .replace(config, data.config.network.clone());
                    if result.is_ok() {
                        data.revision += 1;
                    }
                    let _ = reply.send(result);
                }
                None => break,
            },
            completion = completions.recv() => if let Some(completion) = completion {
                data.operations.complete(completion);
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
        CoreConfig, ErrorCode, EventConfig, FakeOperationRequest, OperationConfig, OperationState,
        ProfileKey, ProviderProfileConfig, RuntimeState, StorageConfig,
    };
    use std::time::Duration;
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
