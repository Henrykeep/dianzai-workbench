use rmcp::ErrorData as McpError;
use std::path::{Path, PathBuf};

use super::session::{DebugSession, EmbeddedDebuggerToolHandler};
use crate::config::TargetConfig;

const RTT_CONTROL_BLOCK_HEADER_BYTES: usize = 16;
pub(super) type RttScanRange = (u64, u64);
pub(super) type PreparedRttScan = (Option<u64>, Option<Vec<RttScanRange>>);

impl EmbeddedDebuggerToolHandler {
    pub(super) fn flash_erase_allowed(&self) -> bool {
        self.config.security.allow_flash_erase || self.config.flash.allow_erase
    }

    pub(super) fn ensure_flash_erase_allowed(&self) -> Result<(), McpError> {
        if self.flash_erase_allowed() {
            Ok(())
        } else {
            Err(McpError::internal_error(
                "Flash erase is disabled by configuration. Enable security.allow_flash_erase or flash.allow_erase to use this operation."
                    .to_string(),
                None,
            ))
        }
    }

    pub(super) fn ensure_memory_read_allowed(
        &self,
        session: &DebugSession,
        address: u64,
        size: usize,
    ) -> Result<(), McpError> {
        self.ensure_memory_read_allowed_for_target(&session.target_chip, address, size)
    }

    pub(super) fn ensure_memory_read_allowed_for_target(
        &self,
        target_chip: &str,
        address: u64,
        size: usize,
    ) -> Result<(), McpError> {
        if size == 0 {
            return Err(McpError::internal_error(
                "Memory read size must be greater than zero.".to_string(),
                None,
            ));
        }
        if size > self.config.memory.max_read_size {
            return Err(McpError::internal_error(
                format!(
                    "Memory read size {} exceeds configured limit {}.",
                    size, self.config.memory.max_read_size
                ),
                None,
            ));
        }
        self.ensure_memory_region_allowed_for_target(target_chip, address, size, 'r')
    }

    pub(super) fn ensure_memory_write_allowed(
        &self,
        session: &DebugSession,
        address: u64,
        size: usize,
    ) -> Result<(), McpError> {
        if !self.config.security.allow_memory_write {
            return Err(McpError::internal_error(
                "Memory writes are disabled by configuration.".to_string(),
                None,
            ));
        }
        if size == 0 {
            return Err(McpError::internal_error(
                "Memory write size must be greater than zero.".to_string(),
                None,
            ));
        }
        if size > self.config.memory.max_write_size {
            return Err(McpError::internal_error(
                format!(
                    "Memory write size {} exceeds configured limit {}.",
                    size, self.config.memory.max_write_size
                ),
                None,
            ));
        }
        self.ensure_memory_region_allowed(session, address, size, 'w')
    }

    pub(super) fn ensure_memory_region_allowed(
        &self,
        session: &DebugSession,
        address: u64,
        size: usize,
        required_access: char,
    ) -> Result<(), McpError> {
        self.ensure_memory_region_allowed_for_target(
            &session.target_chip,
            address,
            size,
            required_access,
        )
    }

    pub(super) fn ensure_memory_region_allowed_for_target(
        &self,
        target_chip: &str,
        address: u64,
        size: usize,
        required_access: char,
    ) -> Result<(), McpError> {
        let end_exclusive = address.checked_add(size as u64).ok_or_else(|| {
            McpError::internal_error(
                "Memory range overflows u64 address space.".to_string(),
                None,
            )
        })?;

        if !self.config.security.restrict_memory_access {
            return Ok(());
        }

        let target = self.target_config_for(target_chip).ok_or_else(|| {
            McpError::internal_error(
                format!(
                    "Memory access is restricted, but target '{}' has no configured memory map.",
                    target_chip
                ),
                None,
            )
        })?;

        let last_address = end_exclusive - 1;
        let allowed = target.memory_regions.iter().any(|region| {
            address >= region.start
                && last_address <= region.end
                && region.access.contains(required_access)
        });

        if allowed {
            Ok(())
        } else {
            Err(McpError::internal_error(
                format!(
                    "Memory range 0x{address:08X}..0x{last_address:08X} is outside configured '{}' access regions for target '{}'.",
                    required_access, target_chip
                ),
                None,
            ))
        }
    }

    pub(super) fn prepare_rtt_scan_region(
        &self,
        target_chip: &str,
        control_block_address: Option<u64>,
        memory_ranges: Option<Vec<RttScanRange>>,
    ) -> Result<PreparedRttScan, McpError> {
        let control_block_address = control_block_address.or(self.config.rtt.control_block_address);

        if let Some(address) = control_block_address {
            self.ensure_memory_region_allowed_for_target(
                target_chip,
                address,
                RTT_CONTROL_BLOCK_HEADER_BYTES,
                'r',
            )?;
            return Ok((Some(address), None));
        }

        if let Some(ranges) = memory_ranges {
            self.ensure_rtt_ranges_allowed(target_chip, &ranges)?;
            return Ok((None, Some(ranges)));
        }

        if self.config.security.restrict_memory_access {
            return Ok((None, Some(self.configured_rtt_scan_ranges(target_chip)?)));
        }

        Ok((None, None))
    }

    pub(super) fn ensure_rtt_ranges_allowed(
        &self,
        target_chip: &str,
        ranges: &[RttScanRange],
    ) -> Result<(), McpError> {
        if ranges.is_empty() {
            return Err(McpError::internal_error(
                "RTT memory ranges must not be empty.".to_string(),
                None,
            ));
        }

        for (start, end) in ranges {
            let size = end.checked_sub(*start).ok_or_else(|| {
                McpError::internal_error(
                    format!(
                        "RTT memory range 0x{start:08X}..0x{end:08X} has an invalid end address."
                    ),
                    None,
                )
            })?;
            if size == 0 {
                return Err(McpError::internal_error(
                    format!("RTT memory range 0x{start:08X}..0x{end:08X} is empty."),
                    None,
                ));
            }
            let size = usize::try_from(size).map_err(|_| {
                McpError::internal_error(
                    format!("RTT memory range 0x{start:08X}..0x{end:08X} is too large."),
                    None,
                )
            })?;
            self.ensure_memory_region_allowed_for_target(target_chip, *start, size, 'r')?;
        }

        Ok(())
    }

    pub(super) fn configured_rtt_scan_ranges(
        &self,
        target_chip: &str,
    ) -> Result<Vec<RttScanRange>, McpError> {
        let target = self.target_config_for(target_chip).ok_or_else(|| {
            McpError::internal_error(
                format!(
                    "RTT scan is restricted, but target '{}' has no configured memory map.",
                    target_chip
                ),
                None,
            )
        })?;

        let ranges: Result<Vec<_>, _> = target
            .memory_regions
            .iter()
            .filter(|region| region.access.contains('r'))
            .filter(|region| {
                !self.config.rtt.scan_ram_only || region.name.to_ascii_lowercase().contains("ram")
            })
            .map(|region| {
                let end_exclusive = region.end.checked_add(1).ok_or_else(|| {
                    McpError::internal_error(
                        format!("Memory region '{}' end address overflows.", region.name),
                        None,
                    )
                })?;
                Ok((region.start, end_exclusive))
            })
            .collect();

        let ranges = ranges?;
        if ranges.is_empty() {
            return Err(McpError::internal_error(
                format!(
                    "RTT scan is restricted, but target '{}' has no readable configured ranges.",
                    target_chip
                ),
                None,
            ));
        }

        Ok(ranges)
    }

    pub(super) fn target_config_for(&self, target_chip: &str) -> Option<&TargetConfig> {
        let target_chip_lower = target_chip.to_lowercase();
        self.config
            .targets
            .get(&target_chip_lower)
            .or_else(|| self.config.targets.get(target_chip))
            .or_else(|| {
                self.config.targets.values().find(|target| {
                    target.chip.eq_ignore_ascii_case(target_chip)
                        || target.name.eq_ignore_ascii_case(target_chip)
                })
            })
    }

    pub(super) fn resolve_allowed_file_path(
        &self,
        path: &str,
        max_size: usize,
    ) -> Result<PathBuf, McpError> {
        let path = Path::new(path);
        let canonical = path.canonicalize().map_err(|e| {
            McpError::internal_error(
                format!("Failed to resolve file path '{}': {}", path.display(), e),
                None,
            )
        })?;

        let metadata = canonical.metadata().map_err(|e| {
            McpError::internal_error(
                format!(
                    "Failed to read metadata for '{}': {}",
                    canonical.display(),
                    e
                ),
                None,
            )
        })?;
        if !metadata.is_file() {
            return Err(McpError::internal_error(
                format!("Path '{}' is not a regular file.", canonical.display()),
                None,
            ));
        }

        let file_size = metadata.len() as usize;
        let max_size = max_size.min(self.config.security.max_file_size);
        if file_size > max_size {
            return Err(McpError::internal_error(
                format!(
                    "File '{}' is {} bytes, exceeding configured limit {}.",
                    canonical.display(),
                    file_size,
                    max_size
                ),
                None,
            ));
        }

        if self.config.security.allowed_file_paths.is_empty() {
            return Ok(canonical);
        }

        let allowed = self
            .config
            .security
            .allowed_file_paths
            .iter()
            .filter_map(|root| Path::new(root).canonicalize().ok())
            .any(|root| canonical.starts_with(root));

        if allowed {
            Ok(canonical)
        } else {
            Err(McpError::internal_error(
                format!(
                    "File '{}' is outside configured allowed_file_paths.",
                    canonical.display()
                ),
                None,
            ))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;

    #[test]
    fn restricted_rtt_exact_address_uses_target_memory_map() {
        let mut config = Config::default();
        config.security.restrict_memory_access = true;
        let handler = EmbeddedDebuggerToolHandler::new(config);

        assert!(handler
            .prepare_rtt_scan_region("STM32F407VGTx", Some(0x2000_0000), None)
            .is_ok());
        assert!(handler
            .prepare_rtt_scan_region("STM32F407VGTx", Some(0x4000_0000), None)
            .is_err());
    }

    #[test]
    fn restricted_rtt_ranges_must_stay_inside_readable_regions() {
        let mut config = Config::default();
        config.security.restrict_memory_access = true;
        let handler = EmbeddedDebuggerToolHandler::new(config);

        assert!(handler
            .prepare_rtt_scan_region(
                "STM32F407VGTx",
                None,
                Some(vec![(0x2000_0000, 0x2000_0100)])
            )
            .is_ok());
        assert!(handler
            .prepare_rtt_scan_region(
                "STM32F407VGTx",
                None,
                Some(vec![(0x2002_FF00, 0x2003_0100)])
            )
            .is_err());
        assert!(handler
            .prepare_rtt_scan_region(
                "STM32F407VGTx",
                None,
                Some(vec![(0x2000_0000, 0x2000_0000)])
            )
            .is_err());
    }

    #[test]
    fn restricted_flash_verify_reads_use_memory_policy() {
        let mut config = Config::default();
        config.security.restrict_memory_access = true;
        config.memory.max_read_size = 16;
        let handler = EmbeddedDebuggerToolHandler::new(config);

        assert!(handler
            .ensure_memory_read_allowed_for_target("STM32F407VGTx", 0x0800_0000, 16)
            .is_ok());
        assert!(handler
            .ensure_memory_read_allowed_for_target("STM32F407VGTx", 0x0800_0000, 17)
            .is_err());
        assert!(handler
            .ensure_memory_read_allowed_for_target("STM32F407VGTx", 0x4000_0000, 4)
            .is_err());
    }
}
