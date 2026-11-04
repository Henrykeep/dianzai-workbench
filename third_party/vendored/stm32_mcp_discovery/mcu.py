# Source: github.com/Helistana/mcp-stm32cubeide-server@860d90b mcu.py
"""
MCU family detection and fault-register diagnosis.

  * mcu_family_from_name  : STM32F407VG -> stm32f4x.cfg (OpenOCD target file)
  * detect_mcu_family     : sniff the MCU from .ioc / .cproject files
  * parse_fault_registers : turn GDB register dumps into human-readable
                            HardFault/BusFault/UsageFault/MemManage diagnosis
"""

import os
import re
import xml.etree.ElementTree as ET

from project import find_ioc

_SERIES_FAMILY_MAP = {
    "F0": "stm32f0x.cfg", "F1": "stm32f1x.cfg", "F2": "stm32f2x.cfg",
    "F3": "stm32f3x.cfg", "F4": "stm32f4x.cfg", "F7": "stm32f7x.cfg",
    "G0": "stm32g0x.cfg", "G4": "stm32g4x.cfg",
    "H5": "stm32h5x.cfg", "H7": "stm32h7x.cfg",
    "L0": "stm32l0x.cfg", "L1": "stm32l1x.cfg",
    "L4": "stm32l4x.cfg", "L5": "stm32l4x.cfg",
    "C0": "stm32c0x.cfg",
    "U5": "stm32u5x.cfg",
}

_MCU_RE = re.compile(r"STM32([A-Z]\d)\d+", re.IGNORECASE)


def mcu_family_from_name(mcu: str) -> str | None:
    """STM32F407VG -> stm32f4x.cfg (the OpenOCD target config file)."""
    m = _MCU_RE.match(mcu)
    if not m:
        return None
    series = m.group(1).upper()
    return _SERIES_FAMILY_MAP.get(series)


def detect_mcu_family(project_path: str) -> str | None:
    """Determine the MCU family from .ioc (preferred) then .cproject."""
    ioc = find_ioc(project_path)
    if ioc:
        try:
            root = ET.parse(ioc).getroot()
            mcu_name = root.get("Mcu.Name") or root.get("Mcu", "")
            fam = mcu_family_from_name(mcu_name)
            if fam:
                return fam
        except (ET.ParseError, AttributeError):
            pass

    cproject = os.path.join(project_path, ".cproject")
    if os.path.isfile(cproject):
        try:
            tree = ET.parse(cproject)
            text = ET.tostring(tree.getroot(), encoding="unicode")
            m = re.search(r"STM32([A-Z]\d)\d+[A-Z]\d", text)
            if m:
                fam = mcu_family_from_name(m.group(0))
                if fam:
                    return fam
        except ET.ParseError:
            pass
    return None


def _register_at(gdb_output: str, addr_suffix: str) -> int | None:
    """Read a peripheral register value (addr hex suffix) from GDB output."""
    addr_suffix = addr_suffix.lower()
    m = re.search(
        rf"0x[eE]000[eE][dD]{addr_suffix}.*?:\s*(0x[0-9a-fA-F]+)",
        gdb_output,
    )
    return int(m.group(1), 16) if m else None


def parse_fault_registers(gdb_output: str) -> str:
    """Parse GDB register output into a human-readable fault diagnosis."""
    lines_out: list[str] = []

    pc = re.search(r"pc\s+(0x[0-9a-fA-F]+)", gdb_output)
    lr = re.search(r"lr\s+(0x[0-9a-fA-F]+)", gdb_output)
    sp = re.search(r"sp\s+(0x[0-9a-fA-F]+)", gdb_output)

    if pc:
        lines_out.append(f"PC (程序计数器): {pc.group(1)}")
    if lr:
        lines_out.append(f"LR (链接寄存器): {lr.group(1)}")
    if sp:
        lines_out.append(f"SP (栈指针): {sp.group(1)}")

    # CFSR @ 0xE000ED28
    cfsr = _register_at(gdb_output, "28")
    if cfsr is not None:
        lines_out.append(f"\nCFSR (可配置故障状态寄存器): 0x{cfsr:08X}")
        ufsr = cfsr & 0xFFFF
        if ufsr:
            lines_out.append("  [UsageFault]")
            if ufsr & (1 << 0):
                lines_out.append("    - UNDEFINSTR: 未定义指令")
            if ufsr & (1 << 1):
                lines_out.append("    - INVSTATE: 非法指令状态(EPSR)")
            if ufsr & (1 << 2):
                lines_out.append("    - INVPC: 非法PC加载")
            if ufsr & (1 << 3):
                lines_out.append("    - NOCP: 使用了禁用的协处理器")
            if ufsr & (1 << 8):
                lines_out.append("    - UNALIGNED: 非对齐访问")
            if ufsr & (1 << 9):
                lines_out.append("    - DIVBYZERO: 除零错误")
        bfsr = (cfsr >> 8) & 0xFF
        if bfsr:
            lines_out.append("  [BusFault]")
            if bfsr & (1 << 0):
                lines_out.append("    - IBUSERR: 指令总线错误")
            if bfsr & (1 << 1):
                lines_out.append("    - PRECISERR: 精确数据总线错误")
            if bfsr & (1 << 2):
                lines_out.append("    - IMPRECISERR: 不精确数据总线错误")
            if bfsr & (1 << 3):
                lines_out.append("    - UNSTKERR: 异常返回时出栈错误")
            if bfsr & (1 << 4):
                lines_out.append("    - STKERR: 异常入栈错误")
            if bfsr & (1 << 5):
                lines_out.append("    - LSPERR: 浮点惰性状态保存错误")
        mmsr = (cfsr >> 24) & 0xFF
        if mmsr:
            lines_out.append("  [MemManage]")
            if mmsr & (1 << 0):
                lines_out.append("    - IACCVIOL: 尝试执行非法地址")
            if mmsr & (1 << 1):
                lines_out.append("    - DACCVIOL: 非法数据访问(如访问未映射内存)")
            if mmsr & (1 << 3):
                lines_out.append("    - MUNSTKERR: 出栈时MPU访问违规")
            if mmsr & (1 << 4):
                lines_out.append("    - MSTKERR: 入栈时MPU访问违规")
            if mmsr & (1 << 5):
                lines_out.append("    - MLSPERR: 浮点惰性状态MPU违规")

    # HFSR @ 0xE000ED2C
    hfsr = _register_at(gdb_output, "2C")
    if hfsr is not None:
        lines_out.append(f"\nHFSR (硬故障状态寄存器): 0x{hfsr:08X}")
        if hfsr & (1 << 30):
            lines_out.append("  - FORCED: 由其他故障升级而来(见上)")
        if hfsr & (1 << 1):
            lines_out.append("  - VECTBL: 向量表读取故障")

    # BFAR @ 0xE000ED38
    bfar = _register_at(gdb_output, "38")
    if bfar is not None and bfar not in (0x00000000, 0xE000ED38):
        lines_out.append(f"\nBFAR (故障地址): 0x{bfar:08X}")

    # Backtrace — all lines starting with #N
    bt_lines = re.findall(r"#\d+\s+.*", gdb_output)
    if bt_lines:
        lines_out.append("\n调用栈:")
        for line in bt_lines[:10]:
            lines_out.append(f"  {line}")

    return "\n".join(lines_out) if len(lines_out) > 2 else "未能解析故障信息"
