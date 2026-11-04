//! RTT (Real-Time Transfer) communication
//!
//! This module provides RTT integration using probe-rs for embedded debugging
//! with enhanced ELF symbol detection based on probe-rs implementation analysis.

pub mod elf_parser;
pub mod manager;

// Export RTT components
pub use elf_parser::{get_elf_debug_info, get_rtt_symbol_from_elf, ElfDebugInfo, SymbolInfo};
pub use manager::{ChannelDirection, ChannelInfo, RttManager};
