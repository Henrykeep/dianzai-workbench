# embedded_debugger_mcp —— probe-rs 烧录/调试/读写内存/RTT MCP 服务器（MIT，Rust）

Source: github.com/Adancurusul/embedded-debugger-mcp@7113ae4 src

- 搬了什么：Cargo.toml/Cargo.lock、src/、skills/、.claude-plugin/（include_str! 要用）、README、LICENSE，原样。
- 改了什么：无。`tools/mcp/up.sh` 用 cargo 编到 build/mcp/embedded-debugger-mcp，独立进程运行。需要 libudev-dev、pkg-config。
