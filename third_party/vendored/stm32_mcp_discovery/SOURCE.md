# stm32_mcp_discovery —— STM32 工具路径发现（MIT）

Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b discovery.py
（同一仓库 tools.py tool_generate_code 的 CubeMX 脚本写法 `config load / project toolchain / project name / project path / project generate / exit` + `STM32CubeMX -q script`，在适配层 `app/sidecar/dzbench/cubemx.py` 里照搬，十几行，没有单独搬文件）

- 搬了什么：discovery.py 全部——环境变量 → PATH → Windows 注册表 → 已知安装目录（有界 glob）四级查找 CubeMX / CubeIDE / CubeProgrammer / arm gdb / OpenOCD（含 ST 的 OpenOCD 脚本目录），带缓存、路径失效自动重查。
- 改了什么：无（只加文件头两行，文件改名 stm32_discovery.py 避免和别的 discovery 撞名）。
- 侧车只经 `app/sidecar/dzbench/cubemx.py` 调用。
