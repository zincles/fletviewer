from __future__ import annotations

import threading
from dataclasses import replace
from typing import Callable

from core.api.backend import BackendFacade
from core.api.archive import ArchiveDownloadManager, EHArchiveService
from core.api.downloads import DownloadTaskService
from core.api.images import ImageFetcherPort, ImageTaskService
from core.api.library import HistoryRepositoryPort, HistoryService, LocalGalleryManagerPort, LocalGalleryService
from core.config import BackendConfig, BackendConfigRepository, BooruConfig, EHConfig, PixivConfig, ProxyConfig
from core.net.browser_session import BrowserSessionService
from core.provider.booru import BOORU_PROVIDERS, BooruClient, create_booru_client
from core.provider.pixiv import PixivWebClient


ConfigLoader = Callable[[], dict]
DebugLogger = Callable[[str, str], None]


class BackendRuntime:
    """Owns backend services and provider clients without depending on a UI framework."""

    def __init__(
        self,
        *,
        config_repository: BackendConfigRepository | None = None,
        load_app_config: ConfigLoader | None = None,
        load_eh_config: ConfigLoader | None = None,
        load_pixiv_config: ConfigLoader | None = None,
        load_booru_config: ConfigLoader | None = None,
        log_debug: DebugLogger | None = None,
        timer_factory: Callable[[str, str], object] | None = None,
    ):
        if config_repository is None:
            loaders = (load_app_config, load_eh_config, load_pixiv_config, load_booru_config)
            if not all(loaders):
                raise TypeError("config_repository or all legacy config loaders are required")
            config_repository = _LoaderConfigRepository(
                load_app_config=load_app_config,
                load_eh_config=load_eh_config,
                load_pixiv_config=load_pixiv_config,
                load_booru_config=load_booru_config,
            )
        self.config_repository = config_repository
        self._log_debug = log_debug or (lambda _area, _message: None)
        self._lock = threading.RLock()
        self._pixiv_client: PixivWebClient | None = None
        self._pixiv_signature: tuple[str, str] | None = None
        self._booru_clients: dict[str, BooruClient] = {}
        self._download_manager: ArchiveDownloadManager | None = None
        self._download_task_service: DownloadTaskService | None = None
        self._image_fetcher: ImageFetcherPort | None = None
        self._image_task_service: ImageTaskService | None = None
        self._local_gallery_manager: LocalGalleryManagerPort | None = None
        self._local_gallery_service: LocalGalleryService | None = None
        self._history_service: HistoryService | None = None
        self._initialized = False
        self.browser_session = BrowserSessionService(
            load_app_config=self._load_network_config,
            load_eh_config=self._load_eh_config,
            log_debug=self._log_debug,
            timer_factory=timer_factory,
        )
        self.eh_archive_service = EHArchiveService(
            get_eh_client=self.browser_session.get_eh_client,
            get_download_manager=self.get_download_manager,
        )
        self.backend = BackendFacade(
            get_eh_client=self.browser_session.get_eh_client,
            get_pixiv_client=self.get_pixiv_client,
            get_booru_client=self.get_booru_client,
            eh_archive_service=self.eh_archive_service,
            get_download_task_service=self.get_download_task_service,
            get_image_task_service=self.get_image_task_service,
            get_local_gallery_service=self.get_local_gallery_service,
            get_history_service=self.get_history_service,
        )

    def configure_download_manager(self, manager: ArchiveDownloadManager) -> None:
        self._download_manager = manager
        self._download_task_service = DownloadTaskService(manager)

    def get_download_manager(self) -> ArchiveDownloadManager:
        manager = self._download_manager
        if manager is None:
            raise RuntimeError("下载管理器尚未注入 BackendRuntime")
        return manager

    def get_download_task_service(self) -> DownloadTaskService:
        service = self._download_task_service
        if service is None:
            raise RuntimeError("下载管理器尚未注入 BackendRuntime")
        return service

    def configure_image_fetcher(
        self,
        fetcher: ImageFetcherPort,
        *,
        images_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self._image_fetcher = fetcher
        self._image_task_service = ImageTaskService(fetcher, images_enabled=images_enabled)

    def get_image_task_service(self) -> ImageTaskService:
        service = self._image_task_service
        if service is None:
            raise RuntimeError("图像服务尚未注入 BackendRuntime")
        return service

    def configure_local_gallery_manager(self, manager: LocalGalleryManagerPort) -> None:
        self._local_gallery_manager = manager
        self._local_gallery_service = LocalGalleryService(manager)

    def get_local_gallery_service(self) -> LocalGalleryService:
        service = self._local_gallery_service
        if service is None:
            raise RuntimeError("本地画廊服务尚未注入 BackendRuntime")
        return service

    def configure_history_repository(self, repository: HistoryRepositoryPort) -> None:
        self._history_service = HistoryService(repository)

    def get_history_service(self) -> HistoryService:
        service = self._history_service
        if service is None:
            raise RuntimeError("历史服务尚未注入 BackendRuntime")
        return service

    def initialize(self) -> None:
        """Initialize configured stateful services once; failures remain retryable."""
        with self._lock:
            if self._initialized:
                return
            download_manager = self._download_manager
            local_gallery_manager = self._local_gallery_manager
            if download_manager is not None:
                initializer = getattr(download_manager, "initialize", None)
                if callable(initializer):
                    initializer()
            if local_gallery_manager is not None:
                initializer = getattr(local_gallery_manager, "initialize", None)
                if callable(initializer):
                    initializer()
            self._initialized = True

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shut down configured executors in reverse ownership order."""
        with self._lock:
            image_fetcher = self._image_fetcher
            download_manager = self._download_manager
            self._initialized = False
        if image_fetcher is not None:
            shutdown = getattr(image_fetcher, "shutdown", None)
            if callable(shutdown):
                shutdown(wait=wait)
        if download_manager is not None:
            shutdown = getattr(download_manager, "shutdown", None)
            if callable(shutdown):
                shutdown(wait=wait, cancel_futures=cancel_futures)
        self.invalidate_provider_clients()

    def get_pixiv_client(self) -> PixivWebClient:
        cfg = self.config_repository.load().pixiv
        signature = (cfg.cookie, cfg.user_id)
        with self._lock:
            if self._pixiv_client is not None and self._pixiv_signature != signature:
                self._pixiv_client = None
            if self._pixiv_client is None:
                self._pixiv_client = PixivWebClient(
                    transport=self.browser_session,
                    cookie=signature[0],
                    user_id=signature[1],
                    log_debug=self._log_debug,
                )
                self._pixiv_signature = signature
                self._log_debug("pixiv", f"已创建 Pixiv 网页 Provider has_cookie={bool(signature[0])}")
            return self._pixiv_client

    def save_eh_config(self, config: EHConfig, *, verify: bool = False) -> None:
        current = self.config_repository.load()
        self.config_repository.save(replace(current, eh=config))
        self.browser_session.set_login_enabled(config.login_enabled, verify=verify)

    def save_pixiv_config(self, config: PixivConfig) -> None:
        current = self.config_repository.load()
        self.config_repository.save(replace(current, pixiv=config))
        self.invalidate_pixiv_client()

    def save_booru_config(self, config: BooruConfig) -> None:
        current = self.config_repository.load()
        self.config_repository.save(replace(current, booru=config))
        self.invalidate_booru_clients()

    def save_proxy_config(self, config: ProxyConfig) -> None:
        current = self.config_repository.load()
        self.config_repository.save(replace(current, proxy=config))
        self.browser_session.configure_proxy_from_storage()

    def invalidate_pixiv_client(self) -> None:
        with self._lock:
            self._pixiv_client = None
            self._pixiv_signature = None

    def get_booru_client(self, provider_id: str) -> BooruClient:
        if provider_id not in BOORU_PROVIDERS:
            raise KeyError(f"未知 Booru Provider: {provider_id}")
        with self._lock:
            client = self._booru_clients.get(provider_id)
            if client is None:
                cfg = self.config_repository.load().booru
                credentials = {}
                if provider_id == "gelbooru":
                    credentials = {
                        "user_id": cfg.gelbooru_user_id,
                        "api_key": cfg.gelbooru_api_key,
                    }
                client = create_booru_client(
                    provider_id,
                    transport=self.browser_session,
                    log_debug=self._log_debug,
                    credentials=credentials,
                )
                self._booru_clients[provider_id] = client
            return client

    def invalidate_booru_clients(self) -> None:
        with self._lock:
            self._booru_clients.clear()

    def invalidate_provider_clients(self) -> None:
        with self._lock:
            self._pixiv_client = None
            self._pixiv_signature = None
            self._booru_clients.clear()

    def _load_network_config(self) -> dict:
        config = self.config_repository.load()
        return {
            "enable_login": config.eh.login_enabled,
            "proxy_mode": config.proxy.mode,
            "proxy_url": config.proxy.url,
        }

    def _load_eh_config(self) -> dict:
        config = self.config_repository.load().eh
        return {
            "ipb_member_id": config.ipb_member_id,
            "ipb_pass_hash": config.ipb_pass_hash,
            "igneous": config.igneous,
            "star": config.star,
        }


class _LoaderConfigRepository:
    """Temporary compatibility adapter for existing BackendRuntime embedders."""

    def __init__(self, *, load_app_config, load_eh_config, load_pixiv_config, load_booru_config):
        self._load_app_config = load_app_config
        self._load_eh_config = load_eh_config
        self._load_pixiv_config = load_pixiv_config
        self._load_booru_config = load_booru_config

    def load(self) -> BackendConfig:
        app = self._load_app_config()
        eh = dict(self._load_eh_config())
        eh["login_enabled"] = bool(app.get("enable_login", True))
        return BackendConfig.from_dict({
            "eh": eh,
            "pixiv": self._load_pixiv_config(),
            "booru": self._load_booru_config(),
            "proxy": {"mode": app.get("proxy_mode"), "url": app.get("proxy_url")},
        })

    def save(self, config: BackendConfig) -> None:
        raise RuntimeError("legacy config loaders are read-only; provide a BackendConfigRepository to save")
