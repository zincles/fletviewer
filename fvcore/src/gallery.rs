//! Local gallery library consuming completed persistent Archive tasks.

use crate::{
    ArchiveTaskState, CoreError, ErrorCode,
    archive::{ArchiveConsumption, ArchiveService},
    image::detect_format,
};
use bytes::Bytes;
use serde::{Deserialize, Serialize};
use std::{
    cmp::Ordering,
    collections::{HashMap, HashSet},
    fs::File,
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::Arc,
};
use time::OffsetDateTime;
use tokio::sync::{Mutex, RwLock, Semaphore};

const MAX_COVER_BYTES: u64 = 64 * 1024 * 1024;
const MAX_IMAGE_MEMBERS: usize = 100_000;
const MAX_TOTAL_IMAGE_BYTES: u64 = 64 * 1024 * 1024 * 1024;
const COMIC_INFO_FILENAME: &str = "ComicInfo.xml";
const DELETE_CONFIRMATION_SECONDS: i64 = 300;

/// Safe summary of one local gallery backed by an original EH Archive ZIP.
#[derive(Clone, Debug, Serialize)]
pub struct LocalGallerySummary {
    /// Stable local gallery ID derived from the Archive task.
    pub id: uuid::Uuid,
    /// Provider implementation identifier. Currently always `eh`.
    pub provider: String,
    /// EH gallery ID.
    pub gid: u64,
    /// EH gallery token.
    pub token: String,
    /// Gallery title captured before Archive submission.
    pub title: String,
    /// Archive byte length.
    pub archive_bytes: u64,
    /// Whether an extracted local cover is available.
    pub cover_available: bool,
    /// Whether the deterministic `ComicInfo.xml` is available.
    pub comic_info_available: bool,
    /// Creation timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub created_at: OffsetDateTime,
    /// Last metadata update timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub updated_at: OffsetDateTime,
}

/// Safe metadata for one naturally sorted image member in a local gallery ZIP.
#[derive(Clone, Debug, Serialize)]
pub struct LocalGalleryPage {
    /// Stable zero-based page ID within the immutable original ZIP.
    pub id: u32,
    /// One-based display number.
    pub number: u32,
    /// Original ZIP member name for display only.
    pub filename: String,
    /// MIME type inferred from the member extension before bytes are read.
    pub mime_type: String,
    /// Declared uncompressed byte length.
    pub byte_length: u64,
}

/// Local gallery metadata together with its readable pages.
#[derive(Clone, Debug, Serialize)]
pub struct LocalGalleryDetail {
    /// Gallery summary without server paths.
    pub gallery: LocalGallerySummary,
    /// Total number of naturally sorted safe image members.
    pub total_pages: u32,
    /// Zero-based offset of the returned page window.
    pub offset: u32,
    /// Naturally sorted safe image members in the requested window.
    pub pages: Vec<LocalGalleryPage>,
}

/// Kind of an immutable local gallery binary resource.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalGalleryResourceKind {
    /// Extracted cover bytes.
    Cover,
    /// One image page extracted from the original ZIP.
    Page,
}

/// Descriptor for one bounded local gallery image resource.
#[derive(Clone, Debug, Serialize)]
pub struct LocalGalleryResourceDescriptor {
    /// Stable local gallery ID.
    pub gallery_id: uuid::Uuid,
    /// Resource kind.
    pub kind: LocalGalleryResourceKind,
    /// Stable zero-based page ID for page resources.
    pub page_id: Option<u32>,
    /// MIME type detected from the actual bytes.
    pub mime_type: String,
    /// Exact resource byte length.
    pub byte_length: usize,
}

/// Immutable bounded binary image resource from a local gallery.
#[derive(Clone, Debug)]
pub struct LocalGalleryResource {
    descriptor: LocalGalleryResourceDescriptor,
    bytes: Bytes,
}

impl LocalGalleryResource {
    /// Returns the safe resource descriptor.
    #[must_use]
    pub fn descriptor(&self) -> &LocalGalleryResourceDescriptor {
        &self.descriptor
    }

    /// Returns a cheap clone of the immutable page bytes.
    #[must_use]
    pub fn bytes(&self) -> Bytes {
        self.bytes.clone()
    }
}

/// Short-lived preview that must be returned unchanged to delete a local gallery.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct LocalGalleryDeleteConfirmation {
    /// Gallery that will be deleted.
    pub gallery_id: uuid::Uuid,
    /// One-use confirmation token bound to the current direct file set.
    pub confirmation_token: uuid::Uuid,
    /// Number of ordinary files that will be removed.
    pub file_count: usize,
    /// Total bytes occupied by those files.
    pub total_bytes: u64,
    /// Token expiry timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub expires_at: OffsetDateTime,
}

/// Explicit request committing a previously previewed local gallery deletion.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalGalleryDeleteRequest {
    /// One-use token returned by [`LocalGalleryDeleteConfirmation`].
    pub confirmation_token: uuid::Uuid,
}

/// Result of an explicitly confirmed local gallery deletion.
#[derive(Clone, Debug, Serialize)]
pub struct LocalGalleryDeleteResult {
    /// Deleted gallery ID.
    pub gallery_id: uuid::Uuid,
    /// Number of ordinary files removed.
    pub deleted_files: usize,
    /// Total bytes represented by the confirmed file set.
    pub deleted_bytes: u64,
}

/// Persisted local gallery record backed by one original EH Archive ZIP.
#[derive(Clone, Debug, Deserialize, Serialize)]
struct LocalGalleryRecord {
    /// Metadata schema version. Currently `1`.
    pub schema_version: u32,
    /// Archive task that committed this gallery.
    pub download_task_id: uuid::Uuid,
    /// EH gallery ID.
    pub gid: u64,
    /// EH gallery token.
    pub token: String,
    /// Gallery title captured before Archive submission.
    pub title: String,
    /// Server-side gallery directory.
    pub directory: String,
    /// Original Archive filename.
    pub archive_filename: String,
    /// Extracted cover filename when a safe image member exists.
    pub cover_filename: Option<String>,
    /// Archive byte length.
    pub archive_bytes: u64,
    /// Creation timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub created_at: OffsetDateTime,
    /// Last metadata update timestamp.
    #[serde(with = "time::serde::rfc3339")]
    pub updated_at: OffsetDateTime,
}

#[derive(Debug)]
struct ImageMember {
    key: NaturalKey,
    zip_index: usize,
    filename: String,
    byte_length: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct GalleryDeletePlan {
    directory: PathBuf,
    files: Vec<(String, u64)>,
    total_bytes: u64,
}

#[derive(Debug)]
struct PendingGalleryDelete {
    gallery_id: uuid::Uuid,
    expires_at: OffsetDateTime,
    plan: GalleryDeletePlan,
}

/// Snapshot of a deterministic `ComicInfo.xml` derived from a local gallery.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ComicInfoSnapshot {
    /// Archive task ID identifying the local gallery.
    pub gallery_id: uuid::Uuid,
    /// Derived metadata filename. Always `ComicInfo.xml`.
    pub filename: String,
    /// Number of safe image pages represented by the metadata.
    pub page_count: usize,
    /// Serialized XML byte length.
    pub bytes: u64,
}

pub(crate) struct GalleryService {
    root: PathBuf,
    archives: Arc<ArchiveService>,
    max_resource_bytes: usize,
    resource_permits: Arc<Semaphore>,
    occupancy: Arc<RwLock<()>>,
    pending_deletes: Mutex<HashMap<uuid::Uuid, PendingGalleryDelete>>,
}

impl GalleryService {
    pub(crate) async fn open(
        downloads: PathBuf,
        archives: Arc<ArchiveService>,
        max_resource_bytes: usize,
        max_inflight_bytes: usize,
    ) -> Result<Arc<Self>, CoreError> {
        let root = downloads.join("EHArchieve");
        tokio::fs::create_dir_all(&root)
            .await
            .map_err(|error| io_error("create local gallery directory", &root, error))?;
        let service = Arc::new(Self {
            root,
            archives,
            max_resource_bytes,
            resource_permits: Arc::new(Semaphore::new(
                max_inflight_bytes.saturating_div(max_resource_bytes).max(1),
            )),
            occupancy: Arc::new(RwLock::new(())),
            pending_deletes: Mutex::new(HashMap::new()),
        });
        service.recover_deletions().await?;
        service.consume_pending().await;
        Ok(service)
    }

    pub(crate) async fn consume_pending(&self) {
        for consumption in self.archives.completed_for_consumption().await {
            match self.consume(consumption).await {
                Ok((id, path)) => {
                    let _ = self
                        .archives
                        .mark_consumed(id, Some(path.to_string_lossy().into_owned()), None)
                        .await;
                }
                Err((id, error)) => {
                    let _ = self
                        .archives
                        .mark_consumed(id, None, Some(error.message().to_owned()))
                        .await;
                }
            }
        }
    }

    async fn recover_deletions(&self) -> Result<(), CoreError> {
        let root = self.root.clone();
        let deletions = tokio::task::spawn_blocking(move || pending_deletion_tickets(&root))
            .await
            .map_err(|_| {
                CoreError::new(ErrorCode::Internal, "local gallery worker panicked", false)
            })??;
        for deletion in deletions {
            self.archives
                .mark_local_gallery_deleted(deletion.id)
                .await?;
            tokio::task::spawn_blocking(move || {
                delete_tombstone(&deletion.tombstone, &deletion.plan)?;
                std::fs::remove_file(&deletion.ticket).map_err(|error| {
                    io_error(
                        "remove local gallery deletion ticket",
                        &deletion.ticket,
                        error,
                    )
                })
            })
            .await
            .map_err(|_| {
                CoreError::new(ErrorCode::Internal, "local gallery worker panicked", false)
            })??;
        }
        Ok(())
    }

    pub(crate) async fn list(&self) -> Vec<LocalGallerySummary> {
        let _occupancy = self.occupancy.read().await;
        let root = self.root.clone();
        tokio::task::spawn_blocking(move || {
            scan(&root)
                .into_iter()
                .map(|record| summary(&record))
                .collect()
        })
        .await
        .unwrap_or_default()
    }

    pub(crate) async fn detail(
        &self,
        id: uuid::Uuid,
        offset: u32,
        limit: u32,
    ) -> Result<LocalGalleryDetail, CoreError> {
        if limit == 0 || limit > 500 {
            return Err(CoreError::new(
                ErrorCode::InvalidInput,
                "local gallery page limit must be between 1 and 500",
                false,
            ));
        }
        let occupancy = self.occupancy.clone().read_owned().await;
        let root = self.root.clone();
        let max_page_bytes = self.max_resource_bytes;
        tokio::task::spawn_blocking(move || {
            let _occupancy = occupancy;
            gallery_detail(&root, id, offset, limit, max_page_bytes)
        })
        .await
        .map_err(|_| CoreError::new(ErrorCode::Internal, "local gallery worker panicked", false))?
    }

    pub(crate) async fn page(
        &self,
        id: uuid::Uuid,
        page_id: u32,
    ) -> Result<LocalGalleryResource, CoreError> {
        let occupancy = self.occupancy.clone().read_owned().await;
        let root = self.root.clone();
        let max_page_bytes = self.max_resource_bytes;
        let permit = self
            .resource_permits
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| {
                CoreError::new(ErrorCode::NotReady, "local gallery is shutting down", true)
            })?;
        tokio::task::spawn_blocking(move || {
            let _occupancy = occupancy;
            let _permit = permit;
            read_gallery_page(&root, id, page_id, max_page_bytes)
        })
        .await
        .map_err(|_| CoreError::new(ErrorCode::Internal, "local gallery worker panicked", false))?
    }

    pub(crate) async fn cover(&self, id: uuid::Uuid) -> Result<LocalGalleryResource, CoreError> {
        let occupancy = self.occupancy.clone().read_owned().await;
        let root = self.root.clone();
        let max_resource_bytes = self.max_resource_bytes;
        let permit = self
            .resource_permits
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| {
                CoreError::new(ErrorCode::NotReady, "local gallery is shutting down", true)
            })?;
        tokio::task::spawn_blocking(move || {
            let _occupancy = occupancy;
            let _permit = permit;
            read_gallery_cover(&root, id, max_resource_bytes)
        })
        .await
        .map_err(|_| CoreError::new(ErrorCode::Internal, "local gallery worker panicked", false))?
    }

    pub(crate) async fn generate_comic_info(
        &self,
        id: uuid::Uuid,
    ) -> Result<ComicInfoSnapshot, CoreError> {
        let occupancy = self.occupancy.clone().write_owned().await;
        let root = self.root.clone();
        tokio::task::spawn_blocking(move || {
            let _occupancy = occupancy;
            generate_comic_info_by_id(&root, id)
        })
        .await
        .map_err(|_| CoreError::new(ErrorCode::Internal, "ComicInfo worker panicked", false))?
    }

    pub(crate) async fn delete_comic_info(&self, id: uuid::Uuid) -> Result<(), CoreError> {
        let occupancy = self.occupancy.clone().write_owned().await;
        let root = self.root.clone();
        tokio::task::spawn_blocking(move || {
            let _occupancy = occupancy;
            delete_comic_info_by_id(&root, id)
        })
        .await
        .map_err(|_| CoreError::new(ErrorCode::Internal, "ComicInfo worker panicked", false))?
    }

    pub(crate) async fn prepare_delete(
        &self,
        id: uuid::Uuid,
    ) -> Result<LocalGalleryDeleteConfirmation, CoreError> {
        let occupancy = self.occupancy.clone().read_owned().await;
        let root = self.root.clone();
        let plan = tokio::task::spawn_blocking(move || {
            let _occupancy = occupancy;
            gallery_delete_plan(&root, id)
        })
        .await
        .map_err(|_| {
            CoreError::new(ErrorCode::Internal, "local gallery worker panicked", false)
        })??;
        let confirmation_token = uuid::Uuid::now_v7();
        let expires_at = OffsetDateTime::now_utc()
            .checked_add(time::Duration::seconds(DELETE_CONFIRMATION_SECONDS))
            .expect("short confirmation lifetime fits timestamp");
        let confirmation = LocalGalleryDeleteConfirmation {
            gallery_id: id,
            confirmation_token,
            file_count: plan.files.len(),
            total_bytes: plan.total_bytes,
            expires_at,
        };
        let now = OffsetDateTime::now_utc();
        let mut pending = self.pending_deletes.lock().await;
        pending.retain(|_, value| value.expires_at > now);
        pending.insert(
            confirmation_token,
            PendingGalleryDelete {
                gallery_id: id,
                expires_at,
                plan,
            },
        );
        Ok(confirmation)
    }

    pub(crate) async fn delete(
        &self,
        id: uuid::Uuid,
        request: LocalGalleryDeleteRequest,
    ) -> Result<LocalGalleryDeleteResult, CoreError> {
        let pending = self
            .pending_deletes
            .lock()
            .await
            .remove(&request.confirmation_token)
            .ok_or_else(invalid_delete_confirmation)?;
        if pending.gallery_id != id || pending.expires_at <= OffsetDateTime::now_utc() {
            return Err(invalid_delete_confirmation());
        }
        let _occupancy = self.occupancy.write().await;
        let current = gallery_delete_plan(&self.root, id)?;
        if current != pending.plan {
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "local gallery changed after deletion was previewed",
                true,
            ));
        }
        let tombstone = self
            .root
            .join(format!(".delete.{}.{}", id, request.confirmation_token));
        let ticket = self.root.join(format!(
            ".delete.{}.{}.json",
            id, request.confirmation_token
        ));
        atomic_json(&ticket, &current)?;
        std::fs::rename(&current.directory, &tombstone).map_err(|error| {
            let _ = std::fs::remove_file(&ticket);
            io_error(
                "hide local gallery before confirmed deletion",
                &current.directory,
                error,
            )
        })?;
        if let Err(error) = self.archives.mark_local_gallery_deleted(id).await {
            let _ = std::fs::rename(&tombstone, &current.directory);
            let _ = std::fs::remove_file(&ticket);
            return Err(error);
        }
        delete_tombstone(&tombstone, &current)?;
        std::fs::remove_file(&ticket)
            .map_err(|error| io_error("remove local gallery deletion ticket", &ticket, error))?;
        Ok(LocalGalleryDeleteResult {
            gallery_id: id,
            deleted_files: current.files.len(),
            deleted_bytes: current.total_bytes,
        })
    }

    async fn consume(
        &self,
        consumption: ArchiveConsumption,
    ) -> Result<(uuid::Uuid, PathBuf), (uuid::Uuid, CoreError)> {
        let id = consumption.task.id;
        let occupancy = self.occupancy.clone().write_owned().await;
        let root = self.root.clone();
        tokio::task::spawn_blocking(move || {
            let _occupancy = occupancy;
            consume_blocking(&root, consumption)
        })
        .await
        .map_err(|_| {
            (
                id,
                CoreError::new(ErrorCode::Internal, "local gallery worker panicked", false),
            )
        })?
        .map(|path| (id, path))
        .map_err(|error| (id, error))
    }
}

fn consume_blocking(root: &Path, consumption: ArchiveConsumption) -> Result<PathBuf, CoreError> {
    if consumption.task.state != ArchiveTaskState::Completed || !consumption.archive_path.is_file()
    {
        return Err(CoreError::new(
            ErrorCode::ResourceNotFound,
            "completed Archive ZIP is missing",
            false,
        ));
    }
    if let Some(existing) = find_by_task(root, consumption.task.id) {
        let _ = std::fs::remove_file(&consumption.archive_path);
        return Ok(existing);
    }
    let directory_name = gallery_directory_name(
        consumption.task.gallery.gid,
        &consumption.task.gallery.token,
        &consumption.task.title,
    );
    let final_directory = unique_path(&root.join(directory_name))?;
    let staging = root.join(format!(
        ".{}.{}.staging",
        final_directory
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("gallery"),
        consumption.task.id
    ));
    if staging.exists() {
        std::fs::remove_dir_all(&staging)
            .map_err(|error| io_error("remove stale gallery staging directory", &staging, error))?;
    }
    std::fs::create_dir(&staging)
        .map_err(|error| io_error("create gallery staging directory", &staging, error))?;
    let archive_filename = consumption
        .archive_path
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            CoreError::new(
                ErrorCode::InvalidInput,
                "Archive filename is not valid UTF-8",
                false,
            )
        })?
        .to_owned();
    let staging_archive = staging.join(&archive_filename);
    if let Err(error) = move_file(&consumption.archive_path, &staging_archive) {
        let _ = std::fs::remove_dir_all(&staging);
        return Err(error);
    }
    let result = (|| {
        let cover_filename = inspect_and_extract_cover(&staging_archive, &staging)?;
        let now = OffsetDateTime::now_utc();
        let metadata = LocalGalleryRecord {
            schema_version: 1,
            download_task_id: consumption.task.id,
            gid: consumption.task.gallery.gid,
            token: consumption.task.gallery.token,
            title: consumption.task.title,
            directory: final_directory.to_string_lossy().into_owned(),
            archive_filename,
            cover_filename,
            archive_bytes: std::fs::metadata(&staging_archive)
                .map_err(|error| {
                    io_error("read gallery Archive metadata", &staging_archive, error)
                })?
                .len(),
            created_at: now,
            updated_at: now,
        };
        atomic_json(&staging.join("gallery.json"), &metadata)?;
        generate_comic_info(&staging, &metadata)?;
        std::fs::rename(&staging, &final_directory)
            .map_err(|error| io_error("commit local gallery directory", &final_directory, error))?;
        Ok(final_directory.clone())
    })();
    if result.is_err() {
        if staging_archive.exists() && !consumption.archive_path.exists() {
            let _ = move_file(&staging_archive, &consumption.archive_path);
        }
        let _ = std::fs::remove_dir_all(&staging);
    }
    result
}

fn inspect_and_extract_cover(zip_path: &Path, output: &Path) -> Result<Option<String>, CoreError> {
    let file =
        File::open(zip_path).map_err(|error| io_error("open gallery ZIP", zip_path, error))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|error| {
        CoreError::new(
            ErrorCode::Parse,
            format!("invalid gallery ZIP: {error}"),
            false,
        )
    })?;
    let candidates = image_members(&mut archive, u64::MAX)?;
    let Some(candidate) = candidates.first() else {
        return Ok(None);
    };
    let mut member = archive.by_index(candidate.zip_index).map_err(|error| {
        CoreError::new(
            ErrorCode::Parse,
            format!("failed to open ZIP cover: {error}"),
            false,
        )
    })?;
    if member.size() > MAX_COVER_BYTES {
        return Err(CoreError::new(
            ErrorCode::ResponseTooLarge,
            "gallery cover exceeds 64 MiB",
            false,
        ));
    }
    let extension = Path::new(member.name())
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("jpg")
        .to_ascii_lowercase();
    let extension = if extension == "jpeg" {
        "jpg"
    } else {
        &extension
    };
    let filename = format!("thumb.{extension}");
    let path = output.join(&filename);
    let mut cover =
        File::create(&path).map_err(|error| io_error("create gallery cover", &path, error))?;
    std::io::copy(&mut member, &mut cover)
        .map_err(|error| io_error("extract gallery cover", &path, error))?;
    cover
        .flush()
        .map_err(|error| io_error("flush gallery cover", &path, error))?;
    Ok(Some(filename))
}

fn generate_comic_info_by_id(root: &Path, id: uuid::Uuid) -> Result<ComicInfoSnapshot, CoreError> {
    let gallery = scan(root)
        .into_iter()
        .find(|gallery| gallery.download_task_id == id)
        .ok_or_else(local_gallery_not_found)?;
    generate_comic_info(Path::new(&gallery.directory), &gallery)
}

fn summary(record: &LocalGalleryRecord) -> LocalGallerySummary {
    let directory = Path::new(&record.directory);
    LocalGallerySummary {
        id: record.download_task_id,
        provider: "eh".to_owned(),
        gid: record.gid,
        token: record.token.clone(),
        title: record.title.clone(),
        archive_bytes: record.archive_bytes,
        cover_available: record
            .cover_filename
            .as_deref()
            .and_then(safe_sidecar_name)
            .is_some_and(|filename| directory.join(filename).is_file()),
        comic_info_available: directory.join(COMIC_INFO_FILENAME).is_file(),
        created_at: record.created_at,
        updated_at: record.updated_at,
    }
}

fn gallery_detail(
    root: &Path,
    id: uuid::Uuid,
    offset: u32,
    limit: u32,
    max_page_bytes: usize,
) -> Result<LocalGalleryDetail, CoreError> {
    let record = find_record(root, id)?;
    let archive_path = Path::new(&record.directory).join(&record.archive_filename);
    let file = File::open(&archive_path)
        .map_err(|error| io_error("open local gallery ZIP", &archive_path, error))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|error| invalid_zip(error.to_string()))?;
    let members = image_members(&mut archive, max_page_bytes as u64)?;
    let total_pages = u32::try_from(members.len()).expect("image member limit fits in u32");
    if offset > total_pages {
        return Err(local_gallery_page_not_found());
    }
    let pages = members
        .into_iter()
        .enumerate()
        .skip(offset as usize)
        .take(limit as usize)
        .map(|(index, member)| {
            let id = u32::try_from(index).expect("image member limit fits in u32");
            LocalGalleryPage {
                id,
                number: id + 1,
                mime_type: mime_for_name(&member.filename).to_owned(),
                filename: member.filename,
                byte_length: member.byte_length,
            }
        })
        .collect();
    Ok(LocalGalleryDetail {
        gallery: summary(&record),
        total_pages,
        offset,
        pages,
    })
}

fn read_gallery_page(
    root: &Path,
    id: uuid::Uuid,
    page_id: u32,
    max_page_bytes: usize,
) -> Result<LocalGalleryResource, CoreError> {
    let record = find_record(root, id)?;
    let archive_path = Path::new(&record.directory).join(&record.archive_filename);
    let file = File::open(&archive_path)
        .map_err(|error| io_error("open local gallery ZIP", &archive_path, error))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|error| invalid_zip(error.to_string()))?;
    let members = image_members(&mut archive, max_page_bytes as u64)?;
    let member = members
        .get(page_id as usize)
        .ok_or_else(local_gallery_page_not_found)?;
    let mut source = archive
        .by_index(member.zip_index)
        .map_err(|error| invalid_zip(error.to_string()))?;
    let mut bytes = Vec::with_capacity(member.byte_length as usize);
    source
        .by_ref()
        .take(max_page_bytes as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| io_error("extract local gallery page", &archive_path, error))?;
    if bytes.len() > max_page_bytes {
        return Err(CoreError::new(
            ErrorCode::ResponseTooLarge,
            format!("gallery page exceeds the configured {max_page_bytes} byte limit"),
            false,
        ));
    }
    let (_, mime_type) = detect_format(&bytes)?;
    Ok(LocalGalleryResource {
        descriptor: LocalGalleryResourceDescriptor {
            gallery_id: id,
            kind: LocalGalleryResourceKind::Page,
            page_id: Some(page_id),
            mime_type: mime_type.to_owned(),
            byte_length: bytes.len(),
        },
        bytes: Bytes::from(bytes),
    })
}

fn read_gallery_cover(
    root: &Path,
    id: uuid::Uuid,
    max_resource_bytes: usize,
) -> Result<LocalGalleryResource, CoreError> {
    let record = find_record(root, id)?;
    let filename = record
        .cover_filename
        .as_deref()
        .ok_or_else(local_gallery_cover_not_found)?;
    let filename = safe_sidecar_name(filename).ok_or_else(|| {
        CoreError::new(
            ErrorCode::IntegrityMismatch,
            "local gallery cover filename is unsafe",
            false,
        )
    })?;
    let path = Path::new(&record.directory).join(filename);
    let metadata = std::fs::metadata(&path)
        .map_err(|error| io_error("read local gallery cover metadata", &path, error))?;
    if !metadata.is_file() {
        return Err(local_gallery_cover_not_found());
    }
    if metadata.len() > max_resource_bytes as u64 {
        return Err(CoreError::new(
            ErrorCode::ResponseTooLarge,
            format!("gallery cover exceeds the configured {max_resource_bytes} byte limit"),
            false,
        ));
    }
    let mut file =
        File::open(&path).map_err(|error| io_error("open local gallery cover", &path, error))?;
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    Read::by_ref(&mut file)
        .take(max_resource_bytes as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| io_error("read local gallery cover", &path, error))?;
    if bytes.len() > max_resource_bytes {
        return Err(CoreError::new(
            ErrorCode::ResponseTooLarge,
            format!("gallery cover exceeds the configured {max_resource_bytes} byte limit"),
            false,
        ));
    }
    let (_, mime_type) = detect_format(&bytes)?;
    Ok(LocalGalleryResource {
        descriptor: LocalGalleryResourceDescriptor {
            gallery_id: id,
            kind: LocalGalleryResourceKind::Cover,
            page_id: None,
            mime_type: mime_type.to_owned(),
            byte_length: bytes.len(),
        },
        bytes: Bytes::from(bytes),
    })
}

fn find_record(root: &Path, id: uuid::Uuid) -> Result<LocalGalleryRecord, CoreError> {
    scan(root)
        .into_iter()
        .find(|gallery| gallery.download_task_id == id)
        .ok_or_else(local_gallery_not_found)
}

fn gallery_delete_plan(root: &Path, id: uuid::Uuid) -> Result<GalleryDeletePlan, CoreError> {
    let record = find_record(root, id)?;
    let directory = PathBuf::from(record.directory);
    if directory.parent() != Some(root)
        || directory
            .file_name()
            .and_then(|value| value.to_str())
            .is_none_or(|value| value.is_empty() || value.starts_with('.'))
    {
        return Err(CoreError::new(
            ErrorCode::IntegrityMismatch,
            "local gallery directory is outside the managed root",
            false,
        ));
    }
    let (files, total_bytes) = direct_gallery_files(&directory)?;
    Ok(GalleryDeletePlan {
        directory,
        files,
        total_bytes,
    })
}

fn direct_gallery_files(directory: &Path) -> Result<(Vec<(String, u64)>, u64), CoreError> {
    let mut files = Vec::new();
    let mut total_bytes = 0_u64;
    for entry in std::fs::read_dir(directory)
        .map_err(|error| io_error("inspect local gallery files", directory, error))?
    {
        let entry =
            entry.map_err(|error| io_error("inspect local gallery files", directory, error))?;
        let file_type = entry
            .file_type()
            .map_err(|error| io_error("inspect local gallery file type", &entry.path(), error))?;
        let filename = entry.file_name().into_string().map_err(|_| {
            CoreError::new(
                ErrorCode::IntegrityMismatch,
                "local gallery contains a non-UTF-8 filename",
                false,
            )
        })?;
        if !file_type.is_file() || safe_sidecar_name(&filename).is_none() {
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "local gallery deletion only accepts direct ordinary files",
                false,
            ));
        }
        let bytes = entry
            .metadata()
            .map_err(|error| io_error("inspect local gallery file", &entry.path(), error))?
            .len();
        total_bytes = total_bytes.checked_add(bytes).ok_or_else(|| {
            CoreError::new(
                ErrorCode::ResponseTooLarge,
                "local gallery file sizes overflow the supported total",
                false,
            )
        })?;
        files.push((filename, bytes));
    }
    files.sort_unstable();
    Ok((files, total_bytes))
}

#[derive(Debug)]
struct RecoverableGalleryDelete {
    id: uuid::Uuid,
    tombstone: PathBuf,
    ticket: PathBuf,
    plan: GalleryDeletePlan,
}

fn pending_deletion_tickets(root: &Path) -> Result<Vec<RecoverableGalleryDelete>, CoreError> {
    let mut deletions = Vec::new();
    for entry in std::fs::read_dir(root)
        .map_err(|error| io_error("scan local gallery deletion recovery", root, error))?
    {
        let entry =
            entry.map_err(|error| io_error("scan local gallery deletion recovery", root, error))?;
        let filename = entry.file_name();
        let Some(filename) = filename.to_str() else {
            continue;
        };
        let Some(remainder) = filename
            .strip_prefix(".delete.")
            .and_then(|value| value.strip_suffix(".json"))
        else {
            continue;
        };
        let Some((id, token)) = remainder.split_once('.') else {
            continue;
        };
        let (Ok(id), Ok(_token)) = (uuid::Uuid::parse_str(id), uuid::Uuid::parse_str(token)) else {
            continue;
        };
        let ticket = entry.path();
        if !entry
            .file_type()
            .map_err(|error| io_error("inspect local gallery deletion recovery", &ticket, error))?
            .is_file()
        {
            continue;
        }
        let bytes = std::fs::read(&ticket)
            .map_err(|error| io_error("read local gallery deletion ticket", &ticket, error))?;
        let plan: GalleryDeletePlan = serde_json::from_slice(&bytes).map_err(|error| {
            CoreError::new(
                ErrorCode::Parse,
                format!("invalid local gallery deletion ticket: {error}"),
                false,
            )
        })?;
        if plan.directory.parent() != Some(root) {
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "local gallery deletion ticket is outside the managed root",
                false,
            ));
        }
        let tombstone = root.join(format!(".delete.{id}.{token}"));
        if plan.directory.exists() && !tombstone.exists() {
            std::fs::remove_file(&ticket).map_err(|error| {
                io_error(
                    "remove uncommitted local gallery deletion ticket",
                    &ticket,
                    error,
                )
            })?;
            continue;
        }
        if !tombstone.exists() {
            std::fs::remove_file(&ticket).map_err(|error| {
                io_error(
                    "remove completed local gallery deletion ticket",
                    &ticket,
                    error,
                )
            })?;
            continue;
        }
        if plan.directory.exists() {
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "local gallery deletion has both visible and hidden directories",
                false,
            ));
        }
        let (files, _) = direct_gallery_files(&tombstone)?;
        if files.iter().any(|file| !plan.files.contains(file)) {
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "local gallery deletion tombstone changed after confirmation",
                false,
            ));
        }
        deletions.push(RecoverableGalleryDelete {
            id,
            tombstone,
            ticket,
            plan,
        });
    }
    Ok(deletions)
}

fn delete_tombstone(tombstone: &Path, plan: &GalleryDeletePlan) -> Result<(), CoreError> {
    for (filename, expected_bytes) in &plan.files {
        let path = tombstone.join(filename);
        let metadata = match std::fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(error) => {
                return Err(io_error(
                    "verify confirmed local gallery file",
                    &path,
                    error,
                ));
            }
        };
        if !metadata.file_type().is_file() || metadata.len() != *expected_bytes {
            return Err(CoreError::new(
                ErrorCode::IntegrityMismatch,
                "local gallery changed during confirmed deletion",
                false,
            ));
        }
        std::fs::remove_file(&path)
            .map_err(|error| io_error("delete confirmed local gallery file", &path, error))?;
    }
    std::fs::remove_dir(tombstone)
        .map_err(|error| io_error("delete confirmed local gallery directory", tombstone, error))
}

fn delete_comic_info_by_id(root: &Path, id: uuid::Uuid) -> Result<(), CoreError> {
    let gallery = scan(root)
        .into_iter()
        .find(|gallery| gallery.download_task_id == id)
        .ok_or_else(local_gallery_not_found)?;
    let path = Path::new(&gallery.directory).join(COMIC_INFO_FILENAME);
    match std::fs::remove_file(&path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(io_error("delete ComicInfo.xml", &path, error)),
    }
}

fn generate_comic_info(
    directory: &Path,
    gallery: &LocalGalleryRecord,
) -> Result<ComicInfoSnapshot, CoreError> {
    let metadata_path = directory.join("gallery.json");
    let metadata_bytes = std::fs::read(&metadata_path)
        .map_err(|error| io_error("read gallery metadata", &metadata_path, error))?;
    let persisted: LocalGalleryRecord =
        serde_json::from_slice(&metadata_bytes).map_err(|error| {
            CoreError::new(
                ErrorCode::Parse,
                format!("invalid gallery metadata: {error}"),
                false,
            )
        })?;
    if persisted.download_task_id != gallery.download_task_id
        || persisted.archive_filename != gallery.archive_filename
    {
        return Err(CoreError::new(
            ErrorCode::IntegrityMismatch,
            "gallery metadata changed while deriving ComicInfo.xml",
            true,
        ));
    }
    let archive_path = directory.join(&persisted.archive_filename);
    let file = File::open(&archive_path)
        .map_err(|error| io_error("open gallery ZIP", &archive_path, error))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|error| {
        CoreError::new(
            ErrorCode::Parse,
            format!("invalid gallery ZIP: {error}"),
            false,
        )
    })?;
    let pages = image_members(&mut archive, u64::MAX)?;
    let xml = comic_info_xml(&persisted, pages.len());
    let path = directory.join(COMIC_INFO_FILENAME);
    atomic_bytes(&path, xml.as_bytes())?;
    Ok(ComicInfoSnapshot {
        gallery_id: persisted.download_task_id,
        filename: COMIC_INFO_FILENAME.to_owned(),
        page_count: pages.len(),
        bytes: xml.len() as u64,
    })
}

fn image_members<R: Read + std::io::Seek>(
    archive: &mut zip::ZipArchive<R>,
    max_page_bytes: u64,
) -> Result<Vec<ImageMember>, CoreError> {
    if archive.len() > MAX_IMAGE_MEMBERS {
        return Err(CoreError::new(
            ErrorCode::ResponseTooLarge,
            "gallery ZIP exceeds 100000 members",
            false,
        ));
    }
    let mut candidates = Vec::new();
    let mut names = HashSet::new();
    let mut total_bytes = 0_u64;
    for index in 0..archive.len() {
        let member = archive.by_index_raw(index).map_err(|error| {
            CoreError::new(
                ErrorCode::Parse,
                format!("invalid ZIP member: {error}"),
                false,
            )
        })?;
        if !member.is_dir() && safe_image_member(member.name()) {
            let normalized = member.name().replace('\\', "/");
            if !names.insert(normalized.clone()) {
                return Err(CoreError::new(
                    ErrorCode::IntegrityMismatch,
                    "gallery ZIP contains duplicate image member names",
                    false,
                ));
            }
            if member.size() > max_page_bytes {
                return Err(CoreError::new(
                    ErrorCode::ResponseTooLarge,
                    format!("gallery page exceeds the configured {max_page_bytes} byte limit"),
                    false,
                ));
            }
            total_bytes = total_bytes.checked_add(member.size()).ok_or_else(|| {
                CoreError::new(
                    ErrorCode::ResponseTooLarge,
                    "gallery ZIP image sizes overflow the supported total",
                    false,
                )
            })?;
            if total_bytes > MAX_TOTAL_IMAGE_BYTES {
                return Err(CoreError::new(
                    ErrorCode::ResponseTooLarge,
                    "gallery ZIP declares more than 64 GiB of image data",
                    false,
                ));
            }
            candidates.push(ImageMember {
                key: natural_key(&normalized),
                zip_index: index,
                filename: normalized,
                byte_length: member.size(),
            });
        }
    }
    candidates.sort_by(|left, right| left.key.cmp(&right.key));
    Ok(candidates)
}

fn comic_info_xml(gallery: &LocalGalleryRecord, page_count: usize) -> String {
    let mut xml = String::from("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<ComicInfo>\n");
    xml_element(&mut xml, "Title", &gallery.title);
    xml_element(
        &mut xml,
        "Web",
        &format!("https://e-hentai.org/g/{}/{}/", gallery.gid, gallery.token),
    );
    xml_element(&mut xml, "PageCount", &page_count.to_string());
    xml_element(
        &mut xml,
        "Notes",
        &format!("Generated by FletViewer; provider=eh; gid={}", gallery.gid),
    );
    if page_count > 0 {
        xml.push_str("  <Pages>\n");
        for index in 0..page_count {
            if index == 0 {
                xml.push_str("    <Page Image=\"0\" Type=\"FrontCover\" />\n");
            } else {
                xml.push_str(&format!("    <Page Image=\"{index}\" />\n"));
            }
        }
        xml.push_str("  </Pages>\n");
    }
    xml.push_str("</ComicInfo>\n");
    xml
}

fn xml_element(xml: &mut String, name: &str, value: &str) {
    xml.push_str("  <");
    xml.push_str(name);
    xml.push('>');
    for character in value.chars() {
        match character {
            '&' => xml.push_str("&amp;"),
            '<' => xml.push_str("&lt;"),
            '>' => xml.push_str("&gt;"),
            '\'' => xml.push_str("&apos;"),
            '"' => xml.push_str("&quot;"),
            character if valid_xml_character(character) => xml.push(character),
            _ => xml.push('\u{fffd}'),
        }
    }
    xml.push_str("</");
    xml.push_str(name);
    xml.push_str(">\n");
}

fn valid_xml_character(character: char) -> bool {
    matches!(character, '\u{9}' | '\u{a}' | '\u{d}') || character >= '\u{20}'
}

fn scan(root: &Path) -> Vec<LocalGalleryRecord> {
    let Ok(entries) = std::fs::read_dir(root) else {
        return Vec::new();
    };
    let mut galleries = entries
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.path().is_dir() && !entry.file_name().to_string_lossy().starts_with('.')
        })
        .filter_map(|entry| {
            let bytes = std::fs::read(entry.path().join("gallery.json")).ok()?;
            let mut gallery: LocalGalleryRecord = serde_json::from_slice(&bytes).ok()?;
            let archive_name = Path::new(&gallery.archive_filename);
            if archive_name.is_absolute()
                || archive_name
                    .parent()
                    .is_some_and(|parent| parent != Path::new(""))
                || archive_name.file_name().and_then(|value| value.to_str())
                    != Some(gallery.archive_filename.as_str())
            {
                return None;
            }
            let directory = entry.path();
            if !directory.join(&gallery.archive_filename).is_file() {
                return None;
            }
            gallery.directory = directory.to_string_lossy().into_owned();
            Some(gallery)
        })
        .collect::<Vec<_>>();
    galleries.sort_by_key(|gallery| std::cmp::Reverse(gallery.updated_at));
    galleries
}

fn find_by_task(root: &Path, id: uuid::Uuid) -> Option<PathBuf> {
    scan(root)
        .into_iter()
        .find(|gallery| gallery.download_task_id == id)
        .map(|gallery| PathBuf::from(gallery.directory))
}

fn safe_image_member(name: &str) -> bool {
    let normalized = name.replace('\\', "/");
    let path = Path::new(&normalized);
    if path.is_absolute()
        || normalized
            .split('/')
            .any(|part| part.is_empty() || part == ".." || part.starts_with('.'))
        || normalized.split('/').any(|part| part == "__MACOSX")
    {
        return false;
    }
    matches!(
        path.extension()
            .and_then(|value| value.to_str())
            .map(str::to_ascii_lowercase)
            .as_deref(),
        Some("jpg" | "jpeg" | "png" | "webp" | "gif")
    )
}

fn safe_sidecar_name(name: &str) -> Option<&str> {
    let path = Path::new(name);
    (!name.is_empty()
        && !path.is_absolute()
        && path.parent().is_some_and(|parent| parent == Path::new(""))
        && path.file_name().and_then(|value| value.to_str()) == Some(name))
    .then_some(name)
}

fn mime_for_name(name: &str) -> &'static str {
    match Path::new(name)
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("jpg" | "jpeg") => "image/jpeg",
        Some("png") => "image/png",
        Some("gif") => "image/gif",
        Some("webp") => "image/webp",
        _ => "application/octet-stream",
    }
}

fn natural_key(value: &str) -> NaturalKey {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut digits = None;
    for character in value.chars().chain(std::iter::once('\0')) {
        let is_digit = character.is_ascii_digit();
        if digits.is_some_and(|value| value != is_digit) || character == '\0' {
            if digits == Some(true) {
                let significant = current.trim_start_matches('0');
                parts.push(NaturalPart::Number {
                    significant: if significant.is_empty() {
                        "0".to_owned()
                    } else {
                        significant.to_owned()
                    },
                    width: current.len(),
                    original: current.clone(),
                });
            } else if !current.is_empty() {
                parts.push(NaturalPart::Text {
                    folded: current.to_ascii_lowercase(),
                    original: current.clone(),
                });
            }
            current.clear();
        }
        if character != '\0' {
            current.push(character);
            digits = Some(is_digit);
        }
    }
    NaturalKey {
        parts,
        original: value.to_owned(),
    }
}

#[derive(Debug, Eq, PartialEq)]
struct NaturalKey {
    parts: Vec<NaturalPart>,
    original: String,
}

impl Ord for NaturalKey {
    fn cmp(&self, other: &Self) -> Ordering {
        self.parts
            .cmp(&other.parts)
            .then_with(|| self.original.cmp(&other.original))
    }
}

impl PartialOrd for NaturalKey {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Debug, Eq, PartialEq)]
enum NaturalPart {
    Number {
        significant: String,
        width: usize,
        original: String,
    },
    Text {
        folded: String,
        original: String,
    },
}

impl Ord for NaturalPart {
    fn cmp(&self, other: &Self) -> Ordering {
        match (self, other) {
            (
                Self::Number {
                    significant: left,
                    width: left_width,
                    original: left_original,
                },
                Self::Number {
                    significant: right,
                    width: right_width,
                    original: right_original,
                },
            ) => left
                .len()
                .cmp(&right.len())
                .then_with(|| left.cmp(right))
                .then_with(|| left_width.cmp(right_width))
                .then_with(|| left_original.cmp(right_original)),
            (
                Self::Text {
                    folded: left,
                    original: left_original,
                },
                Self::Text {
                    folded: right,
                    original: right_original,
                },
            ) => left
                .cmp(right)
                .then_with(|| left_original.cmp(right_original)),
            (Self::Number { .. }, Self::Text { .. }) => Ordering::Less,
            (Self::Text { .. }, Self::Number { .. }) => Ordering::Greater,
        }
    }
}

impl PartialOrd for NaturalPart {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

fn gallery_directory_name(gid: u64, token: &str, title: &str) -> String {
    let prefix = format!("[{gid}][{token}] ");
    let mut title = sanitize_component(title);
    title.truncate(180_usize.saturating_sub(prefix.len()).max(1));
    title = title.trim_end_matches([' ', '.']).to_owned();
    if title.is_empty() {
        title = "Untitled".to_owned();
    }
    format!("{prefix}{title}")
}

fn sanitize_component(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_control()
                || matches!(
                    character,
                    '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*'
                )
            {
                '_'
            } else {
                character
            }
        })
        .collect::<String>()
        .trim_matches([' ', '.'])
        .to_owned()
}

fn unique_path(path: &Path) -> Result<PathBuf, CoreError> {
    if !path.exists() {
        return Ok(path.to_owned());
    }
    for index in 1..1000 {
        let candidate = path.with_file_name(format!(
            "{} ({index})",
            path.file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("gallery")
        ));
        if !candidate.exists() {
            return Ok(candidate);
        }
    }
    Err(CoreError::new(
        ErrorCode::Io,
        "no unique local gallery path is available",
        false,
    ))
}

fn move_file(source: &Path, target: &Path) -> Result<(), CoreError> {
    match std::fs::rename(source, target) {
        Ok(()) => Ok(()),
        Err(_) => {
            std::fs::copy(source, target)
                .map_err(|error| io_error("copy Archive into local gallery", target, error))?;
            std::fs::remove_file(source)
                .map_err(|error| io_error("remove consumed Archive source", source, error))
        }
    }
}

fn atomic_json(path: &Path, value: &impl Serialize) -> Result<(), CoreError> {
    let temporary = path.with_extension("json.tmp");
    let bytes = serde_json::to_vec_pretty(value).map_err(|error| {
        CoreError::new(
            ErrorCode::Internal,
            format!("failed to serialize gallery metadata: {error}"),
            false,
        )
    })?;
    std::fs::write(&temporary, bytes)
        .map_err(|error| io_error("write gallery metadata", &temporary, error))?;
    std::fs::rename(&temporary, path)
        .map_err(|error| io_error("commit gallery metadata", path, error))
}

fn atomic_bytes(path: &Path, bytes: &[u8]) -> Result<(), CoreError> {
    let temporary = path.with_extension("xml.tmp");
    std::fs::write(&temporary, bytes)
        .map_err(|error| io_error("write derived ComicInfo.xml", &temporary, error))?;
    if path.exists() {
        std::fs::remove_file(path)
            .map_err(|error| io_error("replace derived ComicInfo.xml", path, error))?;
    }
    std::fs::rename(&temporary, path)
        .map_err(|error| io_error("commit derived ComicInfo.xml", path, error))
}

fn local_gallery_not_found() -> CoreError {
    CoreError::new(
        ErrorCode::ResourceNotFound,
        "local gallery was not found",
        false,
    )
}

fn local_gallery_page_not_found() -> CoreError {
    CoreError::new(
        ErrorCode::ResourceNotFound,
        "local gallery page was not found",
        false,
    )
}

fn local_gallery_cover_not_found() -> CoreError {
    CoreError::new(
        ErrorCode::ResourceNotFound,
        "local gallery cover was not found",
        false,
    )
}

fn invalid_delete_confirmation() -> CoreError {
    CoreError::new(
        ErrorCode::AccessDenied,
        "local gallery deletion confirmation is invalid or expired",
        false,
    )
}

fn invalid_zip(message: impl Into<String>) -> CoreError {
    CoreError::new(
        ErrorCode::Parse,
        format!("invalid gallery ZIP: {}", message.into()),
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

#[cfg(test)]
mod tests {
    use super::{
        atomic_json, consume_blocking, delete_comic_info_by_id, delete_tombstone,
        gallery_delete_plan, gallery_detail, generate_comic_info_by_id, image_members, natural_key,
        pending_deletion_tickets, read_gallery_cover, read_gallery_page, scan,
    };
    use crate::{
        ArchiveTaskSnapshot, ArchiveTaskState, EhArchiveVariant, EhGalleryRef, ErrorCode,
        ProfileKey, archive::ArchiveConsumption,
    };
    use std::{fs::File, io::Write};
    use tempfile::TempDir;
    use time::OffsetDateTime;
    use zip::{ZipWriter, write::SimpleFileOptions};

    fn task(id: uuid::Uuid) -> ArchiveTaskSnapshot {
        let now = OffsetDateTime::now_utc();
        ArchiveTaskSnapshot {
            id,
            state: ArchiveTaskState::Completed,
            revision: 4,
            profile: ProfileKey::new("eh", "default"),
            gallery: EhGalleryRef {
                gid: 123456,
                token: "abcdef1234".to_owned(),
            },
            variant: EhArchiveVariant::Resample,
            title: "Fixture: Gallery?".to_owned(),
            bytes_done: 0,
            bytes_total: None,
            resume_supported: true,
            final_path: None,
            error: None,
            consume_error: None,
            created_at: now,
            updated_at: now,
            url_acquired_at: Some(now),
            url_valid_seconds: 86_400,
            max_ip_count: 2,
        }
    }

    #[test]
    fn consumes_zip_with_natural_cover_order_and_is_idempotent() {
        let temp = TempDir::new().unwrap();
        let root = temp.path().join("EHArchieve");
        std::fs::create_dir(&root).unwrap();
        let archive_path = temp.path().join("source.zip");
        let file = File::create(&archive_path).unwrap();
        let mut zip = ZipWriter::new(file);
        zip.start_file("10.jpg", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"ten").unwrap();
        zip.start_file("2.jpg", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"two").unwrap();
        zip.finish().unwrap();
        let id = uuid::Uuid::now_v7();
        let gallery = consume_blocking(
            &root,
            ArchiveConsumption {
                task: task(id),
                archive_path: archive_path.clone(),
            },
        )
        .unwrap();
        assert_eq!(std::fs::read(gallery.join("thumb.jpg")).unwrap(), b"two");
        assert!(gallery.join("ComicInfo.xml").is_file());
        assert!(gallery.join("source.zip").is_file());
        assert!(!archive_path.exists());
        assert_eq!(scan(&root).len(), 1);

        let duplicate = temp.path().join("duplicate.zip");
        std::fs::copy(gallery.join("source.zip"), &duplicate).unwrap();
        assert_eq!(
            consume_blocking(
                &root,
                ArchiveConsumption {
                    task: task(id),
                    archive_path: duplicate.clone()
                }
            )
            .unwrap(),
            gallery
        );
        assert!(!duplicate.exists());
        assert_eq!(scan(&root).len(), 1);
    }

    #[test]
    fn natural_order_handles_padding_text_and_unbounded_numbers() {
        let mut names = vec![
            "page10.webp",
            "0002.webp",
            "page2.webp",
            "01.webp",
            "1.webp",
            "184467440737095516160.webp",
            "99999999999999999999.webp",
        ];
        names.sort_by_key(|name| natural_key(name));
        assert_eq!(
            names,
            [
                "1.webp",
                "01.webp",
                "0002.webp",
                "99999999999999999999.webp",
                "184467440737095516160.webp",
                "page2.webp",
                "page10.webp",
            ]
        );
    }

    #[test]
    fn delete_plan_is_stable_and_rejects_nested_content() {
        let temp = TempDir::new().unwrap();
        let root = temp.path().join("EHArchieve");
        std::fs::create_dir(&root).unwrap();
        let archive_path = temp.path().join("delete.zip");
        let file = File::create(&archive_path).unwrap();
        let mut zip = ZipWriter::new(file);
        zip.start_file("1.jpg", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"\xff\xd8\xffpage").unwrap();
        zip.finish().unwrap();
        let id = uuid::Uuid::now_v7();
        let directory = consume_blocking(
            &root,
            ArchiveConsumption {
                task: task(id),
                archive_path,
            },
        )
        .unwrap();
        let first = gallery_delete_plan(&root, id).unwrap();
        let second = gallery_delete_plan(&root, id).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.files.len(), 4);
        assert!(first.total_bytes > 0);

        std::fs::create_dir(directory.join("nested")).unwrap();
        assert_eq!(
            gallery_delete_plan(&root, id).unwrap_err().code(),
            ErrorCode::IntegrityMismatch
        );
    }

    #[test]
    fn confirmed_delete_ticket_recovers_partial_file_removal_safely() {
        let temp = TempDir::new().unwrap();
        let root = temp.path().join("EHArchieve");
        std::fs::create_dir(&root).unwrap();
        let archive_path = temp.path().join("recover.zip");
        let file = File::create(&archive_path).unwrap();
        let mut zip = ZipWriter::new(file);
        zip.start_file("1.jpg", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"\xff\xd8\xffpage").unwrap();
        zip.finish().unwrap();
        let id = uuid::Uuid::now_v7();
        consume_blocking(
            &root,
            ArchiveConsumption {
                task: task(id),
                archive_path,
            },
        )
        .unwrap();
        let plan = gallery_delete_plan(&root, id).unwrap();
        let token = uuid::Uuid::now_v7();
        let tombstone = root.join(format!(".delete.{id}.{token}"));
        let ticket = root.join(format!(".delete.{id}.{token}.json"));
        atomic_json(&ticket, &plan).unwrap();
        std::fs::rename(&plan.directory, &tombstone).unwrap();
        std::fs::remove_file(tombstone.join(&plan.files[0].0)).unwrap();

        let pending = pending_deletion_tickets(&root).unwrap();
        assert_eq!(pending.len(), 1);
        delete_tombstone(&pending[0].tombstone, &pending[0].plan).unwrap();
        assert!(!tombstone.exists());

        let changed = root.join(format!(".delete.{id}.{}", uuid::Uuid::now_v7()));
        std::fs::create_dir(&changed).unwrap();
        std::fs::write(changed.join("unexpected"), b"data").unwrap();
        let changed_ticket = changed.with_file_name(format!(
            "{}.json",
            changed.file_name().unwrap().to_string_lossy()
        ));
        atomic_json(&changed_ticket, &plan).unwrap();
        assert_eq!(
            pending_deletion_tickets(&root).unwrap_err().code(),
            ErrorCode::IntegrityMismatch
        );
    }

    #[test]
    fn comic_info_is_deterministic_deletable_and_does_not_change_zip() {
        let temp = TempDir::new().unwrap();
        let root = temp.path().join("EHArchieve");
        std::fs::create_dir(&root).unwrap();
        let archive_path = temp.path().join("original fixture.zip");
        let file = File::create(&archive_path).unwrap();
        let mut zip = ZipWriter::new(file);
        zip.start_file("000010.webp", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"ten").unwrap();
        zip.start_file("000002.webp", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"two").unwrap();
        zip.finish().unwrap();
        let original_zip = std::fs::read(&archive_path).unwrap();
        let id = uuid::Uuid::now_v7();
        let mut snapshot = task(id);
        snapshot.title = "Fixture & <Gallery>".to_owned();
        let gallery = consume_blocking(
            &root,
            ArchiveConsumption {
                task: snapshot,
                archive_path,
            },
        )
        .unwrap();
        assert_eq!(
            std::fs::read(gallery.join("original fixture.zip")).unwrap(),
            original_zip
        );
        let first = std::fs::read(gallery.join("ComicInfo.xml")).unwrap();
        let first_snapshot = generate_comic_info_by_id(&root, id).unwrap();
        assert_eq!(first_snapshot.page_count, 2);
        assert_eq!(std::fs::read(gallery.join("ComicInfo.xml")).unwrap(), first);
        delete_comic_info_by_id(&root, id).unwrap();
        assert!(!gallery.join("ComicInfo.xml").exists());
        generate_comic_info_by_id(&root, id).unwrap();
        assert_eq!(std::fs::read(gallery.join("ComicInfo.xml")).unwrap(), first);
        let xml = String::from_utf8(first).unwrap();
        assert!(xml.contains("<Title>Fixture &amp; &lt;Gallery&gt;</Title>"));
        assert!(xml.contains("<PageCount>2</PageCount>"));
        assert!(xml.contains("<Page Image=\"0\" Type=\"FrontCover\" />"));
        assert_eq!(
            std::fs::read(gallery.join("original fixture.zip")).unwrap(),
            original_zip
        );
    }

    #[test]
    fn local_pages_are_safe_sorted_bounded_and_detected_from_bytes() {
        let temp = TempDir::new().unwrap();
        let root = temp.path().join("EHArchieve");
        std::fs::create_dir(&root).unwrap();
        let archive_path = temp.path().join("pages.zip");
        let file = File::create(&archive_path).unwrap();
        let mut zip = ZipWriter::new(file);
        zip.start_file("10.jpg", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"\xff\xd8\xfften").unwrap();
        zip.start_file("folder/2.png", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"\x89PNG\r\n\x1a\ntwo").unwrap();
        zip.start_file("../escape.jpg", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"\xff\xd8\xffescape").unwrap();
        zip.start_file(".hidden/1.jpg", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"\xff\xd8\xffhidden").unwrap();
        zip.finish().unwrap();
        let id = uuid::Uuid::now_v7();
        consume_blocking(
            &root,
            ArchiveConsumption {
                task: task(id),
                archive_path,
            },
        )
        .unwrap();

        let detail = gallery_detail(&root, id, 0, 100, 1024).unwrap();
        assert_eq!(detail.total_pages, 2);
        assert_eq!(detail.pages[0].id, 0);
        assert_eq!(detail.pages[0].filename, "10.jpg");
        assert_eq!(detail.pages[1].filename, "folder/2.png");
        assert!(
            !serde_json::to_string(&detail)
                .unwrap()
                .contains("directory")
        );
        let first = read_gallery_page(&root, id, 0, 1024).unwrap();
        assert_eq!(first.descriptor().mime_type, "image/jpeg");
        assert_eq!(
            first.descriptor().kind,
            super::LocalGalleryResourceKind::Page
        );
        assert_eq!(first.descriptor().page_id, Some(0));
        assert_eq!(first.bytes().as_ref(), b"\xff\xd8\xfften");
        assert!(read_gallery_page(&root, id, 2, 1024).is_err());
    }

    #[test]
    fn local_cover_is_bounded_and_detected_from_actual_bytes() {
        let temp = TempDir::new().unwrap();
        let root = temp.path().join("EHArchieve");
        std::fs::create_dir(&root).unwrap();
        let archive_path = temp.path().join("cover.zip");
        let file = File::create(&archive_path).unwrap();
        let mut zip = ZipWriter::new(file);
        zip.start_file("1.jpg", SimpleFileOptions::default())
            .unwrap();
        zip.write_all(b"\xff\xd8\xffcover").unwrap();
        zip.finish().unwrap();
        let id = uuid::Uuid::now_v7();
        let directory = consume_blocking(
            &root,
            ArchiveConsumption {
                task: task(id),
                archive_path,
            },
        )
        .unwrap();
        let cover = read_gallery_cover(&root, id, 1024).unwrap();
        assert_eq!(
            cover.descriptor().kind,
            super::LocalGalleryResourceKind::Cover
        );
        assert_eq!(cover.descriptor().page_id, None);
        assert_eq!(cover.descriptor().mime_type, "image/jpeg");
        assert_eq!(cover.bytes().as_ref(), b"\xff\xd8\xffcover");

        std::fs::write(directory.join("thumb.jpg"), b"not an image").unwrap();
        assert_eq!(
            read_gallery_cover(&root, id, 1024).unwrap_err().code(),
            ErrorCode::UnexpectedResponse
        );
        std::fs::write(directory.join("thumb.jpg"), [0_u8; 9]).unwrap();
        assert_eq!(
            read_gallery_cover(&root, id, 8).unwrap_err().code(),
            ErrorCode::ResponseTooLarge
        );

        let metadata_path = directory.join("gallery.json");
        let mut metadata: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&metadata_path).unwrap()).unwrap();
        metadata["cover_filename"] = serde_json::Value::String("../outside.jpg".to_owned());
        std::fs::write(&metadata_path, serde_json::to_vec(&metadata).unwrap()).unwrap();
        assert_eq!(
            read_gallery_cover(&root, id, 1024).unwrap_err().code(),
            ErrorCode::IntegrityMismatch
        );
    }

    #[test]
    fn zip_index_rejects_duplicate_names_and_oversized_pages() {
        let temp = TempDir::new().unwrap();
        let duplicate = temp.path().join("duplicate.zip");
        let file = File::create(&duplicate).unwrap();
        let mut writer = ZipWriter::new(file);
        writer
            .start_file("folder/1.jpg", SimpleFileOptions::default())
            .unwrap();
        writer.write_all(b"one").unwrap();
        writer
            .start_file("folder\\1.jpg", SimpleFileOptions::default())
            .unwrap();
        writer.write_all(b"two").unwrap();
        writer.finish().unwrap();
        let file = File::open(&duplicate).unwrap();
        let mut archive = zip::ZipArchive::new(file).unwrap();
        let error = image_members(&mut archive, 1024).unwrap_err();
        assert_eq!(error.code(), ErrorCode::IntegrityMismatch);

        let oversized = temp.path().join("oversized.zip");
        let file = File::create(&oversized).unwrap();
        let mut writer = ZipWriter::new(file);
        writer
            .start_file("1.jpg", SimpleFileOptions::default())
            .unwrap();
        writer.write_all(&[0_u8; 9]).unwrap();
        writer.finish().unwrap();
        let file = File::open(&oversized).unwrap();
        let mut archive = zip::ZipArchive::new(file).unwrap();
        let error = image_members(&mut archive, 8).unwrap_err();
        assert_eq!(error.code(), ErrorCode::ResponseTooLarge);
    }
}
