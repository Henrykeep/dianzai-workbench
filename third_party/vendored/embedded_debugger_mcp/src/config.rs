//! Configuration management for the debugger MCP server

use crate::error::{DebugError, Result};
use clap::{Parser, Subcommand, ValueEnum};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

/// Command line arguments
#[derive(Parser, Debug)]
#[command(name = "embedded-debugger-mcp")]
#[command(about = "A Model Context Protocol server for embedded debugging")]
#[command(version)]
pub struct Args {
    /// Path to configuration file
    #[arg(short, long)]
    pub config: Option<PathBuf>,

    /// Log level (error, warn, info, debug, trace)
    #[arg(long)]
    pub log_level: Option<String>,

    /// Log file path
    #[arg(long)]
    pub log_file: Option<PathBuf>,

    /// Maximum number of concurrent debug sessions
    #[arg(long)]
    pub max_sessions: Option<usize>,

    /// Session timeout in seconds
    #[arg(long)]
    pub session_timeout: Option<u64>,

    /// Default debugger speed in kHz
    #[arg(long)]
    pub default_speed: Option<u32>,

    /// Connection timeout in milliseconds
    #[arg(long)]
    pub connection_timeout: Option<u64>,

    /// Connection retry count
    #[arg(long)]
    pub retry_count: Option<u32>,

    /// RTT buffer size in bytes
    #[arg(long)]
    pub rtt_buffer_size: Option<usize>,

    /// RTT poll interval in milliseconds
    #[arg(long)]
    pub rtt_poll_interval: Option<u64>,

    /// Allow flash erase operations
    #[arg(long)]
    pub allow_flash_erase: bool,

    /// Restrict memory access to safe ranges
    #[arg(long)]
    pub restrict_memory_access: bool,

    /// Generate default configuration file
    #[arg(long)]
    pub generate_config: bool,

    /// Validate configuration and exit
    #[arg(long)]
    pub validate_config: bool,

    /// Show current configuration and exit
    #[arg(long)]
    pub show_config: bool,

    /// CLI command to run. Defaults to serving MCP over stdio when omitted.
    #[command(subcommand)]
    pub command: Option<Command>,
}

/// Top-level CLI commands.
#[derive(Subcommand, Debug, Clone, PartialEq, Eq)]
pub enum Command {
    /// Serve the MCP server over stdio.
    Serve,
    /// Configuration utilities.
    Config {
        #[command(subcommand)]
        action: ConfigCommand,
    },
    /// Debug probe utilities.
    Probes {
        #[command(subcommand)]
        action: ProbeCommand,
    },
    /// Run environment checks for CLI, MCP, and hardware discovery.
    Doctor {
        /// Emit machine-readable JSON.
        #[arg(long)]
        json: bool,
    },
    /// Skill helper commands for agent-driven workflows.
    Skill {
        #[command(subcommand)]
        action: SkillCommand,
    },
}

/// Configuration CLI commands.
#[derive(Subcommand, Debug, Clone, PartialEq, Eq)]
pub enum ConfigCommand {
    /// Print a default configuration file.
    Generate,
    /// Validate the effective configuration.
    Validate,
    /// Show the effective configuration.
    Show,
}

/// Probe CLI commands.
#[derive(Subcommand, Debug, Clone, PartialEq, Eq)]
pub enum ProbeCommand {
    /// List connected debug probes.
    List {
        /// Emit machine-readable JSON.
        #[arg(long)]
        json: bool,
    },
}

/// Skill helper CLI commands.
#[derive(Subcommand, Debug, Clone, PartialEq, Eq)]
pub enum SkillCommand {
    /// Print the default prompt for CLI+Skill workflows.
    PrintPrompt,
    /// Install the bundled skill for Codex and/or Claude Code.
    Install {
        /// Which assistant target to install for.
        #[arg(long, value_enum, default_value = "both")]
        target: SkillInstallTarget,

        /// Override the user home directory used for installation.
        #[arg(long)]
        home: Option<PathBuf>,

        /// Print planned writes without changing the filesystem.
        #[arg(long)]
        dry_run: bool,

        /// Replace existing installed skill/plugin directories.
        #[arg(long)]
        force: bool,

        /// Emit machine-readable JSON.
        #[arg(long)]
        json: bool,
    },
}

/// Supported skill installation targets.
#[derive(ValueEnum, Debug, Clone, Copy, PartialEq, Eq)]
pub enum SkillInstallTarget {
    /// Install the Codex skill under ~/.codex/skills.
    Codex,
    /// Install Claude Code skill and local plugin-dir package under ~/.claude.
    Claude,
    /// Install both Codex and Claude Code targets.
    Both,
}

/// Main configuration structure
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Config {
    pub server: ServerConfig,
    pub debugger: DebuggerConfig,
    pub rtt: RttConfig,
    pub memory: MemoryConfig,
    pub flash: FlashConfig,
    pub security: SecurityConfig,
    pub targets: HashMap<String, TargetConfig>,
    pub logging: LoggingConfig,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            server: ServerConfig::default(),
            debugger: DebuggerConfig::default(),
            rtt: RttConfig::default(),
            memory: MemoryConfig::default(),
            flash: FlashConfig::default(),
            security: SecurityConfig::default(),
            targets: Self::default_targets(),
            logging: LoggingConfig::default(),
        }
    }
}

impl Config {
    /// Load configuration from file or create default
    pub fn load(config_path: Option<&PathBuf>) -> Result<Self> {
        let config = Self::load_unvalidated(config_path)?;
        config.validate()?;
        Ok(config)
    }

    /// Load configuration from file or create default without validating values.
    pub fn load_unvalidated(config_path: Option<&PathBuf>) -> Result<Self> {
        if let Some(path) = config_path {
            let content = std::fs::read_to_string(path).map_err(|e| {
                DebugError::InvalidConfig(format!("Failed to read config file: {}", e))
            })?;
            toml::from_str(&content)
                .map_err(|e| DebugError::InvalidConfig(format!("Invalid TOML syntax: {}", e)))
        } else {
            Ok(Config::default())
        }
    }

    /// Merge command line arguments into configuration
    pub fn merge_args(&mut self, args: &Args) {
        if let Some(max_sessions) = args.max_sessions {
            self.server.max_sessions = max_sessions;
        }
        if let Some(session_timeout) = args.session_timeout {
            self.server.session_timeout_seconds = session_timeout;
        }
        if let Some(default_speed) = args.default_speed {
            self.debugger.default_speed_khz = default_speed;
        }
        if let Some(connection_timeout) = args.connection_timeout {
            self.debugger.connection_timeout_ms = connection_timeout;
        }
        if let Some(retry_count) = args.retry_count {
            self.debugger.retry_count = retry_count;
        }
        if let Some(rtt_buffer_size) = args.rtt_buffer_size {
            self.rtt.buffer_size = rtt_buffer_size;
        }
        if let Some(rtt_poll_interval) = args.rtt_poll_interval {
            self.rtt.poll_interval_ms = rtt_poll_interval;
        }
        if args.allow_flash_erase {
            self.security.allow_flash_erase = true;
        }
        if args.restrict_memory_access {
            self.security.restrict_memory_access = true;
        }
        if let Some(log_level) = &args.log_level {
            self.logging.level = log_level.clone();
        }
        if let Some(log_file) = &args.log_file {
            self.logging.file = Some(log_file.clone());
        }
    }

    /// Validate configuration
    pub fn validate(&self) -> Result<()> {
        if self.server.max_sessions == 0 {
            return Err(DebugError::InvalidConfig(
                "max_sessions must be > 0".to_string(),
            ));
        }
        if self.debugger.default_speed_khz == 0 {
            return Err(DebugError::InvalidConfig(
                "default_speed_khz must be > 0".to_string(),
            ));
        }
        if self.rtt.buffer_size == 0 {
            return Err(DebugError::InvalidConfig(
                "rtt.buffer_size must be > 0".to_string(),
            ));
        }
        if self.memory.max_read_size == 0 {
            return Err(DebugError::InvalidConfig(
                "memory.max_read_size must be > 0".to_string(),
            ));
        }
        if self.memory.max_write_size == 0 {
            return Err(DebugError::InvalidConfig(
                "memory.max_write_size must be > 0".to_string(),
            ));
        }
        if self.flash.max_binary_size == 0 {
            return Err(DebugError::InvalidConfig(
                "flash.max_binary_size must be > 0".to_string(),
            ));
        }
        if self.security.max_file_size == 0 {
            return Err(DebugError::InvalidConfig(
                "security.max_file_size must be > 0".to_string(),
            ));
        }
        Ok(())
    }

    /// Generate TOML configuration string
    pub fn to_toml(&self) -> Result<String> {
        toml::to_string_pretty(self)
            .map_err(|e| DebugError::InvalidConfig(format!("Failed to serialize config: {}", e)))
    }

    /// Get default target configurations
    fn default_targets() -> HashMap<String, TargetConfig> {
        let mut targets = HashMap::new();

        targets.insert(
            "stm32f407".to_string(),
            TargetConfig {
                name: "STM32F407VG".to_string(),
                chip: "STM32F407VGTx".to_string(),
                architecture: "Cortex-M4".to_string(),
                flash_size: 1048576, // 1MB
                ram_size: 196608,    // 192KB
                flash_algorithm: "STM32F4xx".to_string(),
                memory_regions: vec![
                    MemoryRegion {
                        name: "Flash".to_string(),
                        start: 0x08000000,
                        end: 0x080FFFFF,
                        access: "rx".to_string(),
                    },
                    MemoryRegion {
                        name: "RAM".to_string(),
                        start: 0x20000000,
                        end: 0x2002FFFF,
                        access: "rwx".to_string(),
                    },
                ],
            },
        );

        targets.insert(
            "nrf52832".to_string(),
            TargetConfig {
                name: "nRF52832".to_string(),
                chip: "nrf52832_xxAA".to_string(),
                architecture: "Cortex-M4F".to_string(),
                flash_size: 524288, // 512KB
                ram_size: 65536,    // 64KB
                flash_algorithm: "nRF52".to_string(),
                memory_regions: vec![
                    MemoryRegion {
                        name: "Flash".to_string(),
                        start: 0x00000000,
                        end: 0x0007FFFF,
                        access: "rx".to_string(),
                    },
                    MemoryRegion {
                        name: "RAM".to_string(),
                        start: 0x20000000,
                        end: 0x2000FFFF,
                        access: "rwx".to_string(),
                    },
                ],
            },
        );

        targets
    }
}

impl From<usize> for Config {
    fn from(max_sessions: usize) -> Self {
        let mut config = Config::default();
        config.server.max_sessions = max_sessions;
        config
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ServerConfig {
    pub max_sessions: usize,
    pub session_timeout_seconds: u64,
    pub worker_threads: Option<usize>,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            max_sessions: 5,
            session_timeout_seconds: 3600,
            worker_threads: None,
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DebuggerConfig {
    pub default_speed_khz: u32,
    pub connection_timeout_ms: u64,
    pub retry_count: u32,
    pub probe_discovery_timeout_ms: u64,
    pub halt_on_connect: bool,
    pub reset_on_connect: bool,
    pub connect_under_reset: bool,
    pub default_reset_type: String,
}

impl Default for DebuggerConfig {
    fn default() -> Self {
        Self {
            default_speed_khz: 4000,
            connection_timeout_ms: 5000,
            retry_count: 3,
            probe_discovery_timeout_ms: 2000,
            halt_on_connect: true,
            reset_on_connect: false,
            connect_under_reset: false,
            default_reset_type: "hardware".to_string(),
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RttConfig {
    pub buffer_size: usize,
    pub poll_interval_ms: u64,
    pub max_channels: usize,
    pub scan_timeout_ms: u64,
    pub scan_memory: bool,
    pub scan_ram_only: bool,
    pub control_block_address: Option<u64>,
}

impl Default for RttConfig {
    fn default() -> Self {
        Self {
            buffer_size: 1024,
            poll_interval_ms: 10,
            max_channels: 16,
            scan_timeout_ms: 1000,
            scan_memory: true,
            scan_ram_only: true,
            control_block_address: None,
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct MemoryConfig {
    pub max_read_size: usize,
    pub max_write_size: usize,
    pub cache_enable: bool,
    pub cache_size: usize,
}

impl Default for MemoryConfig {
    fn default() -> Self {
        Self {
            max_read_size: 65536, // 64KB
            max_write_size: 4096, // 4KB
            cache_enable: true,
            cache_size: 1048576, // 1MB
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FlashConfig {
    pub default_erase_timeout_ms: u64,
    pub default_program_timeout_ms: u64,
    pub verify_after_program: bool,
    pub allow_erase: bool,
    pub max_binary_size: usize,
}

impl Default for FlashConfig {
    fn default() -> Self {
        Self {
            default_erase_timeout_ms: 30000,
            default_program_timeout_ms: 60000,
            verify_after_program: true,
            allow_erase: false,
            max_binary_size: 10485760, // 10MB
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SecurityConfig {
    pub allow_flash_erase: bool,
    pub allow_memory_write: bool,
    pub restrict_memory_access: bool,
    pub allowed_file_paths: Vec<String>,
    pub max_file_size: usize,
}

impl Default for SecurityConfig {
    fn default() -> Self {
        Self {
            allow_flash_erase: false,
            allow_memory_write: true,
            restrict_memory_access: false,
            allowed_file_paths: vec![],
            max_file_size: 10485760, // 10MB
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TargetConfig {
    pub name: String,
    pub chip: String,
    pub architecture: String,
    pub flash_size: usize,
    pub ram_size: usize,
    pub flash_algorithm: String,
    pub memory_regions: Vec<MemoryRegion>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct MemoryRegion {
    pub name: String,
    pub start: u64,
    pub end: u64,
    pub access: String, // "r", "w", "x", "rw", "rx", "rwx"
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LoggingConfig {
    pub level: String,
    pub file: Option<PathBuf>,
    pub format: String,
    pub timestamp_format: String,
    pub include_location: bool,
    pub include_thread_names: bool,
}

impl Default for LoggingConfig {
    fn default() -> Self {
        Self {
            level: "info".to_string(),
            file: None,
            format: "text".to_string(),
            timestamp_format: "rfc3339".to_string(),
            include_location: false,
            include_thread_names: false,
        }
    }
}
