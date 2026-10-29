"""ELF 符号表（纯 Python，只读 ELF32 小端 .symtab）+ 按变量名轮询内存画曲线。

思路参考 stm32-mcp 的“按变量名读内存”；代码自写。没有 DWARF：变量类型由用户选（f32/i32/u32/i16/u16/i8/u8）。
探针抽象 Probe.read(addr, n)；pyOCD 实现在 flash.py；测试用 MockProbe。⚠ 真探针未实测（MSPM0 / STM32 都没上板）。
"""
from __future__ import annotations

import pathlib
import struct
import threading
import time
from dataclasses import dataclass

TYPES = {"f32": "<f", "i32": "<i", "u32": "<I", "i16": "<h", "u16": "<H", "i8": "<b", "u8": "<B"}
STT = {0: "notype", 1: "object", 2: "func", 3: "section", 4: "file"}



GAP = 64


def spans(items: list[tuple[str, int, str]], gap: int = GAP) -> list[tuple[int, int, list]]:
    out: list[list] = []
    for it in sorted(items, key=lambda x: x[1]):
        a, b = it[1], it[1] + struct.calcsize(TYPES[it[2]])
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
            out[-1][2].append(it)
        else:
            out.append([a, b, [it]])
    return [tuple(x) for x in out]

class ElfError(Exception):
    pass


@dataclass
class Sym:
    name: str
    addr: int
    size: int
    kind: str


def load_symbols(path: str | pathlib.Path) -> dict[str, Sym]:
    b = pathlib.Path(path).read_bytes()
    if b[:4] != b"\x7fELF":
        raise ElfError(f"{path} 不是 ELF 文件")
    if b[4] != 1 or b[5] != 1:
        raise ElfError("只支持 32 位小端 ELF（Cortex-M）")
    shoff, = struct.unpack_from("<I", b, 0x20)
    shentsize, shnum, = struct.unpack_from("<HH", b, 0x2E)
    secs = [struct.unpack_from("<IIIIIIIIII", b, shoff + i * shentsize) for i in range(shnum)]
    out: dict[str, Sym] = {}
    for s in secs:
        if s[1] != 2:                                  # SHT_SYMTAB
            continue
        off, size, link, entsize = s[4], s[5], s[6], s[9] or 16
        stroff = secs[link][4]
        for k in range(off, off + size, entsize):
            nm, val, sz, info, _, shndx = struct.unpack_from("<IIIBBH", b, k)
            if not nm or shndx == 0:
                continue
            end = b.index(b"\0", stroff + nm)
            name = b[stroff + nm:end].decode("utf-8", "replace")
            kind = STT.get(info & 0xF, "other")
            if kind in ("object", "func", "notype") and not name.startswith("$"):
                out.setdefault(name, Sym(name, val & ~1 if kind == "func" else val, sz, kind))
    if not out:
        raise ElfError("ELF 里没有符号表（被 strip 了？用带调试信息的 .elf/.axf）")
    return out


def func_at(syms: dict[str, Sym], addr: int) -> str | None:
    best = None
    for s in syms.values():
        if s.kind == "func" and s.addr <= addr < s.addr + max(s.size, 2):
            if not best or s.addr > best.addr:
                best = s
    return f"{best.name}+0x{addr - best.addr:x}" if best else None


class MockProbe:
    """测试用：一块假内存。"""
    def __init__(self, mem: dict[int, bytes] | None = None, idcode: int = 0x0BC11477):
        self.mem, self.idcode, self.halted = dict(mem or {}), idcode, False

    def read(self, addr: int, n: int) -> bytes:
        for base, data in self.mem.items():
            if base <= addr and addr + n <= base + len(data):
                return data[addr - base:addr - base + n]
        raise ElfError(f"读 0x{addr:08x} 失败（假内存没有这块）")


class SymbolWatch:
    """按名字轮询若干变量，样本注入 session（虚拟 schema，tag = ELF）。只读，风险 auto。"""
    MAX = 16

    def __init__(self, session, probe, syms: dict[str, Sym]):
        self.s, self.probe, self.syms = session, probe, syms
        self.stop_ev = threading.Event()
        self.th: threading.Thread | None = None
        self.items: list[tuple[str, int, str]] = []

    def resolve(self, spec: list[dict]) -> list[tuple[str, int, str]]:
        items = []
        for x in spec[: self.MAX]:
            name, ty = x["name"], x.get("type", "f32")
            base = name.split("[")[0].split(".")[0]
            if base not in self.syms:
                raise ElfError(f"ELF 里没有变量 {base}（static 局部变量会被改名，或被优化掉了）")
            if ty not in TYPES:
                raise ElfError(f"类型 {ty} 不支持，可选 {', '.join(TYPES)}")
            items.append((name, self.syms[base].addr + int(x.get("offset", 0)), ty))
        return items

    def schema(self, period_ms: int) -> dict:
        return {"version": 1, "hash": 0, "virtual": True, "params": [],
                "telemetry": {"id": -1, "period_ms": period_ms, "fields": [{"name": n, "type": "f32"} for n, _, _ in self.items]}}

    def sample(self) -> dict:
        """相邻变量合并成一次块读（间隔 ≤ GAP 字节就并），探针往返次数从“每变量一次”降到“每段一次”。"""
        out = {}
        for start, end, members in spans(self.items):
            blob = self.probe.read(start, end - start)
            for name, addr, ty in members:
                k = addr - start
                out[name] = float(struct.unpack(TYPES[ty], blob[k:k + struct.calcsize(TYPES[ty])])[0])
        return out

    def start(self, spec: list[dict], period_ms: int = 10) -> dict:
        self.stop()
        self.items = self.resolve(spec)
        period_ms = max(2, int(period_ms))
        self.s.inject([], self.schema(period_ms), "ELF")
        self.stop_ev = threading.Event()

        def run():
            while not self.stop_ev.wait(period_ms / 1000):
                try:
                    self.s.inject([self.sample()], None, "ELF")
                except Exception as e:      # noqa: BLE001 —— 探针掉线：停下并报告
                    self.s.emit({"type": "error", "code": "probe", "message": f"读变量失败：{e}", "fix": "检查 SWD 线和供电"})
                    break
        self.th = threading.Thread(target=run, daemon=True)
        self.th.start()
        return {"fields": [{"name": n, "addr": f"0x{a:08x}", "type": t} for n, a, t in self.items], "period_ms": period_ms}

    def stop(self) -> None:
        self.stop_ev.set()
        if self.th:
            self.th.join(timeout=1)
            self.th = None
