//! Configuration-driven executable entry point for fvcore.

#![forbid(unsafe_code)]

use clap::{ArgAction, CommandFactory, Parser, Subcommand};
use fvcore::{CoreBuilder, CoreConfig, CoreError};
use std::{
    path::{Path, PathBuf},
    process::ExitCode,
};
use tracing_subscriber::EnvFilter;

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
        /// 要验证的 JSON 配置文件。
        #[arg(value_name = "文件")]
        file: PathBuf,
    },
    /// 在现有目录中创建完整的默认 config.json。
    #[command(
        help_template = "{about}\n\n用法: {usage}\n\n参数:\n{positionals}\n\n选项:\n{options}"
    )]
    CreateConfig {
        /// 用于保存 config.json 的现有目录。
        #[arg(value_name = "目录")]
        directory: PathBuf,
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
            check_config(file)?;
            println!("configuration is valid: {}", file.display());
            return Ok(());
        }
        Some(Command::CreateConfig { directory }) => {
            let path = create_config(directory)?;
            println!("configuration created: {}", path.display());
            return Ok(());
        }
        Some(Command::Run) | Some(Command::Web) | None => {}
    }
    let web = matches!(cli.command, Some(Command::Web));
    let config = load_config(web)?;
    let runtime = CoreBuilder::new(config).build().await?;
    let snapshot = runtime.handle().snapshot().await?;
    tracing::info!(
        runtime_id = %snapshot.runtime_id,
        instance = snapshot.instance_name,
        "fvcore is ready"
    );
    if let Some(listen) = runtime.control_listen() {
        tracing::info!(url = %format!("http://{listen}/"), "HTTP control plane is listening");
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
    if !path.is_file() {
        let directory = path.parent().unwrap_or_else(|| Path::new("."));
        return Err(CoreError::new(
            fvcore::ErrorCode::Io,
            format!(
                "未找到配置文件: {}；配置文件应位于目录: {}",
                path.display(),
                directory.display()
            ),
            false,
        ));
    }
    let mut config = CoreConfig::from_json_file(&path)?;
    config.resolve_storage_paths(path.parent().unwrap_or_else(|| Path::new(".")));
    config.validate()
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

fn create_config(directory: &Path) -> Result<PathBuf, CoreError> {
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
    let path = directory.join("config.json");
    if path.exists() {
        return Err(CoreError::new(
            fvcore::ErrorCode::InvalidInput,
            format!("configuration already exists: {}", path.display()),
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
    let temporary = directory.join(".config.json.tmp");
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
        std::fs::hard_link(&temporary, &path).map_err(|error| {
            CoreError::new(
                fvcore::ErrorCode::Io,
                format!(
                    "failed to publish configuration {}: {error}",
                    path.display()
                ),
                false,
            )
        })?;
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
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result?;
    Ok(path)
}

fn load_config(web: bool) -> Result<CoreConfig, CoreError> {
    let executable = std::env::current_exe().map_err(|error| {
        CoreError::new(
            fvcore::ErrorCode::Io,
            format!("failed to locate fvcore executable: {error}"),
            false,
        )
    })?;
    load_config_for_executable(&executable, web)
}

fn load_config_for_executable(executable: &Path, web: bool) -> Result<CoreConfig, CoreError> {
    let executable_directory = executable.parent().ok_or_else(|| {
        CoreError::new(
            fvcore::ErrorCode::Io,
            "fvcore executable path has no parent directory",
            false,
        )
    })?;
    let config_path = executable_directory.join("config.json");
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
    Ok(config)
}

fn init_tracing() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    tracing_subscriber::fmt().with_env_filter(filter).init();
}

#[cfg(test)]
mod tests {
    use super::{Cli, check_config, create_config, load_config_for_executable};
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
        assert!(Cli::try_parse_from(["fvcore", "check-config", "custom.json"]).is_ok());
        assert!(Cli::try_parse_from(["fvcore", "create-config", "."]).is_ok());
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
        let first_path = create_config(first.path()).unwrap();
        let second_path = create_config(second.path()).unwrap();
        let first_bytes = fs::read(&first_path).unwrap();
        assert_eq!(first_bytes, fs::read(&second_path).unwrap());
        assert_eq!(first_bytes.last(), Some(&b'\n'));
        check_config(&first_path).unwrap();
        let error = create_config(first.path()).unwrap_err();
        assert_eq!(error.code(), fvcore::ErrorCode::InvalidInput);
        assert_eq!(fs::read(&first_path).unwrap(), first_bytes);
        assert!(!first.path().join(".config.json.tmp").exists());
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
}
