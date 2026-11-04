Use the embedded-debugger skill to inspect this embedded debugging setup.

Work CLI-first unless an MCP client is already configured:

1. Run `embedded-debugger-mcp doctor`.
2. Run `embedded-debugger-mcp probes list`.
3. If MCP is available, start or verify `embedded-debugger-mcp serve` and use
   MCP tools for session operations.
4. Before any flash erase, flash program, memory write, reset, run, or RTT write,
   state the exact target, probe, file path or address range, and why the
   operation is needed.
5. Report concrete command or tool output as evidence. Do not infer hardware
   success without a successful CLI command or MCP tool result.
