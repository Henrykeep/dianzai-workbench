//! Embedded Debugger MCP Server - Main Entry Point

use clap::Parser;
use embedded_debugger_mcp::config::{
    Command as CliCommand, ConfigCommand, ProbeCommand, SkillCommand,
};
use embedded_debugger_mcp::debugger::discovery::ProbeDiscovery;
use rmcp::{transport::stdio, ServiceExt};
use serde::Serialize;
use std::process::Command as ProcessCommand;
use tracing::{debug, error, info};
use tracing_subscriber::{fmt, EnvFilter};

use embedded_debugger_mcp::{config::Args, tools::EmbeddedDebuggerToolHandler, Config, DebugError};
use skill_installer::{install_skill_bundle, DEFAULT_SKILL_PROMPT};

mod skill_installer;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Parse command line arguments
    let args = Args::parse();

    // Handle special flags first
    if args.generate_config
        || matches!(
            args.command,
            Some(CliCommand::Config {
                action: ConfigCommand::Generate
            })
        )
    {
        let config = Config::default();
        println!("{}", config.to_toml()?);
        return Ok(());
    }

    if let Some(CliCommand::Doctor { json }) = args.command.clone() {
        let mut config_result = Config::load_unvalidated(args.config.as_ref());
        if let Ok(config) = &mut config_result {
            config.merge_args(&args);
        }
        let report = DoctorReport::collect(config_result);
        print_doctor_report(&report, json)?;
        return Ok(());
    }

    // Load configuration
    let mut config = Config::load(args.config.as_ref())?;

    // Merge command line arguments into configuration
    config.merge_args(&args);

    if args.validate_config {
        config.validate()?;
        println!("Configuration is valid");
        return Ok(());
    }

    if args.show_config {
        println!("{}", config.to_toml()?);
        return Ok(());
    }

    // Validate final configuration
    config.validate()?;

    // Initialize logging after config merge so file config is not overwritten by CLI defaults.
    init_logging(&config)?;

    info!(
        "Starting Debugger MCP Server v{}",
        env!("CARGO_PKG_VERSION")
    );
    debug!("Command line args: {:?}", args);

    info!("Configuration loaded and validated successfully");

    if let Some(command) = args.command.clone() {
        return run_cli_command(command, config).await;
    }

    run_mcp_server(config).await
}

async fn run_cli_command(
    command: CliCommand,
    config: Config,
) -> Result<(), Box<dyn std::error::Error>> {
    match command {
        CliCommand::Serve => run_mcp_server(config).await,
        CliCommand::Config { action } => {
            match action {
                ConfigCommand::Generate => println!("{}", Config::default().to_toml()?),
                ConfigCommand::Validate => println!("Configuration is valid"),
                ConfigCommand::Show => println!("{}", config.to_toml()?),
            }
            Ok(())
        }
        CliCommand::Probes {
            action: ProbeCommand::List { json },
        } => {
            let probes = ProbeDiscovery::list_probes()?;
            if json {
                println!("{}", serde_json::to_string_pretty(&probes)?);
            } else if probes.is_empty() {
                println!("No debug probes found");
            } else {
                for (index, probe) in probes.iter().enumerate() {
                    println!(
                        "{}. {} ({:04X}:{:04X}) {}",
                        index + 1,
                        probe.identifier,
                        probe.vendor_id,
                        probe.product_id,
                        probe.serial_number.as_deref().unwrap_or("no serial")
                    );
                }
            }
            Ok(())
        }
        CliCommand::Doctor { json } => {
            let report = DoctorReport::collect(Ok(config));
            print_doctor_report(&report, json)
        }
        CliCommand::Skill { action } => match action {
            SkillCommand::PrintPrompt => {
                print!("{}", DEFAULT_SKILL_PROMPT);
                Ok(())
            }
            SkillCommand::Install {
                target,
                home,
                dry_run,
                force,
                json,
            } => {
                let report = install_skill_bundle(target, home, dry_run, force)?;
                if json {
                    println!("{}", serde_json::to_string_pretty(&report)?);
                } else {
                    report.print_text();
                }
                Ok(())
            }
        },
    }
}

async fn run_mcp_server(config: Config) -> Result<(), Box<dyn std::error::Error>> {
    // Create and serve the handler using rust-sdk standard pattern
    let service = EmbeddedDebuggerToolHandler::new(config)
        .serve(stdio())
        .await
        .inspect_err(|e| {
            error!("Serving error: {:?}", e);
        })?;

    info!("Embedded Debugger MCP Server started successfully");

    // Wait for the service to complete
    service.waiting().await?;

    // Cleanup (simplified - no sessions to manage)
    info!("Cleaning up resources...");

    info!("Embedded Debugger MCP Server stopped");
    Ok(())
}

#[derive(Debug, Serialize)]
struct DoctorReport {
    version: &'static str,
    rustc_version: Option<String>,
    config_valid: bool,
    config_error: Option<String>,
    probe_count: Option<usize>,
    probe_error: Option<String>,
}

impl DoctorReport {
    fn collect(config_result: Result<Config, DebugError>) -> Self {
        let config_result = config_result.and_then(|config| config.validate().map(|()| config));
        let probe_result = ProbeDiscovery::list_probes();

        Self {
            version: env!("CARGO_PKG_VERSION"),
            rustc_version: command_output("rustc", &["--version"]),
            config_valid: config_result.is_ok(),
            config_error: config_result.err().map(|error| error.to_string()),
            probe_count: probe_result.as_ref().ok().map(Vec::len),
            probe_error: probe_result.err().map(|error| error.to_string()),
        }
    }
}

fn print_doctor_report(
    report: &DoctorReport,
    json: bool,
) -> Result<(), Box<dyn std::error::Error>> {
    if json {
        println!("{}", serde_json::to_string_pretty(report)?);
        return Ok(());
    }

    println!("embedded-debugger-mcp doctor");
    println!("version: {}", report.version);
    println!(
        "rustc: {}",
        report.rustc_version.as_deref().unwrap_or("not found")
    );
    println!("config_valid: {}", report.config_valid);
    if let Some(error) = &report.config_error {
        println!("config_error: {}", error);
    }
    println!("probe_count: {}", report.probe_count.unwrap_or(0));
    if let Some(error) = &report.probe_error {
        println!("probe_error: {}", error);
    }
    println!("mcp_mode: use `embedded-debugger-mcp serve`");
    println!("cli_skill_mode: use `embedded-debugger-mcp skill print-prompt`");
    Ok(())
}

fn command_output(command: &str, args: &[&str]) -> Option<String> {
    let output = ProcessCommand::new(command).args(args).output().ok()?;
    if !output.status.success() {
        return None;
    }

    let stdout = String::from_utf8(output.stdout).ok()?;
    Some(stdout.trim().to_string())
}

/// Initialize logging system
fn init_logging(config: &Config) -> Result<(), Box<dyn std::error::Error>> {
    let env_filter =
        EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(&config.logging.level));

    let subscriber = fmt::Subscriber::builder()
        .with_env_filter(env_filter)
        .with_target(true)
        .with_thread_ids(true)
        .with_file(false)
        .with_line_number(false);

    // Configure output destination
    if let Some(log_file) = &config.logging.file {
        let file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_file)?;

        subscriber.with_writer(file).init();

        eprintln!("Logging to file: {}", log_file.display());
    } else {
        subscriber.with_writer(std::io::stderr).init();
    }

    debug!("Logging initialized with level: {}", config.logging.level);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use embedded_debugger_mcp::config::SkillInstallTarget;

    #[test]
    fn test_args_parsing() {
        let args = Args::parse_from([
            "embedded-debugger-mcp",
            "--log-level",
            "debug",
            "--max-sessions",
            "10",
        ]);

        assert_eq!(args.log_level.as_deref(), Some("debug"));
        assert_eq!(args.max_sessions, Some(10));
        assert!(args.command.is_none());
    }

    #[test]
    fn test_subcommand_parsing() {
        let args = Args::parse_from(["embedded-debugger-mcp", "probes", "list", "--json"]);
        assert_eq!(
            args.command,
            Some(CliCommand::Probes {
                action: ProbeCommand::List { json: true }
            })
        );
    }

    #[test]
    fn test_skill_install_subcommand_parsing() {
        let args = Args::parse_from([
            "embedded-debugger-mcp",
            "skill",
            "install",
            "--target",
            "codex",
            "--dry-run",
            "--json",
        ]);
        assert_eq!(
            args.command,
            Some(CliCommand::Skill {
                action: SkillCommand::Install {
                    target: SkillInstallTarget::Codex,
                    home: None,
                    dry_run: true,
                    force: false,
                    json: true,
                }
            })
        );
    }

    #[test]
    fn test_default_config() {
        let config = Config::default();
        assert!(config.validate().is_ok());
        assert_eq!(config.server.max_sessions, 5);
        assert_eq!(config.debugger.default_speed_khz, 4000);
    }
}
