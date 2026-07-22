//! Core-owned storage domains, instance lock and transactional state database.

use crate::{CoreError, ErrorCode, StorageConfig, StorageSnapshot};
use fs2::FileExt;
use redb::{Database, ReadableTable, TableDefinition};
use std::{
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
    sync::{Arc, Weak},
};

const STORAGE_SCHEMA_VERSION: u64 = 2;
const METADATA: TableDefinition<&str, u64> = TableDefinition::new("metadata");
const LOCAL_GALLERIES: TableDefinition<&str, &str> = TableDefinition::new("local_galleries");

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
            data: display_path(&self.paths.data),
            cache: display_path(&self.paths.cache),
            downloads: display_path(&self.paths.downloads),
            temp: display_path(&self.paths.temp),
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

fn display_path(path: &Path) -> String {
    path.to_string_lossy().into_owned()
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
        assert_eq!(snapshot.schema_version, 2);
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
        assert_eq!(storage.snapshot().unwrap().schema_version, 2);
        assert!(storage.gallery_registry().list().unwrap().is_empty());
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
}
