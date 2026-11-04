# sigrok_mcp_server —— 逻辑分析仪（sigrok-cli 包装）MCP 服务器（MIT，Go）

Source: github.com/KenosInc/sigrok-mcp-server@71a652d cmd/sigrok-mcp-server

- 搬了什么：go.mod/go.sum、cmd/、internal/、README、LICENSE，原样。
- 改了什么：无。`tools/mcp/up.sh` 用 go build 编到 build/mcp/sigrok-mcp-server。
- 运行时调用系统里的 sigrok-cli（外部程序，单独安装，不进本仓库）。
