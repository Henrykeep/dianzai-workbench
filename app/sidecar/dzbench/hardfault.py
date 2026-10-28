"""HardFault 解码：按内核分支（ARMv6-M 的 Cortex-M0/M0+ 没有 CFSR/HFSR/MMFAR/BFAR）。

输入：异常栈帧 8 个字（r0 r1 r2 r3 r12 lr pc xpsr）、EXC_RETURN、可选的 SCB 故障寄存器；可选 ELF 符号把 PC/LR 翻成函数名。
寄存器位定义来自 ARMv7-M / ARMv6-M 架构参考手册（事实，不是代码搬运）。思路参考 Helistana 的 HardFault 工具。
⚠ 只用构造的寄存器值单测，未在真实故障上验证。
"""
from __future__ import annotations

from .elfsym import func_at

CFSR_BITS = {
    0: ("IACCVIOL", "取指访问违例（跳到了不可执行的地址，如函数指针为空/野）"),
    1: ("DACCVIOL", "数据访问违例（MPU 保护区）"),
    3: ("MUNSTKERR", "异常返回出栈时 MemManage"),
    4: ("MSTKERR", "异常入栈时 MemManage（栈溢出？）"),
    5: ("MLSPERR", "浮点惰性保存时 MemManage"),
    7: ("MMARVALID", "MMFAR 有效"),
    8: ("IBUSERR", "取指总线错误"),
    9: ("PRECISERR", "精确数据总线错误（BFAR 是出错地址：野指针/外设没开时钟）"),
    10: ("IMPRECISERR", "非精确总线错误（PC 不准，看出错前几条写操作）"),
    11: ("UNSTKERR", "出栈总线错误"),
    12: ("STKERR", "入栈总线错误（栈指针坏了/栈溢出）"),
    13: ("LSPERR", "浮点惰性保存总线错误"),
    15: ("BFARVALID", "BFAR 有效"),
    16: ("UNDEFINSTR", "未定义指令（跑飞，或 FPU 未使能就用浮点）"),
    17: ("INVSTATE", "非法状态（跳转地址最低位为 0，Thumb 位丢了）"),
    18: ("INVPC", "非法 EXC_RETURN"),
    19: ("NOCP", "协处理器不可用（FPU 没在 SystemInit 里打开）"),
    20: ("STKOF", "栈溢出（v8-M 栈限制）"),
    24: ("UNALIGNED", "非对齐访问（开了 UNALIGN_TRP）"),
    25: ("DIVBYZERO", "整数除零（开了 DIV_0_TRP）"),
}
HFSR_BITS = {1: ("VECTTBL", "取向量表出错"), 30: ("FORCED", "可配置故障升级成 HardFault，看 CFSR"), 31: ("DEBUGEVT", "调试事件")}
CORES_V6M = ("cm0", "cm0plus", "cm1")
TARGET_CORE = {"mspm0": "cm0plus", "stm32f0": "cm0", "stm32g0": "cm0plus", "stm32l0": "cm0plus", "stm32f1": "cm3",
               "stm32f4": "cm4", "stm32g4": "cm4", "stm32f7": "cm7", "stm32h7": "cm7"}


def guess_core(target: str | None) -> str | None:
    t = (target or "").lower()
    return next((c for k, c in TARGET_CORE.items() if t.startswith(k)), None)


def decode(frame: list[int], exc_return: int | None = None, core: str | None = None, regs: dict | None = None,
           syms: dict | None = None) -> dict:
    if len(frame) != 8:
        raise ValueError("栈帧需要 8 个字：r0 r1 r2 r3 r12 lr pc xpsr")
    r0, r1, r2, r3, r12, lr, pc, xpsr = frame
    out: dict = {"core": core or "unknown", "pc": f"0x{pc:08x}", "lr": f"0x{lr:08x}", "xpsr": f"0x{xpsr:08x}",
                 "causes": [], "notes": []}
    if syms:
        out["pc_func"], out["lr_func"] = func_at(syms, pc), func_at(syms, lr & ~1)
    if exc_return is not None:
        out["stack"] = "PSP（线程，RTOS 任务栈）" if exc_return & 0x4 else "MSP（主栈）"
        if core not in CORES_V6M and not exc_return & 0x10:
            out["notes"].append("栈帧含浮点寄存器（EXC_RETURN bit4=0），栈帧更长，r0..xpsr 位置不变")
    if not xpsr & (1 << 24):
        out["causes"].append({"name": "T_BIT_0", "why": "xPSR 的 Thumb 位为 0：跳到了偶数地址（函数指针没 |1 或为 NULL）"})
    ipsr = xpsr & 0x1FF
    if ipsr:
        out["notes"].append(f"出错时正在处理异常号 {ipsr}（{'IRQ%d' % (ipsr - 16) if ipsr >= 16 else '系统异常'}）")
    if pc in (0, 0xFFFFFFFF) or pc & 1:
        out["causes"].append({"name": "BAD_PC", "why": "PC 非法（空函数指针 / 栈被冲坏）"})
    if core in CORES_V6M:
        out["notes"].append("ARMv6-M（M0/M0+）没有 CFSR/HFSR/MMFAR/BFAR：只能靠栈帧 PC/LR 定位。"
                            "常见原因：非对齐访问（M0+ 不支持非对齐 LDR/STR）、空指针、栈溢出、外设未上电访问")
        if r0 & 3 or r1 & 3 or r2 & 3 or r3 & 3:
            out["notes"].append("有参数寄存器不是 4 字节对齐：若 PC 处是 LDR/STR，很可能是 M0+ 非对齐访问")
        return out
    regs = regs or {}
    if "cfsr" in regs:
        cfsr = regs["cfsr"]
        for b, (n, why) in CFSR_BITS.items():
            if cfsr >> b & 1 and n not in ("MMARVALID", "BFARVALID"):
                out["causes"].append({"name": n, "why": why})
        if cfsr >> 7 & 1 and "mmfar" in regs:
            out["fault_addr"] = f"0x{regs['mmfar']:08x}"
        if cfsr >> 15 & 1 and "bfar" in regs:
            out["fault_addr"] = f"0x{regs['bfar']:08x}"
    if "hfsr" in regs:
        for b, (n, why) in HFSR_BITS.items():
            if regs["hfsr"] >> b & 1:
                out["causes"].append({"name": n, "why": why})
    return out
