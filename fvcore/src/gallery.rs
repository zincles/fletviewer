//! Local gallery library consuming completed persistent Archive tasks.

use crate::{
    ArchiveTaskState, CoreError, ErrorCode,
    archive::{ArchiveConsumption, ArchiveService},
};
use serde::{Deserialize, Serialize};
use std::{
    fs::File,
    io::Write,
    path::{Path, PathBuf},
    sync::Arc,
};
use time::OffsetDateTime;

const MAX_COVER_BYTES: u64 = 64 * 1024 * 1024;

/// Immutable local gallery snapshot backed by one original EH Archive ZIP.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct LocalGallerySnapshot {
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

pub(crate) struct GalleryService {
    root: PathBuf,
    archives: Arc<ArchiveService>,
}

impl GalleryService {
    pub(crate) async fn open(
        downloads: PathBuf,
        archives: Arc<ArchiveService>,
    ) -> Result<Arc<Self>, CoreError> {
        let root = downloads.join("EHArchieve");
        tokio::fs::create_dir_all(&root)
            .await
            .map_err(|error| io_error("create local gallery directory", &root, error))?;
        let service = Arc::new(Self { root, archives });
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

    pub(crate) async fn list(&self) -> Vec<LocalGallerySnapshot> {
        let root = self.root.clone();
        tokio::task::spawn_blocking(move || scan(&root))
            .await
            .unwrap_or_default()
    }

    async fn consume(
        &self,
        consumption: ArchiveConsumption,
    ) -> Result<(uuid::Uuid, PathBuf), (uuid::Uuid, CoreError)> {
        let id = consumption.task.id;
        let root = self.root.clone();
        tokio::task::spawn_blocking(move || consume_blocking(&root, consumption))
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
        .map(sanitize_component)
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "archive.zip".to_owned());
    let staging_archive = staging.join(&archive_filename);
    if let Err(error) = move_file(&consumption.archive_path, &staging_archive) {
        let _ = std::fs::remove_dir_all(&staging);
        return Err(error);
    }
    let result = (|| {
        let cover_filename = inspect_and_extract_cover(&staging_archive, &staging)?;
        let now = OffsetDateTime::now_utc();
        let metadata = LocalGallerySnapshot {
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
    let mut candidates = Vec::new();
    for index in 0..archive.len() {
        let member = archive.by_index_raw(index).map_err(|error| {
            CoreError::new(
                ErrorCode::Parse,
                format!("invalid ZIP member: {error}"),
                false,
            )
        })?;
        if !member.is_dir() && safe_image_member(member.name()) {
            candidates.push((natural_key(member.name()), index));
        }
    }
    candidates.sort_by(|left, right| left.0.cmp(&right.0));
    let Some((_, index)) = candidates.first() else {
        return Ok(None);
    };
    let mut member = archive.by_index(*index).map_err(|error| {
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

fn scan(root: &Path) -> Vec<LocalGallerySnapshot> {
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
            let gallery: LocalGallerySnapshot = serde_json::from_slice(&bytes).ok()?;
            entry
                .path()
                .join(&gallery.archive_filename)
                .is_file()
                .then_some(gallery)
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

fn natural_key(value: &str) -> Vec<NaturalPart> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut digits = None;
    for character in value.chars().chain(std::iter::once('\0')) {
        let is_digit = character.is_ascii_digit();
        if digits.is_some_and(|value| value != is_digit) || character == '\0' {
            if digits == Some(true) {
                parts.push(NaturalPart::Number(current.parse().unwrap_or(u64::MAX)));
            } else if !current.is_empty() {
                parts.push(NaturalPart::Text(current.to_ascii_lowercase()));
            }
            current.clear();
        }
        if character != '\0' {
            current.push(character);
            digits = Some(is_digit);
        }
    }
    parts
}

#[derive(Eq, Ord, PartialEq, PartialOrd)]
enum NaturalPart {
    Number(u64),
    Text(String),
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

fn io_error(action: &str, path: &Path, error: std::io::Error) -> CoreError {
    CoreError::new(
        ErrorCode::Io,
        format!("failed to {action} {}: {error}", path.display()),
        false,
    )
}

#[cfg(test)]
mod tests {
    use super::{consume_blocking, scan};
    use crate::{
        ArchiveTaskSnapshot, ArchiveTaskState, EhArchiveVariant, EhGalleryRef, ProfileKey,
        archive::ArchiveConsumption,
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
}
