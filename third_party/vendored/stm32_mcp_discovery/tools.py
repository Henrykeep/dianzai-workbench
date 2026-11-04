# Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b tools.py
"""
Async implementations of all MCP tools.

Every function here is fully async (no nested asyncio.run), so the MCP
server never creates competing event loops and concurrent tool calls are
safe.  Stateful debug operations are guarded by _debug_lock.
"""

import asyncio
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import stm32_discovery as discovery
import fontgen
import mcu
import stm32_process as process
import project as project_utils
import serial_monitor

# Guards all operations that touch the shared OpenOCD session / debug state.
_debug_lock = asyncio.Lock()

# Persistent session object for debug_status / debug_halt / debug_resume.
_persistent_session = process.OpenOCDSession()


# ── workspace management ───────────────────────────────────────────────────

_WS_ROOT = os.path.join(tempfile.gettempdir(), "cubeide_ws")
_WS_MAX_AGE_SECONDS = 24 * 3600


def _cleanup_stale_workspaces() -> None:
    """Remove workspace dirs older than a day (both legacy and current)."""
    try:
        now = time.time()
        for name in os.listdir(tempfile.gettempdir()):
            if not name.startswith("cubeide_ws"):
                continue
            full = os.path.join(tempfile.gettempdir(), name)
            try:
                if now - os.path.getmtime(full) > _WS_MAX_AGE_SECONDS:
                    shutil.rmtree(full, ignore_errors=True)
            except OSError:
                pass
    except OSError:
        pass


def _get_workspace() -> str:
    os.makedirs(_WS_ROOT, exist_ok=True)
    _cleanup_stale_workspaces()
    return _WS_ROOT


# ── command builders (pure, unit-testable) ─────────────────────────────────

def build_command(cubeide: str, workspace: str, project_path: str,
                  config: str, clean: bool) -> list[str]:
    """Assemble the CubeIDE headless-build command line."""
    project_name = os.path.basename(project_path)
    build_action = "-cleanBuild" if clean else "-build"
    return [
        cubeide,
        "--launcher.suppressErrors",
        "-nosplash",
        "-application", "org.eclipse.cdt.managedbuilder.core.headlessbuild",
        "-data", workspace,
        "-import", project_path,
        build_action, f"{project_name}/{config}",
    ]


def clean_command(cubeide: str, workspace: str, project_path: str,
                  config: str) -> list[str]:
    """Assemble the CubeIDE clean-only command line."""
    project_name = os.path.basename(project_path)
    return [
        cubeide,
        "--launcher.suppressErrors",
        "-nosplash",
        "-application", "org.eclipse.cdt.managedbuilder.core.headlessbuild",
        "-data", workspace,
        "-import", project_path,
        "-clean", f"{project_name}/{config}",
    ]


def cubeprog_flash_command(cubeprog: str, firmware_path: str,
                           address: str, probe: str, port: str) -> list[str]:
    return [
        cubeprog,
        "-c", f"port={port}",
        "-w", firmware_path, address,
        "-v",
        "-rst",
    ]


def cubeprog_read_command(cubeprog: str, output_path: str,
                          address: str, length: str, port: str) -> list[str]:
    return [
        cubeprog,
        "-c", f"port={port}",
        "-r", output_path, address, length,
    ]


def cubeprog_erase_command(cubeprog: str, port: str) -> list[str]:
    return [
        cubeprog,
        "-c", f"port={port}",
        "-e", "all",
    ]


def _parse_build_errors(stderr: str) -> list[str]:
    """Extract GCC-style error lines from build output."""
    errors = []
    for line in stderr.splitlines():
        line = line.strip()
        if not line:
            continue
        if ": error:" in line or ": fatal error:" in line:
            errors.append(line)
        if "undefined reference" in line:
            errors.append(line)
    return errors


# ── build / codegen / flash ────────────────────────────────────────────────

async def tool_build_project(project_path: str, config: str = "Debug",
                             clean: bool = True) -> str:
    cubeide = discovery.get_tool("cubeide")
    workspace = _get_workspace()
    cmd = build_command(cubeide, workspace, project_path, config, clean)

    returncode, stdout, stderr = await process.run(cmd, timeout=300)

    if returncode == 0:
        elf = project_utils.find_elf(project_path, config)
        elf_info = f"\n输出: {elf}" if elf else ""
        return f"构建成功（{os.path.basename(project_path)}/{config}）{elf_info}"

    errors = _parse_build_errors(stderr)
    if errors:
        return f"构建失败，{len(errors)} 个错误:\n" + "\n".join(errors[:20])
    return f"构建失败（返回码 {returncode}）\n{stderr[-2000:]}"


async def tool_clean_project(project_path: str, config: str = "Debug") -> str:
    cubeide = discovery.get_tool("cubeide")
    workspace = _get_workspace()
    cmd = clean_command(cubeide, workspace, project_path, config)

    returncode, stdout, stderr = await process.run(cmd, timeout=300)

    if returncode == 0:
        return f"清理成功（{os.path.basename(project_path)}/{config}）"
    return f"清理失败（返回码 {returncode}）\n{stderr[-1000:]}"


async def tool_generate_code(ioc_path: str, output_path: str = "",
                             toolchain: str = "STM32CubeIDE") -> str:
    if not os.path.isfile(ioc_path):
        return f"ioc 文件不存在: {ioc_path}"

    cubemx = discovery.get_tool("cubemx")
    if not output_path:
        output_path = os.path.dirname(ioc_path)

    script_content = (
        f"config load {ioc_path}\n"
        f"project toolchain {toolchain}\n"
        f"project name {Path(output_path).name or Path(ioc_path).stem}\n"
        f"project path {output_path}\n"
        f"project generate\n"
        f"exit\n"
    )
    fd, script_path = tempfile.mkstemp(suffix=".txt", prefix="cubemx_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script_content)

        returncode, stdout, stderr = await process.run(
            [cubemx, "-q", script_path], timeout=120
        )
        if returncode == 0:
            return f"代码生成成功 → {output_path}"
        return f"代码生成失败（返回码 {returncode}）\n{stderr[:1000]}"
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)


async def tool_flash_firmware(firmware_path: str, address: str = "0x08000000",
                              probe: str = "", port: str = "SWD") -> str:
    if not os.path.isfile(firmware_path):
        return f"固件文件不存在: {firmware_path}"

    cubeprog = discovery.get_tool("cubeprog")
    probe = probe or os.environ.get("PROBE_TYPE", "ST-LINK")
    port = port or os.environ.get("CONNECTION", "SWD")

    cmd = cubeprog_flash_command(cubeprog, firmware_path, address, probe, port)
    returncode, stdout, stderr = await process.run(cmd, timeout=60)

    if returncode == 0:
        return f"烧录成功 → {address}\n{stdout[-500:]}"

    if "No STM32 target found" in stderr or "ST-LINK error" in stderr:
        return "错误: 未检测到 STM32 设备，请检查连接和供电"
    return f"烧录失败（返回码 {returncode}）\n{stderr[:1000]}"


async def tool_read_flash(output_path: str, address: str = "0x08000000",
                          length: str = "0x40000",
                          port: str = "SWD") -> str:
    cubeprog = discovery.get_tool("cubeprog")
    cmd = cubeprog_read_command(cubeprog, output_path, address, length, port)
    returncode, stdout, stderr = await process.run(cmd, timeout=120)

    if returncode == 0:
        return f"Flash 读取成功 → {output_path}\n{stdout[-500:]}"
    return f"Flash 读取失败（返回码 {returncode}）\n{stderr[:1000]}"


async def tool_erase_flash(port: str = "SWD") -> str:
    cubeprog = discovery.get_tool("cubeprog")
    cmd = cubeprog_erase_command(cubeprog, port)
    returncode, stdout, stderr = await process.run(cmd, timeout=120)

    if returncode == 0:
        return f"Flash 擦除成功\n{stdout[-500:]}"
    return f"Flash 擦除失败（返回码 {returncode}）\n{stderr[:1000]}"


async def tool_discover_tools() -> str:
    lines = ["工具发现结果:"]
    for name, label in [("cubeide", "STM32CubeIDE"),
                        ("cubemx", "STM32CubeMX"),
                        ("cubeprog", "STM32CubeProgrammer"),
                        ("gdb", "arm-none-eabi-gdb"),
                        ("openocd", "OpenOCD"),
                        ("openocd_scripts", "OpenOCD Scripts"),
                        ("openocd_core_scripts", "OpenOCD Core Scripts")]:
        try:
            path = discovery.get_tool(name)
            lines.append(f"  {label}: {path}")
        except FileNotFoundError:
            env_key = discovery._TOOL_ENV_VARS.get(name, name.upper())
            lines.append(f"  {label}: 未找到（设置 {env_key} 环境变量）")
    return "\n".join(lines)


async def tool_list_projects(root_path: str) -> str:
    if not os.path.isdir(root_path):
        return f"目录不存在: {root_path}"
    found = project_utils.list_projects(root_path)
    if not found:
        return f"在 {root_path} 下未发现 STM32 工程"
    lines = [f"发现 {len(found)} 个工程:"]
    for p in found:
        lines.append(f"  {p}")
    return "\n".join(lines)


async def tool_get_project_info(project_path: str) -> str:
    return project_utils.parse_project_info(project_path)


# ── serial monitor ─────────────────────────────────────────────────────────

async def tool_list_serial_ports() -> str:
    try:
        ports = await serial_monitor.list_ports()
    except ImportError:
        return "未安装 pyserial，请运行: pip install pyserial"
    if not ports:
        return "未发现串口设备"
    lines = [f"发现 {len(ports)} 个串口:"]
    for device, description in ports:
        lines.append(f"  {device} — {description}")
    return "\n".join(lines)


async def tool_serial_monitor(port: str, baudrate: int = 115200,
                              duration: float = 5.0,
                              max_bytes: int = 16384) -> str:
    try:
        text = await serial_monitor.capture(port, baudrate, duration, max_bytes)
    except serial_monitor.SerialError as e:
        return f"串口错误: {e}"
    header = f"[{port} @{baudrate}bps, 采集 {duration:.1f}s]"
    return f"{header}\n{text}"


# ── debug tools (OpenOCD + GDB) ────────────────────────────────────────────

def _fault_markers() -> list[str]:
    return ["HardFault_Handler", "MemManage_Handler",
            "BusFault_Handler", "UsageFault_Handler"]


def _fault_diag_commands(gdb_port: int) -> list[str]:
    return [
        f"target extended-remote localhost:{gdb_port}",
        "info registers pc lr sp xpsr",
        "x/1xw 0xE000ED28",
        "x/1xw 0xE000ED2C",
        "x/1xw 0xE000ED38",
        "bt",
    ]


async def tool_debug_run(project_path: str, config: str = "Debug",
                         timeout: int = 15) -> str:
    elf = project_utils.find_elf(project_path, config)
    if not elf:
        return f"未找到 .elf 文件。请先编译工程: {project_path}/{config}"

    mcu_family = mcu.detect_mcu_family(project_path)
    if not mcu_family:
        return "无法自动识别 MCU 型号，请检查 .ioc 或 .cproject 文件"

    session = process.OpenOCDSession()
    async with _debug_lock:
        try:
            gdb_port, _ = await session.start(mcu_family)
        except FileNotFoundError as e:
            return str(e)
        except RuntimeError as e:
            return str(e)

        gdb_cmds = [
            f"target extended-remote localhost:{gdb_port}",
            "monitor reset halt",
            "load",
            "break HardFault_Handler",
            "break MemManage_Handler",
            "break BusFault_Handler",
            "break UsageFault_Handler",
            "continue",
        ]
        try:
            output = await process.gdb_run(
                gdb_cmds, elf_path=elf, timeout=timeout + 20
            )
        except RuntimeError as e:
            # `-batch` + `continue` never returns when the firmware runs without
            # tripping a fault breakpoint, so a timeout is the normal case here.
            # Probe the target to distinguish "running fine" from a hard fault.
            try:
                diag_output = await process.gdb_run(
                    _fault_diag_commands(gdb_port), timeout=15
                )
            except Exception:
                diag_output = ""
            finally:
                await session.stop()

            cfsr = None
            for line in diag_output.splitlines():
                m = re.search(r"0xE000ED28[:\s]+(0x[0-9a-fA-F]+)", line)
                if m:
                    try:
                        cfsr = int(m.group(1), 16)
                    except ValueError:
                        cfsr = None
                    break
            if cfsr:
                diagnosis = mcu.parse_fault_registers(diag_output)
                return f"固件运行后触发故障!\n\n{diagnosis}"
            return (
                f"固件正常运行（{timeout}s 内无故障触发）\n\n"
                "确认: 程序未进入 HardFault/MemManage/BusFault/UsageFault 任一断点"
            )

        is_fault = any(marker in output for marker in _fault_markers())
        if not is_fault:
            return (
                f"固件正常运行（{timeout}s 内无故障触发）\n\n"
                "确认: 程序未进入 HardFault/MemManage/BusFault/UsageFault 任一断点"
            )

        # Target halted at a fault breakpoint — read registers for diagnosis.
        try:
            diag_output = await process.gdb_run(
                _fault_diag_commands(gdb_port), timeout=15
            )
        except Exception:
            diag_output = ""
        finally:
            await session.stop()

        diagnosis = mcu.parse_fault_registers(diag_output)
        return f"固件运行后触发故障!\n\n{diagnosis}"


async def tool_debug_flash(elf_path: str) -> str:
    if not os.path.isfile(elf_path):
        return f"固件文件不存在: {elf_path}"

    project_dir = os.path.dirname(elf_path)
    mcu_family = mcu.detect_mcu_family(project_dir)
    if not mcu_family:
        mcu_family = mcu.detect_mcu_family(os.path.dirname(project_dir))
    if not mcu_family:
        return "无法自动识别 MCU 型号，请确认 .elf 与工程文件在同一目录"

    session = process.OpenOCDSession()
    async with _debug_lock:
        try:
            gdb_port, _ = await session.start(mcu_family)
        except (FileNotFoundError, RuntimeError) as e:
            return str(e)

        gdb_cmds = [
            f"target extended-remote localhost:{gdb_port}",
            "monitor reset halt",
            "load",
            "monitor reset run",
        ]
        try:
            output = await process.gdb_run(gdb_cmds, elf_path=elf_path, timeout=60)
        except RuntimeError as e:
            return f"烧录超时: {e}\nOpenOCD 日志:\n{session.stderr_tail[-1500:]}"
        finally:
            await session.stop()

    if "Transfer error" in output or "fail" in output.lower():
        return f"烧录失败:\n{output[:1500]}"
    return f"烧录成功（GDB load）\n{output[:500]}"


async def tool_debug_status() -> str:
    async with _debug_lock:
        lines = [
            f"OpenOCD: {'运行中' if _persistent_session.running else '未运行'}",
        ]
        if _persistent_session.running:
            lines.append(f"GDB 端口: {_persistent_session.gdb_port}")
            lines.append(f"Telnet 端口: {_persistent_session.telnet_port}")
    return "\n".join(lines)


async def tool_debug_halt() -> str:
    async with _debug_lock:
        if not _persistent_session.running:
            return "OpenOCD 未在运行，无法执行暂停操作"
        gdb_cmds = [
            f"target extended-remote localhost:{_persistent_session.gdb_port}",
            "monitor halt",
        ]
        try:
            output = await process.gdb_run(gdb_cmds, timeout=10)
            return f"已发送暂停命令\n{output[:500]}"
        except RuntimeError as e:
            return f"暂停超时: {e}"


async def tool_debug_resume() -> str:
    async with _debug_lock:
        if not _persistent_session.running:
            return "OpenOCD 未在运行，无法恢复运行"
        gdb_cmds = [
            f"target extended-remote localhost:{_persistent_session.gdb_port}",
            "continue",
        ]
        try:
            output = await process.gdb_run(gdb_cmds, timeout=10)
            return f"已发送恢复运行命令\n{output[:500]}"
        except RuntimeError as e:
            return f"恢复运行超时: {e}"


# ── 波特律动中文字模 ─────────────────────────────────────────────────────────

async def tool_oled_add_zh_font(project_path: str, text: str,
                                font: str = "wenquanyi_12pt",
                                width: int = 16, height: int = 16,
                                mode: str = "列行式", color: str = "阳码") -> str:
    """向工程 font.c 中文字库表追加波特律动取模生成的字符点阵。

    取模数据优先来自波特律动官方接口（与 led.baud-dance.com 取模助手一致），
    接口不可用时自动回退本地渲染。
    """
    font_c = os.path.join(project_path, "Core", "Src", "font.c")
    if not os.path.isfile(font_c):
        return f"未找到 {font_c}，请确认工程目录结构（Core/Src/font.c）"
    if not text.strip():
        return "text 为空"
    if font not in fontgen.FONT_FACES:
        return (f"未知字体: {font}，可选: "
                + ", ".join(f"{k}({w}x{h})" for k, (w, h) in fontgen.FONT_FACES.items()))
    if mode not in fontgen.MODES:
        return f"未知取模方式: {mode}，可选: {', '.join(fontgen.MODES)}"
    if color not in fontgen.COLORS:
        return f"未知阴阳码: {color}，可选: {', '.join(fontgen.COLORS)}"
    try:
        return fontgen.add_chars_to_font_c(font_c, text, font, width, height, mode, color)
    except Exception as e:
        return f"执行出错: {type(e).__name__}: {e}"
