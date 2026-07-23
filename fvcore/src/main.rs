//! Configuration-driven executable entry point for fvcore.

#![forbid(unsafe_code)]

use clap::{ArgAction, CommandFactory, Parser, Subcommand};
use fs2::FileExt;
use fvcore::{CoreBuilder, CoreConfig, CoreError};
use std::{
    fs::File,
    path::{Path, PathBuf},
    process::ExitCode,
};
use tracing_subscriber::EnvFilter;

const CONFIG_FILENAME: &str = "config.json";
const CONFIG_BACKUP_FILENAME: &str = ".config.json.override-backup";
const CONFIG_LOCK_FILENAME: &str = ".config.json.lock";

#[derive(Debug, Parser)]
#[command(
    version,
    bin_name = "fvcore",
    about = "FletViewer 的纯 Rust 业务核心",
    long_about = None,
    disable_help_flag = true,
    disable_version_flag = true,
    disable_help_subcommand = true,
    subcommand_value_name = "命令",
    help_template = "{name} {version}\n{about}\n\n用法: {usage}\n\n命令:\n{subcommands}\n\n选项:\n{options}"
)]
struct Cli {
    /// 显示帮助。
    #[arg(short = 'h', long = "help", global = true, action = ArgAction::Help)]
    help: Option<bool>,

    /// 显示版本。
    #[arg(short = 'V', long = "version", action = ArgAction::Version)]
    version: Option<bool>,

    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// 显示根命令帮助。
    Help,
    /// 运行核心，直到收到中断信号。
    #[command(help_template = "{about}\n\n用法: {usage}\n\n选项:\n{options}")]
    Run,
    /// 运行核心，同时启用 HTTP 控制面和 WebUI。
    #[command(help_template = "{about}\n\n用法: {usage}\n\n选项:\n{options}")]
    Web,
    /// 解析并完整验证一个 JSON 配置文件，然后退出。
    #[command(
        help_template = "{about}\n\n用法: {usage}\n\n参数:\n{positionals}\n\n选项:\n{options}"
    )]
    CheckConfig {
        /// 要验证的 JSON 配置文件；省略时检查 executable 同级的 config.json。
        #[arg(value_name = "文件")]
        file: Option<PathBuf>,
    },
    /// 在现有目录中创建完整的默认 config.json。
    #[command(
        help_template = "{about}\n\n用法: {usage}\n\n参数:\n{positionals}\n\n选项:\n{options}"
    )]
    CreateConfig {
        /// 用于保存 config.json 的现有目录；省略时使用 executable 所在目录。
        #[arg(value_name = "目录")]
        directory: Option<PathBuf>,
        /// 将现有配置安全重置为完整默认配置；不合并或保留旧字段。
        #[arg(long = "override")]
        override_existing: bool,
    },
}

#[tokio::main]
async fn main() -> ExitCode {
    init_tracing();
    let cli = Cli::parse();
    match run(cli).await {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            tracing::error!(
                code = error.code().as_str(),
                retryable = error.retryable(),
                message = error.message(),
                "fvcore failed"
            );
            ExitCode::FAILURE
        }
    }
}

async fn run(cli: Cli) -> Result<(), CoreError> {
    match &cli.command {
        Some(Command::Help) => {
            Cli::command().print_help().map_err(|error| {
                CoreError::new(
                    fvcore::ErrorCode::Io,
                    format!("无法输出帮助: {error}"),
                    false,
                )
            })?;
            println!();
            return Ok(());
        }
        Some(Command::CheckConfig { file }) => {
            let path = check_config_path(file.as_deref())?;
            check_config(&path)?;
            println!("配置文件有效: {}", path.display());
            return Ok(());
        }
        Some(Command::CreateConfig {
            directory,
            override_existing,
        }) => {
            let directory = create_config_directory(directory.as_deref())?;
            let result = create_config(&directory, *override_existing)?;
            if result.replaced {
                println!("已用完整默认配置覆盖: {}", result.path.display());
            } else {
                println!("已创建配置文件: {}", result.path.display());
            }
            return Ok(());
        }
        Some(Command::Run) | Some(Command::Web) | None => {}
    }
    let web = matches!(cli.command, Some(Command::Web));
    let config_path = executable_directory()?.join(CONFIG_FILENAME);
    let config = load_config(web)?;
    let runtime = CoreBuilder::new(config)
        .config_file(config_path)
        .build()
        .await?;
    let snapshot = runtime.handle().snapshot().await?;
    tracing::info!(
        runtime_id = %snapshot.runtime_id,
        instance = snapshot.instance_name,
        "fvcore is ready"
    );
    if let Some(listen) = runtime.control_listen() {
        tracing::info!(
            bind = %listen,
            local_url = %local_control_url(listen),
            lan_port = listen.port(),
            "HTTP control plane is listening; LAN clients should use this computer's LAN IP"
        );
    }

    tokio::signal::ctrl_c().await.map_err(|error| {
        CoreError::new(
            fvcore::ErrorCode::Io,
            format!("failed to wait for shutdown signal: {error}"),
            false,
        )
    })?;
    tracing::info!("shutdown requested");
    runtime.shutdown().await
}

fn local_control_url(listen: std::net::SocketAddr) -> String {
    let local = match listen {
        std::net::SocketAddr::V4(address) if address.ip().is_unspecified() => {
            std::net::SocketAddr::from(([127, 0, 0, 1], address.port()))
        }
        std::net::SocketAddr::V6(address) if address.ip().is_unspecified() => {
            std::net::SocketAddr::from(([0, 0, 0, 0, 0, 0, 0, 1], address.port()))
        }
        address => address,
    };
    format!("http://{local}/")
}

fn check_config(path: &Path) -> Result<(), CoreError> {
    let path = absolute_path(path)?;
    if path.is_dir() {
        return Err(CoreError::new(
            fvcore::ErrorCode::InvalidInput,
            format!(
                "配置路径是目录，需要指定 JSON 文件；该目录为: {}；若使用默认文件名，应检查: {}",
                path.display(),
                path.join("config.json").display()
            ),
            false,
        ));
    }
    let directory = path.parent().unwrap_or_else(|| Path::new("."));
    let _lock = if directory.is_dir()
        && path.file_name().and_then(|value| value.to_str()) == Some(CONFIG_FILENAME)
    {
        let lock = lock_config(directory)?;
        recover_config_override(directory)?;
        Some(lock)
    } else {
        None
    };
    if !path.is_file() {
        return Err(CoreError::new(
            fvcore::ErrorCode::Io,
            format!(
                "未找到配置文件: {}；配置文件应位于目录: {}；请执行 `fvcore create-config {}` 创建默认配置",
                path.display(),
                directory.display(),
                directory.display()
            ),
            false,
        ));
    }
    validate_config_file(&path)
}

fn check_config_path(path: Option<&Path>) -> Result<PathBuf, CoreError> {
    match path {
        Some(path) => absolute_path(path),
        None => executable_directory().map(|directory| directory.join(CONFIG_FILENAME)),
    }
}

fn absolute_path(path: &Path) -> Result<PathBuf, CoreError> {
    if path.is_absolute() {
        return Ok(path.components().collect());
    }
    std::env::current_dir()
        .map(|directory| directory.join(path).components().collect())
        .map_err(|error| {
            CoreError::new(
                fvcore::ErrorCode::Io,
                format!("无法解析配置文件路径 {}: {error}", path.display()),
                false,
            )
        })
}

#[derive(Debug)]
struct ConfigCreateResult {
    path: PathBuf,
    replaced: bool,
}

#[derive(Debug)]
struct ConfigLock {
    file: File,
}

impl Drop for ConfigLock {
    fn drop(&mut self) {
        if let Err(error) = FileExt::unlock(&self.file) {
            tracing::warn!(%error, "failed to release configuration lock");
        }
    }
}

fn create_config(
    directory: &Path,
    override_existing: bool,
) -> Result<ConfigCreateResult, CoreError> {
    if !directory.is_dir() {
        return Err(CoreError::new(
            fvcore::ErrorCode::InvalidInput,
            format!(
                "configuration destination must be an existing directory: {}",
                directory.display()
            ),
            false,
        ));
    }
    let _lock = lock_config(directory)?;
    recover_config_override(directory)?;
    let path = directory.join(CONFIG_FILENAME);
    let replaced = match std::fs::symlink_metadata(&path) {
        Ok(metadata) if metadata.file_type().is_file() => true,
        Ok(_) => {
            return Err(CoreError::new(
                fvcore::ErrorCode::InvalidInput,
                format!("现有配置不是普通文件，拒绝覆盖: {}", path.display()),
                false,
            ));
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
        Err(error) => return Err(config_io_error("检查现有配置", &path, error)),
    };
    if replaced && !override_existing {
        return Err(CoreError::new(
            fvcore::ErrorCode::InvalidInput,
            format!(
                "配置文件已存在，拒绝覆盖: {}；可执行 `fvcore check-config {}` 验证现有配置；若要丢弃现有配置并重置为完整默认配置，请执行 `fvcore create-config {} --override`",
                path.display(),
                path.display(),
                directory.display()
            ),
            false,
        ));
    }
    let mut bytes = serde_json::to_vec_pretty(&CoreConfig::default()).map_err(|error| {
        CoreError::new(
            fvcore::ErrorCode::Internal,
            format!("failed to serialize default configuration: {error}"),
            false,
        )
    })?;
    bytes.push(b'\n');
    let temporary = directory.join(format!(".config.{}.tmp", uuid::Uuid::now_v7()));
    let result = (|| {
        use std::io::Write;
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|error| {
                CoreError::new(
                    fvcore::ErrorCode::Io,
                    format!(
                        "failed to create temporary configuration {}: {error}",
                        temporary.display()
                    ),
                    false,
                )
            })?;
        file.write_all(&bytes).map_err(|error| {
            CoreError::new(
                fvcore::ErrorCode::Io,
                format!(
                    "failed to write temporary configuration {}: {error}",
                    temporary.display()
                ),
                false,
            )
        })?;
        file.sync_all().map_err(|error| {
            CoreError::new(
                fvcore::ErrorCode::Io,
                format!(
                    "failed to flush temporary configuration {}: {error}",
                    temporary.display()
                ),
                false,
            )
        })?;
        validate_config_file(&temporary)?;
        if replaced {
            replace_config(&temporary, &path, directory)
        } else {
            std::fs::hard_link(&temporary, &path)
                .map_err(|error| config_io_error("发布配置", &path, error))?;
            std::fs::remove_file(&temporary).map_err(|error| {
                CoreError::new(
                    fvcore::ErrorCode::Io,
                    format!(
                        "configuration was created but temporary file {} could not be removed: {error}",
                        temporary.display()
                    ),
                    false,
                )
            })
        }
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result?;
    validate_config_file(&path)?;
    Ok(ConfigCreateResult { path, replaced })
}

fn replace_config(temporary: &Path, path: &Path, directory: &Path) -> Result<(), CoreError> {
    let backup = directory.join(CONFIG_BACKUP_FILENAME);
    std::fs::rename(path, &backup).map_err(|error| config_io_error("备份现有配置", path, error))?;
    if let Err(error) = std::fs::rename(temporary, path) {
        let rollback = std::fs::rename(&backup, path);
        return Err(if let Err(rollback) = rollback {
            CoreError::new(
                fvcore::ErrorCode::Io,
                format!(
                    "发布覆盖配置失败: {error}；恢复旧配置也失败: {rollback}；恢复副本位于 {}",
                    backup.display()
                ),
                false,
            )
        } else {
            config_io_error("发布覆盖配置，旧配置已恢复", path, error)
        });
    }
    std::fs::remove_file(&backup).map_err(|error| {
        CoreError::new(
            fvcore::ErrorCode::Io,
            format!(
                "新配置已发布，但无法删除恢复副本 {}: {error}；下次配置操作会自动恢复事务",
                backup.display()
            ),
            false,
        )
    })
}

fn lock_config(directory: &Path) -> Result<ConfigLock, CoreError> {
    let path = directory.join(CONFIG_LOCK_FILENAME);
    let file = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&path)
        .map_err(|error| config_io_error("打开配置锁", &path, error))?;
    file.try_lock_exclusive().map_err(|error| {
        CoreError::new(
            fvcore::ErrorCode::AlreadyRunning,
            format!(
                "另一个 fvcore 进程正在管理该目录的配置 {}: {error}",
                directory.display()
            ),
            true,
        )
    })?;
    Ok(ConfigLock { file })
}

fn recover_config_override(directory: &Path) -> Result<(), CoreError> {
    let path = directory.join(CONFIG_FILENAME);
    let backup = directory.join(CONFIG_BACKUP_FILENAME);
    let backup_metadata = match std::fs::symlink_metadata(&backup) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(config_io_error("检查配置恢复副本", &backup, error)),
    };
    if !backup_metadata.file_type().is_file() {
        return Err(CoreError::new(
            fvcore::ErrorCode::InvalidInput,
            format!(
                "配置恢复副本不是普通文件，拒绝自动处理: {}",
                backup.display()
            ),
            false,
        ));
    }
    match std::fs::symlink_metadata(&path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            std::fs::rename(&backup, &path)
                .map_err(|error| config_io_error("恢复中断覆盖前的配置", &path, error))
        }
        Err(error) => Err(config_io_error("检查当前配置", &path, error)),
        Ok(metadata) if !metadata.file_type().is_file() => Err(CoreError::new(
            fvcore::ErrorCode::InvalidInput,
            format!(
                "当前配置不是普通文件，无法处理恢复副本: {}；恢复副本保留在 {}",
                path.display(),
                backup.display()
            ),
            false,
        )),
        Ok(_) if validate_config_file(&path).is_ok() => std::fs::remove_file(&backup)
            .map_err(|error| config_io_error("清理已完成覆盖的恢复副本", &backup, error)),
        Ok(_) => restore_invalid_config(&path, &backup, directory),
    }
}

fn restore_invalid_config(path: &Path, backup: &Path, directory: &Path) -> Result<(), CoreError> {
    let invalid = directory.join(format!(".config.{}.invalid", uuid::Uuid::now_v7()));
    std::fs::rename(path, &invalid)
        .map_err(|error| config_io_error("暂存未完成的覆盖配置", path, error))?;
    if let Err(error) = std::fs::rename(backup, path) {
        let _ = std::fs::rename(&invalid, path);
        return Err(config_io_error("恢复覆盖前的配置", path, error));
    }
    std::fs::remove_file(&invalid)
        .map_err(|error| config_io_error("清理未完成的覆盖配置", &invalid, error))
}

fn validate_config_file(path: &Path) -> Result<(), CoreError> {
    let mut config = CoreConfig::from_json_file(path)?;
    config.resolve_storage_paths(path.parent().unwrap_or_else(|| Path::new(".")));
    config.validate()
}

fn config_io_error(action: &str, path: &Path, error: std::io::Error) -> CoreError {
    CoreError::new(
        fvcore::ErrorCode::Io,
        format!("无法{action} {}: {error}", path.display()),
        false,
    )
}

fn create_config_directory(directory: Option<&Path>) -> Result<PathBuf, CoreError> {
    match directory {
        Some(directory) => absolute_path(directory),
        None => executable_directory(),
    }
}

fn executable_directory() -> Result<PathBuf, CoreError> {
    let executable = std::env::current_exe().map_err(|error| {
        CoreError::new(
            fvcore::ErrorCode::Io,
            format!("无法确定 fvcore executable 路径: {error}"),
            false,
        )
    })?;
    executable.parent().map(Path::to_owned).ok_or_else(|| {
        CoreError::new(
            fvcore::ErrorCode::Io,
            format!("fvcore executable 路径没有父目录: {}", executable.display()),
            false,
        )
    })
}

fn load_config(web: bool) -> Result<CoreConfig, CoreError> {
    let executable_directory = executable_directory()?;
    load_config_from_directory(&executable_directory, web)
}

#[cfg(test)]
fn load_config_for_executable(executable: &Path, web: bool) -> Result<CoreConfig, CoreError> {
    let executable_directory = executable.parent().ok_or_else(|| {
        CoreError::new(
            fvcore::ErrorCode::Io,
            "fvcore executable path has no parent directory",
            false,
        )
    })?;
    load_config_from_directory(executable_directory, web)
}

fn load_config_from_directory(
    executable_directory: &Path,
    web: bool,
) -> Result<CoreConfig, CoreError> {
    let _lock = lock_config(executable_directory)?;
    recover_config_override(executable_directory)?;
    let config_path = executable_directory.join(CONFIG_FILENAME);
    if !config_path.is_file() {
        return Err(CoreError::new(
            fvcore::ErrorCode::Io,
            format!(
                "未找到 fvcore 配置文件: {}；配置文件必须位于 executable 同级目录: {}；可运行 `fvcore create-config {}` 创建默认配置",
                config_path.display(),
                executable_directory.display(),
                executable_directory.display()
            ),
            false,
        ));
    }
    let mut config = CoreConfig::from_json_file(&config_path)?;
    config.resolve_storage_paths(executable_directory);
    if web {
        config.control.enabled = true;
        config.control.webui_enabled = true;
    } else {
        config.control.webui_enabled = false;
    }
    config.validate()?;
    Ok(config)
}

fn init_tracing() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    tracing_subscriber::fmt().with_env_filter(filter).init();
}

#[cfg(test)]
mod tests {
    use super::{
        CONFIG_BACKUP_FILENAME, Cli, check_config, check_config_path, create_config,
        create_config_directory, executable_directory, load_config_for_executable,
        local_control_url, lock_config, recover_config_override,
    };
    use clap::{CommandFactory, Parser};
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn runtime_requires_config_beside_the_executable() {
        let temp = TempDir::new().unwrap();
        let executable = temp.path().join("fvcore.exe");
        let error = load_config_for_executable(&executable, false).unwrap_err();
        assert_eq!(error.code(), fvcore::ErrorCode::Io);
        assert!(
            error
                .message()
                .contains(&temp.path().join("config.json").display().to_string())
        );
        assert!(error.message().contains("create-config"));
    }

    #[test]
    fn discovers_config_json_beside_the_executable_and_resolves_storage_there() {
        let temp = TempDir::new().unwrap();
        fs::write(
            temp.path().join("config.json"),
            r#"{"instance_name":"adjacent","storage":{"data":"State/Data","cache":"State/Cache","downloads":"State/Downloads","temp":"State/Temp"}}"#,
        )
        .unwrap();
        let config = load_config_for_executable(&temp.path().join("fvcore.exe"), false).unwrap();
        assert_eq!(config.instance_name, "adjacent");
        assert_eq!(config.storage.data, temp.path().join("State/Data"));
        assert!(!config.control.webui_enabled);
    }

    #[test]
    fn custom_runtime_config_path_is_not_accepted() {
        assert!(Cli::try_parse_from(["fvcore", "--config", "explicit.json", "run"]).is_err());
    }

    #[test]
    fn wildcard_listener_has_a_browsable_local_url() {
        assert_eq!(
            local_control_url("0.0.0.0:8787".parse().unwrap()),
            "http://127.0.0.1:8787/"
        );
        assert_eq!(
            local_control_url("[::]:8787".parse().unwrap()),
            "http://[::1]:8787/"
        );
        assert_eq!(
            local_control_url("192.168.1.20:9000".parse().unwrap()),
            "http://192.168.1.20:9000/"
        );
    }

    #[test]
    fn web_command_alone_enables_listener_and_webui() {
        let temp = TempDir::new().unwrap();
        fs::write(
            temp.path().join("config.json"),
            r#"{"control":{"enabled":false,"webui_enabled":false}}"#,
        )
        .unwrap();
        let executable = temp.path().join("fvcore.exe");
        let run = load_config_for_executable(&executable, false).unwrap();
        assert!(!run.control.enabled);
        assert!(!run.control.webui_enabled);
        let web = load_config_for_executable(&executable, true).unwrap();
        assert!(web.control.enabled);
        assert!(web.control.webui_enabled);
    }

    #[test]
    fn parses_configuration_management_commands() {
        assert!(Cli::try_parse_from(["fvcore", "help"]).is_ok());
        assert!(Cli::try_parse_from(["fvcore", "web"]).is_ok());
        assert!(Cli::try_parse_from(["fvcore", "check-config"]).is_ok());
        assert!(Cli::try_parse_from(["fvcore", "check-config", "custom.json"]).is_ok());
        assert!(Cli::try_parse_from(["fvcore", "create-config"]).is_ok());
        assert!(Cli::try_parse_from(["fvcore", "create-config", "."]).is_ok());
        assert!(Cli::try_parse_from(["fvcore", "create-config", "--override"]).is_ok());
        assert!(Cli::try_parse_from(["fvcore", "create-config", ".", "--override"]).is_ok());
        assert!(Cli::try_parse_from(["fvcore", "check"]).is_err());
    }

    #[test]
    fn root_and_configuration_help_are_chinese() {
        let mut root = Cli::command();
        let root_help = root.render_help().to_string();
        assert!(root_help.contains("FletViewer 的纯 Rust 业务核心"));
        assert!(root_help.contains("用法:"));
        assert!(root_help.contains("命令:"));
        assert!(root_help.contains("选项:"));
        assert!(root_help.contains("显示帮助。"));
        assert!(!root_help.contains("Usage:"));
        assert!(!root_help.contains("Options:"));

        for name in ["check-config", "create-config"] {
            let command = root
                .find_subcommand_mut(name)
                .expect("configuration subcommand exists");
            let help = command.render_help().to_string();
            assert!(help.contains("用法:"));
            assert!(help.contains("参数:"));
            assert!(help.contains("选项:"));
            assert!(!help.contains("Usage:"));
            assert!(!help.contains("Arguments:"));
            assert!(!help.contains("Options:"));
            if name == "create-config" {
                assert!(help.contains("--override"));
                assert!(help.contains("重置为完整默认配置"));
            }
        }
    }

    #[test]
    fn help_subcommand_uses_the_same_root_help_definition() {
        let mut first = Cli::command();
        let mut second = Cli::command();
        assert_eq!(
            first.render_help().to_string(),
            second.render_help().to_string()
        );
        assert!(first.render_help().to_string().contains("用法: fvcore "));
    }

    #[test]
    fn creates_deterministic_valid_config_without_overwriting() {
        let first = TempDir::new().unwrap();
        let second = TempDir::new().unwrap();
        let first_path = create_config(first.path(), false).unwrap().path;
        let second_path = create_config(second.path(), false).unwrap().path;
        let first_bytes = fs::read(&first_path).unwrap();
        assert_eq!(first_bytes, fs::read(&second_path).unwrap());
        assert_eq!(first_bytes.last(), Some(&b'\n'));
        check_config(&first_path).unwrap();
        let error = create_config(first.path(), false).unwrap_err();
        assert_eq!(error.code(), fvcore::ErrorCode::InvalidInput);
        assert!(error.message().contains("--override"));
        assert_eq!(fs::read(&first_path).unwrap(), first_bytes);
        assert!(!first.path().join(".config.json.tmp").exists());
    }

    #[test]
    fn override_resets_existing_config_to_complete_defaults() {
        let temp = TempDir::new().unwrap();
        let path = temp.path().join("config.json");
        fs::write(&path, r#"{"instance_name":"custom"}"#).unwrap();

        let result = create_config(temp.path(), true).unwrap();

        assert!(result.replaced);
        assert_eq!(result.path, path);
        assert_ne!(
            fs::read_to_string(&path).unwrap(),
            r#"{"instance_name":"custom"}"#
        );
        check_config(&path).unwrap();
        assert!(!temp.path().join(CONFIG_BACKUP_FILENAME).exists());
    }

    #[test]
    fn configuration_directory_lock_rejects_a_second_manager() {
        let temp = TempDir::new().unwrap();
        let _lock = lock_config(temp.path()).unwrap();

        let error = lock_config(temp.path()).unwrap_err();

        assert_eq!(error.code(), fvcore::ErrorCode::AlreadyRunning);
    }

    #[test]
    fn interrupted_override_restores_the_previous_config_when_destination_is_missing() {
        let temp = TempDir::new().unwrap();
        let path = temp.path().join("config.json");
        let backup = temp.path().join(CONFIG_BACKUP_FILENAME);
        let original = r#"{"instance_name":"original"}"#;
        fs::write(&backup, original).unwrap();

        recover_config_override(temp.path()).unwrap();

        assert_eq!(fs::read_to_string(path).unwrap(), original);
        assert!(!backup.exists());
    }

    #[test]
    fn completed_override_discards_the_recovery_copy() {
        let temp = TempDir::new().unwrap();
        let path = temp.path().join("config.json");
        let backup = temp.path().join(CONFIG_BACKUP_FILENAME);
        fs::write(
            &path,
            serde_json::to_vec(&fvcore::CoreConfig::default()).unwrap(),
        )
        .unwrap();
        fs::write(&backup, r#"{"instance_name":"original"}"#).unwrap();

        recover_config_override(temp.path()).unwrap();

        check_config(&path).unwrap();
        assert!(!backup.exists());
    }

    #[test]
    fn interrupted_invalid_override_restores_the_previous_config() {
        let temp = TempDir::new().unwrap();
        let path = temp.path().join("config.json");
        let backup = temp.path().join(CONFIG_BACKUP_FILENAME);
        let original = r#"{"instance_name":"original"}"#;
        fs::write(&path, b"{").unwrap();
        fs::write(&backup, original).unwrap();

        recover_config_override(temp.path()).unwrap();

        assert_eq!(fs::read_to_string(path).unwrap(), original);
        assert!(!backup.exists());
        assert_eq!(
            fs::read_dir(temp.path())
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry.file_name().to_string_lossy().ends_with(".invalid"))
                .count(),
            0
        );
    }

    #[test]
    fn create_config_without_argument_targets_executable_directory() {
        let directory = create_config_directory(None).unwrap();
        assert!(directory.is_absolute());
        assert_eq!(directory, executable_directory().unwrap());
    }

    #[test]
    fn check_config_rejects_unknown_fields_and_invalid_values() {
        let temp = TempDir::new().unwrap();
        let unknown = temp.path().join("unknown.json");
        fs::write(&unknown, r#"{"unknown":true}"#).unwrap();
        assert_eq!(
            check_config(&unknown).unwrap_err().code(),
            fvcore::ErrorCode::Parse
        );
        let invalid = temp.path().join("invalid.json");
        fs::write(&invalid, r#"{"command_capacity":0}"#).unwrap();
        assert_eq!(
            check_config(&invalid).unwrap_err().code(),
            fvcore::ErrorCode::InvalidConfig
        );
    }

    #[test]
    fn check_config_reports_missing_file_and_expected_directory() {
        let temp = TempDir::new().unwrap();
        let missing = temp.path().join("nested/config.json");
        let error = check_config(&missing).unwrap_err();
        let expected: std::path::PathBuf = missing.components().collect();
        assert_eq!(error.code(), fvcore::ErrorCode::Io);
        assert!(error.message().contains(&expected.display().to_string()));
        assert!(
            error
                .message()
                .contains(&temp.path().join("nested").display().to_string())
        );
        assert!(error.message().contains("配置文件应位于目录"));
        assert!(error.message().contains("fvcore create-config"));
    }

    #[test]
    fn check_config_explains_when_a_directory_was_supplied() {
        let temp = TempDir::new().unwrap();
        let error = check_config(temp.path()).unwrap_err();
        assert_eq!(error.code(), fvcore::ErrorCode::InvalidInput);
        assert!(error.message().contains("配置路径是目录"));
        assert!(
            error
                .message()
                .contains(&temp.path().join("config.json").display().to_string())
        );
    }

    #[test]
    fn check_config_without_argument_targets_executable_config_json() {
        let path = check_config_path(None).unwrap();
        assert_eq!(path, executable_directory().unwrap().join("config.json"));
    }

    #[test]
    fn runtime_rejects_invalid_adjacent_config_before_startup() {
        let temp = TempDir::new().unwrap();
        fs::write(temp.path().join("config.json"), r#"{"command_capacity":0}"#).unwrap();
        let error = load_config_for_executable(&temp.path().join("fvcore.exe"), false).unwrap_err();
        assert_eq!(error.code(), fvcore::ErrorCode::InvalidConfig);
    }
}
