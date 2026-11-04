# stm32_mcp_discovery —— STM32 工具路径发现（MIT）

Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b discovery.py
Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b process.py
Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b server.py
Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b tools.py
Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b mcu.py
Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b project.py
Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b serial_monitor.py
Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b fontgen.py
（同一仓库 tools.py tool_generate_code 的 CubeMX 脚本写法 `config load / project toolchain / project name / project path / project generate / exit` + `STM32CubeMX -q script`，在适配层 `app/sidecar/dzbench/cubemx.py` 里照搬，十几行，没有单独搬文件）

- 搬了什么：discovery.py 全部——环境变量 → PATH → Windows 注册表 → 已知安装目录（有界 glob）四级查找 CubeMX / CubeIDE / CubeProgrammer / arm gdb / OpenOCD（含 ST 的 OpenOCD 脚本目录），带缓存、路径失效自动重查。
- 改了什么：无（只加文件头两行，文件改名 stm32_discovery.py 避免和别的 discovery 撞名）。
- 侧车只经 `app/sidecar/dzbench/cubemx.py` 调用。
- process.py → stm32_process.py：子进程独立进程组 + 超时杀整个进程树（Windows taskkill /T /F，POSIX killpg）、async run()、OpenOCD 会话。改了一处：`from discovery import get_tool` → `from stm32_discovery import get_tool`（模块改名）。cubemx.py 用它的 run() 跑 CubeMX 生成和 CubeIDE 无头编译。
- tools.py build_command（CubeIDE headlessbuild 命令行）在 cubemx.py 里照搬。
- server.py / tools.py / mcu.py / project.py / serial_monitor.py / fontgen.py：上游其余文件原样补齐，整套作为独立 MCP 服务器（`python server.py`）运行，供代理直接挂载。只改一处：tools.py 的 `import discovery` → `import stm32_discovery as discovery`、`import process` → `import stm32_process as process`（跟随上面的改名）；每个文件头加 `# Source:`。
