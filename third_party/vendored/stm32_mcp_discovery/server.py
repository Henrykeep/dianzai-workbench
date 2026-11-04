# Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b server.py
"""
MCP Server for STM32CubeIDE automation.

Controls build, code generation, flashing and on-target debugging via the
CubeIDE / CubeMX / CubeProgrammer / OpenOCD / GDB CLIs.  All tool logic
lives in tools.py; this module only registers the MCP surface.

Run:  python server.py
"""

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

import tools
import fontgen

server = Server("stm32cubeide-server")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="discover_tools",
            description=(
                "扫描系统中的 CubeIDE/CubeMX/CubeProgrammer/GDB/OpenOCD 安装路径，"
                "用于排查工具未找到问题"
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_project_info",
            description="获取 STM32 工程信息：MCU 型号、构建配置、源文件数等",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "工程目录路径（包含 .project / .cproject 的目录）",
                    },
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="list_projects",
            description=(
                "在指定目录下搜索所有 STM32 工程（含 .project/.cproject 的目录）。"
                "用于自动发现工程位置，AI 无需手动指定完整路径"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "root_path": {
                        "type": "string",
                        "description": "要搜索的根目录（例如工程所在的工作区）",
                    },
                },
                "required": ["root_path"],
            },
        ),
        Tool(
            name="build_project",
            description="编译 STM32 工程（支持 Clean Build 和增量编译）",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "工程目录路径"},
                    "config": {
                        "type": "string",
                        "description": "构建配置名称（Debug / Release）",
                        "default": "Debug",
                    },
                    "clean": {
                        "type": "boolean",
                        "description": "是否先 Clean 再编译",
                        "default": True,
                    },
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="clean_project",
            description="仅清理 STM32 工程的构建产物（不重新编译）",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "工程目录路径"},
                    "config": {
                        "type": "string",
                        "description": "构建配置名称（Debug / Release）",
                        "default": "Debug",
                    },
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="generate_code",
            description="从 .ioc 文件生成 STM32 初始化代码（调用 CubeMX CLI）",
            inputSchema={
                "type": "object",
                "properties": {
                    "ioc_path": {
                        "type": "string",
                        "description": ".ioc 文件的完整路径",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "代码输出目录（默认为 .ioc 所在目录）",
                        "default": "",
                    },
                    "toolchain": {
                        "type": "string",
                        "description": "目标工具链类型",
                        "enum": ["STM32CubeIDE", "MDK-ARM", "EWARM", "Makefile", "CMake"],
                        "default": "STM32CubeIDE",
                    },
                },
                "required": ["ioc_path"],
            },
        ),
        Tool(
            name="flash_firmware",
            description="将固件烧录到 STM32 芯片（通过 ST-LINK 等调试器）",
            inputSchema={
                "type": "object",
                "properties": {
                    "firmware_path": {
                        "type": "string",
                        "description": "固件文件路径（.bin 或 .hex）",
                    },
                    "address": {
                        "type": "string",
                        "description": "烧录起始地址",
                        "default": "0x08000000",
                    },
                    "probe": {
                        "type": "string",
                        "description": "调试器类型",
                        "enum": ["ST-LINK", "J-Link", "ULINK"],
                        "default": "ST-LINK",
                    },
                    "port": {
                        "type": "string",
                        "description": "连接端口",
                        "enum": ["SWD", "JTAG"],
                        "default": "SWD",
                    },
                },
                "required": ["firmware_path"],
            },
        ),
        Tool(
            name="read_flash",
            description=(
                "通过 CubeProgrammer 读取芯片 Flash 内容并保存为 .bin 文件。"
                "用于验证烧录结果、备份固件或检查意外写入"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "output_path": {
                        "type": "string",
                        "description": "保存读取结果的 .bin 文件路径",
                    },
                    "address": {
                        "type": "string",
                        "description": "读取起始地址",
                        "default": "0x08000000",
                    },
                    "length": {
                        "type": "string",
                        "description": "读取长度（字节，十六进制）",
                        "default": "0x40000",
                    },
                    "port": {
                        "type": "string",
                        "description": "连接端口",
                        "enum": ["SWD", "JTAG"],
                        "default": "SWD",
                    },
                },
                "required": ["output_path"],
            },
        ),
        Tool(
            name="erase_flash",
            description="整片擦除芯片 Flash（CubeProgrammer）。用于清空旧固件/恢复变砖设备",
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {
                        "type": "string",
                        "description": "连接端口",
                        "enum": ["SWD", "JTAG"],
                        "default": "SWD",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="list_serial_ports",
            description="枚举当前系统可用的串口（COM 口）列表",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="serial_monitor",
            description=(
                "从串口采集 MCU 的 UART 输出（如 printf 日志），用于验证固件运行状态。"
                "与 debug_run（抓硬件崩溃）互补"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "port": {
                        "type": "string",
                        "description": "串口号，如 COM3（可用 list_serial_ports 查询）",
                    },
                    "baudrate": {
                        "type": "integer",
                        "description": "波特率",
                        "default": 115200,
                    },
                    "duration": {
                        "type": "number",
                        "description": "采集时长（秒）",
                        "default": 5.0,
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "最多采集的字节数",
                        "default": 16384,
                    },
                },
                "required": ["port"],
            },
        ),
        Tool(
            name="debug_run",
            description=(
                "烧录并运行固件，自动捕获 HardFault/MemManage/BusFault/UsageFault 等"
                "运行时错误并解析故障寄存器原因"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "工程目录路径（需先编译过，存在 .elf 文件）",
                    },
                    "config": {
                        "type": "string",
                        "description": "构建配置名称（Debug / Release）",
                        "default": "Debug",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "运行超时秒数（超时后若未触发故障则认为正常运行）",
                        "default": 15,
                    },
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="debug_flash",
            description="通过 GDB 将 .elf 固件烧录到芯片（比 CubeProgrammer 更精确）",
            inputSchema={
                "type": "object",
                "properties": {
                    "elf_path": {
                        "type": "string",
                        "description": ".elf 固件文件的完整路径",
                    },
                },
                "required": ["elf_path"],
            },
        ),
        Tool(
            name="debug_status",
            description="查看当前调试状态：OpenOCD 是否运行、目标连接状态",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="debug_halt",
            description="暂停目标 MCU 运行（需要 OpenOCD 已在运行）",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="debug_resume",
            description="恢复目标 MCU 运行（需要 OpenOCD 已在运行且目标已暂停）",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="oled_add_zh_font",
            description=(
                "向工程 font.c 中文字库表追加波特律动取模生成的字符点阵"
                "（与 led.baud-dance.com 取模助手一致，接口不可用自动回退本地渲染）。"
                "然后即可在 main.c/oled.c 中用 OLED_PrintString 显示新汉字"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "工程目录路径（需包含 Core/Src/font.c）",
                    },
                    "text": {
                        "type": "string",
                        "description": "要生成的汉字（如 \"测试\"），ASCII 字符会被忽略",
                    },
                    "font": {
                        "type": "string",
                        "description": "波特律动字体（文泉驿点阵字），默认 wenquanyi_12pt=16x16",
                        "enum": list(fontgen.FONT_FACES.keys()),
                        "default": "wenquanyi_12pt",
                    },
                    "width": {
                        "type": "integer",
                        "description": "字模宽度，默认 16",
                        "default": 16,
                    },
                    "height": {
                        "type": "integer",
                        "description": "字模高度，默认 16",
                        "default": 16,
                    },
                    "mode": {
                        "type": "string",
                        "description": "取模方式",
                        "enum": list(fontgen.MODES),
                        "default": "列行式",
                    },
                    "color": {
                        "type": "string",
                        "description": "阴阳码",
                        "enum": list(fontgen.COLORS),
                        "default": "阳码",
                    },
                },
                "required": ["project_path", "text"],
            },
        ),
    ]


async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "discover_tools":
            result = await tools.tool_discover_tools()
        elif name == "get_project_info":
            result = await tools.tool_get_project_info(arguments["project_path"])
        elif name == "list_projects":
            result = await tools.tool_list_projects(arguments["root_path"])
        elif name == "build_project":
            result = await tools.tool_build_project(
                arguments["project_path"],
                arguments.get("config", "Debug"),
                arguments.get("clean", True),
            )
        elif name == "clean_project":
            result = await tools.tool_clean_project(
                arguments["project_path"],
                arguments.get("config", "Debug"),
            )
        elif name == "generate_code":
            result = await tools.tool_generate_code(
                arguments["ioc_path"],
                arguments.get("output_path", ""),
                arguments.get("toolchain", "STM32CubeIDE"),
            )
        elif name == "flash_firmware":
            result = await tools.tool_flash_firmware(
                arguments["firmware_path"],
                arguments.get("address", "0x08000000"),
                arguments.get("probe", ""),
                arguments.get("port", "SWD"),
            )
        elif name == "read_flash":
            result = await tools.tool_read_flash(
                arguments["output_path"],
                arguments.get("address", "0x08000000"),
                arguments.get("length", "0x40000"),
                arguments.get("port", "SWD"),
            )
        elif name == "erase_flash":
            result = await tools.tool_erase_flash(arguments.get("port", "SWD"))
        elif name == "list_serial_ports":
            result = await tools.tool_list_serial_ports()
        elif name == "serial_monitor":
            result = await tools.tool_serial_monitor(
                arguments["port"],
                arguments.get("baudrate", 115200),
                arguments.get("duration", 5.0),
                arguments.get("max_bytes", 16384),
            )
        elif name == "debug_run":
            result = await tools.tool_debug_run(
                arguments["project_path"],
                arguments.get("config", "Debug"),
                arguments.get("timeout", 15),
            )
        elif name == "debug_flash":
            result = await tools.tool_debug_flash(arguments["elf_path"])
        elif name == "debug_status":
            result = await tools.tool_debug_status()
        elif name == "debug_halt":
            result = await tools.tool_debug_halt()
        elif name == "debug_resume":
            result = await tools.tool_debug_resume()
        elif name == "oled_add_zh_font":
            result = await tools.tool_oled_add_zh_font(
                arguments["project_path"],
                arguments["text"],
                arguments.get("font", "wenquanyi_12pt"),
                arguments.get("width", 16),
                arguments.get("height", 16),
                arguments.get("mode", "列行式"),
                arguments.get("color", "阳码"),
            )
        else:
            result = f"未知工具: {name}"

        return [TextContent(type="text", text=result)]
    except FileNotFoundError as e:
        return [TextContent(type="text", text=str(e))]
    except Exception as e:
        return [TextContent(
            type="text",
            text=f"执行出错: {type(e).__name__}: {e}",
        )]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    return await handle_tool(name, arguments)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
