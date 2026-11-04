//! Embedded debugger MCP tools module
//!
//! This module provides a unified tool handler for all embedded debugging operations
//! using the RMCP 0.3.2 API patterns, similar to the serial-mcp-rs implementation.

// Module declarations
pub mod debugger_tools;
pub mod types;

// Export all 22 tools (13 base debugging + 5 RTT communication + 4 flash tools)
pub use debugger_tools::*;
pub use types::*;
