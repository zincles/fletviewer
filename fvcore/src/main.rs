//! Configuration-driven executable entry point for fvcore.

#![forbid(unsafe_code)]

use clap::{Parser, Subcommand};
use fvcore::{CoreBuilder, CoreConfig, CoreError};
use std::{net::SocketAddr, path::PathBuf, process::ExitCode};
use tracing_subscriber::EnvFilter;

#[derive(Debug, Parser)]
#[command(version, about)]
struct Cli {
    /// TOML configuration file. Defaults are used when omitted.
    #[arg(short, long, global = true)]
    config: Option<PathBuf>,

    /// Enable the integrated HTTP control plane.
    #[arg(long, global = true, conflicts_with = "no_web")]
    web: bool,

    /// Disable HTTP listening even when enabled by configuration.
    #[arg(long, global = true, conflicts_with = "web")]
    no_web: bool,

    /// Override the HTTP control-plane listen address.
    #[arg(long, global = true, value_name = "ADDR")]
    web_listen: Option<SocketAddr>,

    /// Enable the embedded diagnostic WebUI and HTTP listening.
    #[arg(long, global = true, conflicts_with = "no_webui")]
    webui: bool,

    /// Disable only the diagnostic WebUI while keeping configured HTTP APIs available.
    #[arg(long, global = true, conflicts_with = "webui")]
    no_webui: bool,

    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Debug, Subcommand)]
enum Command {
    /// Run the Core until interrupted.
    Run,
    /// Parse and validate configuration, then exit.
    Check,
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
    let config = load_config(&cli)?;
    if matches!(cli.command, Some(Command::Check)) {
        config.validate()?;
        println!("configuration is valid");
        return Ok(());
    }

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

fn load_config(cli: &Cli) -> Result<CoreConfig, CoreError> {
    let mut config = match &cli.config {
        Some(path) => CoreConfig::from_toml_file(path)?,
        None => CoreConfig::default(),
    };
    if cli.web {
        config.control.enabled = true;
    } else if cli.no_web {
        config.control.enabled = false;
    }
    if let Some(listen) = cli.web_listen {
        config.control.enabled = true;
        config.control.listen = listen;
    }
    if cli.webui {
        config.control.enabled = true;
        config.control.webui_enabled = true;
    } else if cli.no_webui {
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
    use super::{Cli, load_config};
    use clap::Parser;
    use std::path::PathBuf;

    #[test]
    fn omitted_config_file_uses_defaults() {
        let cli = Cli::try_parse_from(["fvcore", "check"]).unwrap();
        let config = load_config(&cli).unwrap();
        assert_eq!(config.schema_version, 1);
        assert_eq!(config.instance_name, "fvcore");
        assert_eq!(config.command_capacity, 256);
        assert_eq!(config.shutdown_seconds, 15);
        assert!(!config.control.enabled);
        assert_eq!(config.control.listen.to_string(), "127.0.0.1:8787");
        assert!(config.control.webui_enabled);
        assert_eq!(config.profiles.len(), 4);
        assert_eq!(
            config.storage.data,
            PathBuf::from("FletViewer").join("Data")
        );
    }

    #[test]
    fn webui_flags_are_independent_from_the_control_api() {
        let enabled = Cli::try_parse_from(["fvcore", "--webui", "check"]).unwrap();
        let enabled = load_config(&enabled).unwrap();
        assert!(enabled.control.enabled);
        assert!(enabled.control.webui_enabled);

        let api_only = Cli::try_parse_from(["fvcore", "--web", "--no-webui", "check"]).unwrap();
        let api_only = load_config(&api_only).unwrap();
        assert!(api_only.control.enabled);
        assert!(!api_only.control.webui_enabled);
    }
}
