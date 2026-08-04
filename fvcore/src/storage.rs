//! Core-owned storage domains, instance lock and transactional state database.

use crate::{CoreError, ErrorCode, StorageConfig, StorageSnapshot};
use fs2::FileExt;
use redb::{Database, ReadableTable, TableDefinition};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
    sync::{Arc, Weak},
};

const STORAGE_SCHEMA_VERSION: u64 = 3;
const METADATA: TableDefinition<&str, u64> = TableDefinition::new("metadata");
const LOCAL_GALLERIES: TableDefinition<&str, &str> = TableDefinition::new("local_galleries");
const FAVORITE_SEARCHES: TableDefinition<&str, &str> = TableDefinition::new("favorite_searches");

/// One provider-scoped saved search.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct FavoriteSearch {
    /// Stable favorite identifier.
    pub id: uuid::Uuid,
    /// Provider implementation identifier.
    pub provider: String,
    /// Provider profile used by the query.
    pub profile: String,
    /// User-facing label.
    pub name: String,
    /// Provider-native query text.
    pub query: String,
    /// Revision incremented when the favorite changes.
    pub revision: u64,
}

pub(crate) struct FavoriteSearchRegistry {
    database: Weak<Database>,
}

pub(crate) struct StorageService {
    paths: StoragePaths,
    database_path: PathBuf,
    database: Arc<Database>,
    lock: File,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct GalleryRegistration {
    pub(crate) id: uuid::Uuid,
    pub(crate) directory_name: String,
}

pub(crate) struct GalleryRegistry {
    database: Weak<Database>,
}

struct StoragePaths {
    data: PathBuf,
    cache: PathBuf,
    downloads: PathBuf,
    temp: PathBuf,
}

impl StorageService {
    pub(crate) fn open(config: &StorageConfig) -> Result<Self, CoreError> {
        let paths = StoragePaths {
            data: create_domain(&config.data)?,
            cache: create_domain(&config.cache)?,
            downloads: create_domain(&config.downloads)?,
            temp: create_domain(&config.temp)?,
        };
        ensure_distinct(&paths)?;

        let lock_path = paths.data.join(".fvcore.lock");
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|error| io_error("open instance lock", &lock_path, error))?;
        lock.try_lock_exclusive().map_err(|error| {
            CoreError::new(
                ErrorCode::AlreadyRunning,
                format!(
                    "storage Data domain is already owned at {}: {error}",
                    paths.data.display()
                ),
                false,
            )
        })?;

        let database_path = paths.data.join("fvcore.redb");
        let database = match open_database(&database_path) {
            Ok(database) => database,
            Err(error) => {
                let _ = FileExt::unlock(&lock);
                return Err(error);
            }
        };
        initialize_schema(&database)?;

        Ok(Self {
            paths,
            database_path,
            database: Arc::new(database),
            lock,
        })
    }

    pub(crate) fn snapshot(&self) -> Result<StorageSnapshot, CoreError> {
        let database_bytes = fs::metadata(&self.database_path)
            .map_err(|error| io_error("read database metadata", &self.database_path, error))?
            .len();
        Ok(StorageSnapshot {
            schema_version: STORAGE_SCHEMA_VERSION as u32,
            data_identity: storage_identity("data", &self.paths.data),
            cache_identity: storage_identity("cache", &self.paths.cache),
            downloads_identity: storage_identity("downloads", &self.paths.downloads),
            temp_identity: storage_identity("temp", &self.paths.temp),
            database_bytes,
        })
    }

    pub(crate) fn cache_path(&self) -> PathBuf {
        self.paths.cache.clone()
    }

    pub(crate) fn downloads_path(&self) -> PathBuf {
        self.paths.downloads.clone()
    }

    pub(crate) fn gallery_registry(&self) -> Arc<GalleryRegistry> {
        Arc::new(GalleryRegistry {
            database: Arc::downgrade(&self.database),
        })
    }

    pub(crate) fn favorite_search_registry(&self) -> Arc<FavoriteSearchRegistry> {
        Arc::new(FavoriteSearchRegistry {
            database: Arc::downgrade(&self.database),
        })
    }
}

impl FavoriteSearchRegistry {
    pub(crate) fn list(&self) -> Result<Vec<FavoriteSearch>, CoreError> {
        let database = self.database()?;
        let read = database.begin_read().map_err(database_error)?;
        let table = read.open_table(FAVORITE_SEARCHES).map_err(database_error)?;
        let mut favorites = Vec::new();
        for entry in table.iter().map_err(database_error)? {
            let (_, value) = entry.map_err(database_error)?;
            favorites.push(serde_json::from_str(value.value()).map_err(|_| {
                CoreError::new(
                    ErrorCode::IntegrityMismatch,
                    "favorite search is invalid",
                    false,
                )
            })?);
        }
        favorites.sort_by(|left: &FavoriteSearch, right| {
            left.name.cmp(&right.name).then(left.id.cmp(&right.id))
        });
        Ok(favorites)
    }

    pub(crate) fn create(
        &self,
        provider: String,
        profile: String,
        name: String,
        query: String,
    ) -> Result<FavoriteSearch, CoreError> {
        validate_favorite(&provider, &profile, &name, &query)?;
        let favorite = FavoriteSearch {
            id: uuid::Uuid::now_v7(),
            provider,
            profile,
            name,
            query,
            revision: 1,
        };
        let json = serde_json::to_string(&favorite).map_err(database_error)?;
        let database = self.database()?;
        let write = database.begin_write().map_err(database_error)?;
        {
            let mut table = write
                .open_table(FAVORITE_SEARCHES)
                .map_err(database_error)?;
            table
                .insert(favorite.id.to_string().as_str(), json.as_str())
                .map_err(database_error)?;
        }
        write.commit().map_err(database_error)?;
        Ok(favorite)
    }

    pub(crate) fn remove(&self, id: uuid::Uuid) -> Result<bool, CoreError> {
        let database = self.database()?;
        let write = database.begin_write().map_err(database_error)?;
        let removed = {
            let mut table = write
                .open_table(FAVORITE_SEARCHES)
                .map_err(database_error)?;
            table
                .remove(id.to_string().as_str())
                .map_err(database_error)?
                .is_some()
        };
        write.commit().map_err(database_error)?;
        Ok(removed)
    }

    fn database(&self) -> Result<Arc<Database>, CoreError> {
        self.database.upgrade().ok_or_else(|| {
            CoreError::new(
                ErrorCode::NotReady,
                "favorite search registry is unavailable",
                false,
            )
        })
    }
}

fn validate_favorite(
    provider: &str,
    profile: &str,
    name: &str,
    query: &str,
) -> Result<(), CoreError> {
    if !matches!(provider, "eh" | "danbooru" | "gelbooru" | "pixiv") {
        return Err(CoreError::new(
            ErrorCode::InvalidInput,
            "favorite search provider is unsupported",
            false,
        ));
    }
    if profile.trim().is_empty()
        || name.trim().is_empty()
        || query.trim().is_empty()
        || name.len() > 120
        || query.len() > 2_000
    {
        return Err(CoreError::new(
            ErrorCode::InvalidInput,
            "favorite search profile, name and query must be nonempty and bounded",
            false,
        ));
    }
    Ok(())
}

impl GalleryRegistry {
    pub(crate) fn list(&self) -> Result<Vec<GalleryRegistration>, CoreError> {
        let database = self.database()?;
        let read = database.begin_read().map_err(database_error)?;
        let table = read.open_table(LOCAL_GALLERIES).map_err(database_error)?;
        let mut registrations = Vec::new();
        for entry in table.iter().map_err(database_error)? {
            let (id, directory_name) = entry.map_err(database_error)?;
            let id = uuid::Uuid::parse_str(id.value()).map_err(|_| {
                CoreError::new(
                    ErrorCode::IntegrityMismatch,
                    "local gallery registry contains an invalid gallery ID",
                    false,
                )
            })?;
            registrations.push(GalleryRegistration {
                id,
                directory_name: directory_name.value().to_owned(),
            });
        }
        registrations.sort_by_key(|registration| registration.id);
        Ok(registrations)
    }

    pub(crate) fn register(&self, id: uuid::Uuid, directory_name: &str) -> Result<(), CoreError> {
        if !safe_directory_name(directory_name) {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "local gallery registry requires a direct directory name",
                false,
            ));
        }
        let database = self.database()?;
        let write = database.begin_write().map_err(database_error)?;
        {
            let mut table = write.open_table(LOCAL_GALLERIES).map_err(database_error)?;
            if let Some(existing) = table.get(id.to_string().as_str()).map_err(database_error)? {
                if existing.value() == directory_name {
                    return Ok(());
                }
                return Err(CoreError::new(
                    ErrorCode::IntegrityMismatch,
                    "local gallery ID is already registered to another directory",
                    false,
                ));
            }
            for entry in table.iter().map_err(database_error)? {
                let (existing_id, existing_directory) = entry.map_err(database_error)?;
                if existing_directory.value() == directory_name {
                    return Err(CoreError::new(
                        ErrorCode::IntegrityMismatch,
                        format!(
                            "local gallery directory is already registered as {}",
                            existing_id.value()
                        ),
                        false,
                    ));
                }
            }
            table
                .insert(id.to_string().as_str(), directory_name)
                .map_err(database_error)?;
        }
        write.commit().map_err(database_error)
    }

    pub(crate) fn remove(&self, id: uuid::Uuid) -> Result<(), CoreError> {
        let database = self.database()?;
        let write = database.begin_write().map_err(database_error)?;
        {
            let mut table = write.open_table(LOCAL_GALLERIES).map_err(database_error)?;
            table
                .remove(id.to_string().as_str())
                .map_err(database_error)?;
        }
        write.commit().map_err(database_error)
    }

    fn database(&self) -> Result<Arc<Database>, CoreError> {
        self.database.upgrade().ok_or_else(|| {
            CoreError::new(
                ErrorCode::NotReady,
                "local gallery registry is no longer available",
                false,
            )
        })
    }
}

impl Drop for StorageService {
    fn drop(&mut self) {
        if let Err(error) = FileExt::unlock(&self.lock) {
            tracing::warn!(%error, "failed to release storage instance lock");
        }
    }
}

fn create_domain(path: &Path) -> Result<PathBuf, CoreError> {
    fs::create_dir_all(path).map_err(|error| io_error("create storage domain", path, error))?;
    path.canonicalize()
        .map_err(|error| io_error("canonicalize storage domain", path, error))
}

fn ensure_distinct(paths: &StoragePaths) -> Result<(), CoreError> {
    let domains = [&paths.data, &paths.cache, &paths.downloads, &paths.temp];
    for (index, path) in domains.iter().enumerate() {
        for other in domains.iter().skip(index + 1) {
            if path == other || path.starts_with(other) || other.starts_with(path) {
                return Err(CoreError::new(
                    ErrorCode::InvalidConfig,
                    format!(
                        "storage domains must be distinct and non-overlapping: {} and {}",
                        path.display(),
                        other.display()
                    ),
                    false,
                ));
            }
        }
    }
    Ok(())
}

fn open_database(path: &Path) -> Result<Database, CoreError> {
    Database::create(path).map_err(|error| {
        CoreError::new(
            ErrorCode::Io,
            format!("failed to open Core database {}: {error}", path.display()),
            false,
        )
    })
}

fn initialize_schema(database: &Database) -> Result<(), CoreError> {
    let write = database.begin_write().map_err(database_error)?;
    {
        let mut metadata = write.open_table(METADATA).map_err(database_error)?;
        let current_version = metadata
            .get("schema_version")
            .map_err(database_error)?
            .map(|version| version.value());
        match current_version {
            Some(version) if version > STORAGE_SCHEMA_VERSION || version == 0 => {
                return Err(CoreError::new(
                    ErrorCode::InvalidConfig,
                    format!("unsupported storage schema version {version}"),
                    false,
                ));
            }
            Some(version) if version < STORAGE_SCHEMA_VERSION => {
                metadata
                    .insert("schema_version", STORAGE_SCHEMA_VERSION)
                    .map_err(database_error)?;
            }
            Some(_) => {}
            None => {
                metadata
                    .insert("schema_version", STORAGE_SCHEMA_VERSION)
                    .map_err(database_error)?;
            }
        }
    }
    write.open_table(LOCAL_GALLERIES).map_err(database_error)?;
    write
        .open_table(FAVORITE_SEARCHES)
        .map_err(database_error)?;
    write.commit().map_err(database_error)
}

fn safe_directory_name(name: &str) -> bool {
    let path = Path::new(name);
    !name.is_empty()
        && !name.starts_with('.')
        && !path.is_absolute()
        && path.parent().is_some_and(|parent| parent == Path::new(""))
        && path.file_name().and_then(|value| value.to_str()) == Some(name)
}

fn database_error(error: impl std::fmt::Display) -> CoreError {
    CoreError::new(
        ErrorCode::Io,
        format!("Core database operation failed: {error}"),
        false,
    )
}

fn io_error(action: &str, path: &Path, error: std::io::Error) -> CoreError {
    CoreError::new(
        ErrorCode::Io,
        format!("failed to {action} {}: {error}", path.display()),
        false,
    )
}

fn storage_identity(domain: &str, path: &Path) -> String {
    let input = format!("fvcore-storage-v1:{domain}:{}", path.to_string_lossy());
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in input.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3_u64);
    }
    format!("v1-{hash:016x}")
}

#[cfg(test)]
mod tests {
    use super::{METADATA, StorageService, open_database};
    use crate::{ErrorCode, StorageConfig};
    use tempfile::TempDir;

    fn config(temp: &TempDir) -> StorageConfig {
        StorageConfig {
            data: temp.path().join("Data"),
            cache: temp.path().join("Cache"),
            downloads: temp.path().join("Downloads"),
            temp: temp.path().join("Temp"),
        }
    }

    #[test]
    fn creates_domains_and_schema() {
        let temp = TempDir::new().unwrap();
        let storage = StorageService::open(&config(&temp)).unwrap();
        let snapshot = storage.snapshot().unwrap();
        assert_eq!(snapshot.schema_version, 3);
        assert!(snapshot.database_bytes > 0);
        assert!(temp.path().join("Data/fvcore.redb").is_file());

        let registry = storage.gallery_registry();
        let id = uuid::Uuid::now_v7();
        registry.register(id, "gallery one").unwrap();
        registry.register(id, "gallery one").unwrap();
        assert_eq!(registry.list().unwrap()[0].directory_name, "gallery one");
        assert!(registry.register(id, "gallery two").is_err());
        registry.remove(id).unwrap();
        assert!(registry.list().unwrap().is_empty());
    }

    #[test]
    fn migrates_v1_database_and_creates_gallery_registry() {
        let temp = TempDir::new().unwrap();
        std::fs::create_dir_all(temp.path().join("Data")).unwrap();
        let path = temp.path().join("Data/fvcore.redb");
        let database = open_database(&path).unwrap();
        let write = database.begin_write().unwrap();
        {
            let mut metadata = write.open_table(METADATA).unwrap();
            metadata.insert("schema_version", 1).unwrap();
        }
        write.commit().unwrap();
        drop(database);

        let storage = StorageService::open(&config(&temp)).unwrap();
        assert_eq!(storage.snapshot().unwrap().schema_version, 3);
        assert!(storage.gallery_registry().list().unwrap().is_empty());
    }

    #[test]
    fn favorite_searches_are_provider_scoped_and_persistent() {
        let temp = TempDir::new().unwrap();
        let config = config(&temp);
        let storage = StorageService::open(&config).unwrap();
        let registry = storage.favorite_search_registry();
        let favorite = registry
            .create(
                "eh".to_owned(),
                "default".to_owned(),
                "landscapes".to_owned(),
                "landscape language:english".to_owned(),
            )
            .unwrap();
        assert_eq!(
            registry.list().unwrap()[0].query,
            "landscape language:english"
        );
        assert!(
            registry
                .create(
                    "danbooru".to_owned(),
                    "default".to_owned(),
                    "x".to_owned(),
                    "x".to_owned()
                )
                .is_ok()
        );
        assert!(
            registry
                .create(
                    "pixiv".to_owned(),
                    "default".to_owned(),
                    "x".to_owned(),
                    "x".to_owned()
                )
                .is_ok()
        );
        assert!(
            registry
                .create(
                    "unsupported".to_owned(),
                    "default".to_owned(),
                    "x".to_owned(),
                    "x".to_owned()
                )
                .is_err()
        );
        assert!(registry.remove(favorite.id).unwrap());
        assert_eq!(registry.list().unwrap().len(), 2);
    }

    #[test]
    fn rejects_second_owner() {
        let temp = TempDir::new().unwrap();
        let config = config(&temp);
        let first = StorageService::open(&config).unwrap();
        let error = match StorageService::open(&config) {
            Ok(_) => panic!("second storage owner must be rejected"),
            Err(error) => error,
        };
        assert_eq!(error.code(), ErrorCode::AlreadyRunning);
        drop(first);
        StorageService::open(&config).unwrap();
    }

    #[test]
    fn storage_snapshot_uses_stable_opaque_domain_identities() {
        let temp = TempDir::new().unwrap();
        let first = StorageService::open(&config(&temp)).unwrap();
        let first_snapshot = first.snapshot().unwrap();
        drop(first);
        let second = StorageService::open(&config(&temp)).unwrap();
        let second_snapshot = second.snapshot().unwrap();

        assert_eq!(first_snapshot.data_identity, second_snapshot.data_identity);
        assert_eq!(
            first_snapshot.cache_identity,
            second_snapshot.cache_identity
        );
        assert_eq!(
            first_snapshot.downloads_identity,
            second_snapshot.downloads_identity
        );
        assert_eq!(first_snapshot.temp_identity, second_snapshot.temp_identity);
        assert!(first_snapshot.data_identity.starts_with("v1-"));
        assert!(
            !first_snapshot
                .data_identity
                .contains(temp.path().to_str().unwrap())
        );
    }
}
