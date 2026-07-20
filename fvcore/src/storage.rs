//! Core-owned storage domains, instance lock and transactional state database.

use crate::{CoreError, ErrorCode, StorageConfig, StorageSnapshot};
use fs2::FileExt;
use redb::{Database, ReadableTable, TableDefinition};
use std::{
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
};

const STORAGE_SCHEMA_VERSION: u64 = 1;
const METADATA: TableDefinition<&str, u64> = TableDefinition::new("metadata");

pub(crate) struct StorageService {
    paths: StoragePaths,
    database_path: PathBuf,
    _database: Database,
    lock: File,
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
            _database: database,
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
            Some(version) if version != STORAGE_SCHEMA_VERSION => {
                return Err(CoreError::new(
                    ErrorCode::InvalidConfig,
                    format!("unsupported storage schema version {version}"),
                    false,
                ));
            }
            Some(_) => {}
            None => {
                metadata
                    .insert("schema_version", STORAGE_SCHEMA_VERSION)
                    .map_err(database_error)?;
            }
        }
    }
    write.commit().map_err(database_error)
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
    use super::StorageService;
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
        assert_eq!(snapshot.schema_version, 1);
        assert!(snapshot.database_bytes > 0);
        assert!(temp.path().join("Data/fvcore.redb").is_file());
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
