# mcp_hardware_tools —— 示波器/信号源 MCP 服务器（Apache-2.0）

Source: github.com/lpender3672/mcp-hardware-tools@e13d9cd src/hwtools

- 搬了什么：整仓 src/、firmware/、pyproject.toml、README.md、LICENSE，原样，作为独立 MCP 服务器进程运行（不 import 进侧车）。
- 改了什么：每个 .py 文件头加一行 `# Source:`，其余不改。
- 怎么启动：`tools/mcp/hwtools_launch.py`（我们的包装）：设了 HWTOOLS_SCOPE_HOST 走原版 main() 连真 DS1054Z；没设就用它自带的 SimulatedScope 起同一套工具（仿真）。
