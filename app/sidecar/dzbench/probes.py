"""调试后端：OpenOCD / J-Link / probe-rs（pyOCD 仍是默认，见 flash.PyOCDBackend）。

接口与 PyOCDBackend 相同：idcode() / read(addr, n) / load(path, base) / reset() / flash_size() / close()，
所以烧录（Flasher）、烧前备份、ELF 变量实时读取（elfsym.SymbolWatch 调 read）三处不用改就能换后端。
dzbench.json / ~/.dzbench/machine.json：
    "flash": {"tool": "openocd" | "jlink" | "probe-rs" | "pyocd", "target": "stm32f407vetx", "probe_kind": "stlink" | "daplink" | "jlink",
              "probe": "<序列号，可空>", "openocd": {"host": "127.0.0.1", "port": 6666}}   # 填 host 就连已在跑的 openocd，不自己起
ST-Link（用户主力）与 DAPLink（队友）是一等公民：四个后端都认这两种探针（J-Link 后端只认 J-Link，选错直接报错说明）。

参考：embedded-debugger-mcp（MIT，Copyright (c) 2024 Adancurusul）src/backend/{mod,openocd_backend,probe_rs_backend}.rs 的
“统一后端 trait + OpenOCD / probe-rs 两个实现、可连已在跑的服务器”结构；那边 OpenOCD 走 GDB RSP，这里改走 OpenOCD TCL RPC
（6666 端口、\\x1a 结尾，read_memory/program/reset 都是现成命令）。J-Link 走 JLinkExe 命令文件（SEGGER 官方 CLI 文档）。
⚠ 测试：假 OpenOCD TCL 服务器 + 假 JLinkExe / probe-rs 脚本（tests/test_probes.py）；真探针未实测。
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import socket
import subprocess
import tempfile
import time

from .flash import FlashError

# target（与 pyOCD 目标名同一套）→ 各工具的芯片名。没登记的型号：openocd 用 flash.openocd.target_cfg，其余直接用 target 原名
TARGETS = {
    "mspm0g3507":   {"openocd": "target/ti/mspm0.cfg", "probe-rs": "MSPM0G3507", "jlink": "MSPM0G3507"},
    "mspm0g3505":   {"openocd": "target/ti/mspm0.cfg", "probe-rs": "MSPM0G3505", "jlink": "MSPM0G3505"},
    "stm32f103c8":  {"openocd": "target/stm32f1x.cfg", "probe-rs": "STM32F103C8", "jlink": "STM32F103C8"},
    "stm32f103rc":  {"openocd": "target/stm32f1x.cfg", "probe-rs": "STM32F103RC", "jlink": "STM32F103RC"},
    "stm32f407vetx": {"openocd": "target/stm32f4x.cfg", "probe-rs": "STM32F407VETx", "jlink": "STM32F407VE"},
    "stm32f407vgtx": {"openocd": "target/stm32f4x.cfg", "probe-rs": "STM32F407VGTx", "jlink": "STM32F407VG"},
    "stm32f427iihx": {"openocd": "target/stm32f4x.cfg", "probe-rs": "STM32F427IIHx", "jlink": "STM32F427II"},
    "stm32h743vitx": {"openocd": "target/stm32h7x.cfg", "probe-rs": "STM32H743VITx", "jlink": "STM32H743VI"},
}
PROBE_KINDS = ("stlink", "daplink", "jlink")
OPENOCD_IF = {"stlink": "interface/stlink.cfg", "daplink": "interface/cmsis-dap.cfg", "jlink": "interface/jlink.cfg"}
TOOLS = ("pyocd", "openocd", "jlink", "probe-rs")
EXE = {"openocd": "openocd", "jlink": "JLinkExe" if os.name != "nt" else "JLink.exe", "probe-rs": "probe-rs"}


def chip_name(tool: str, target: str, fcfg: dict | None = None) -> str:
    t = (target or "").lower()
    over = ((fcfg or {}).get(tool) or {}) if isinstance((fcfg or {}).get(tool), dict) else {}
    if tool == "openocd" and over.get("target_cfg"):
        return over["target_cfg"]
    if over.get("chip"):
        return over["chip"]
    hit = TARGETS.get(t) or next((v for k, v in TARGETS.items() if t.startswith(k) or k.startswith(t)), None)
    if hit:
        return hit[tool]
    if tool == "openocd":
        raise FlashError("target_cfg", f"OpenOCD 不认识目标 {target}", "在 flash.openocd.target_cfg 写 target/xxx.cfg")
    return target


def _exe(tool: str, fcfg: dict) -> str:
    over = (fcfg.get(tool) or {}) if isinstance(fcfg.get(tool), dict) else {}
    p = over.get("exe") or shutil.which(EXE[tool])
    if not p:
        hint = {"openocd": "装 OpenOCD ≥ 0.12（xPack openocd，解压后把 bin 加 PATH）或在 flash.openocd.exe 写路径",
                "jlink": "装 SEGGER J-Link Software Pack，或在 flash.jlink.exe 写 JLink.exe 路径",
                "probe-rs": "cargo install probe-rs-tools（或官网安装脚本），或在 flash.probe-rs.exe 写路径"}[tool]
        raise FlashError("no_" + tool.replace("-", ""), f"找不到 {EXE[tool]}", hint)
    return p


def _run(cmd: list[str], timeout: float = 60) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise FlashError("probe_timeout", f"{pathlib.Path(cmd[0]).name} 超时（{timeout:g} s）", "探针连好了吗？目标板上电了吗？") from e
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise FlashError("probe_cmd", f"{pathlib.Path(cmd[0]).name} 失败（{r.returncode}）：{out.strip()[-300:]}",
                         "看探针是否插好、目标是否上电、有没有别的程序占着探针（Keil / CubeIDE / 另一个 openocd）")
    return out


# ------------------------------------------------------------------------------------------- OpenOCD
class OpenOCDBackend:
    """OpenOCD TCL RPC。默认自己起 openocd（ST-Link / DAPLink / J-Link 接口），配了 host 就连已在跑的服务器。
    长连接：变量实时读取每次 read 只是一条 read_memory，适合 20 ms 级刷新。"""
    def __init__(self, target: str, probe_kind: str = "stlink", serial: str | None = None, fcfg: dict | None = None):
        fcfg = fcfg or {}
        oc = fcfg.get("openocd") if isinstance(fcfg.get("openocd"), dict) else {}
        self.proc = None
        host, port = oc.get("host"), int(oc.get("port", 6666))
        if not host:
            if probe_kind not in OPENOCD_IF:
                raise FlashError("probe_kind", f"不认识探针类型 {probe_kind}", "flash.probe_kind 写 stlink / daplink / jlink")
            cmd = [_exe("openocd", fcfg), "-f", oc.get("interface_cfg") or OPENOCD_IF[probe_kind]]
            if probe_kind == "jlink":
                cmd += ["-c", "transport select swd"]
            if serial:
                cmd += ["-c", f"adapter serial {serial}"]
            cmd += ["-f", chip_name("openocd", target, fcfg), "-c", f"tcl_port {port}", "-c", "gdb_port disabled",
                    "-c", "telnet_port disabled", "-c", "init"]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            host = "127.0.0.1"
        self.sock = self._connect(host, port, float(oc.get("connect_timeout_s", 8)))

    def _connect(self, host, port, timeout):
        t0 = time.monotonic()
        while True:
            try:
                s = socket.create_connection((host, port), timeout=2)
                s.settimeout(float(30))
                return s
            except OSError:
                if self.proc and self.proc.poll() is not None:
                    err = (self.proc.stderr.read() if self.proc.stderr else "")[-400:]
                    raise FlashError("openocd_start", f"openocd 起不来：{err.strip()}",
                                     "探针插好了吗？ST-Link 固件太旧就用 STM32CubeProgrammer 升级；DAPLink 选 probe_kind=daplink")
                if time.monotonic() - t0 > timeout:
                    self.close()
                    raise FlashError("openocd_connect", f"连不上 openocd {host}:{port}", "openocd 在跑吗？tcl_port 对吗？")
                time.sleep(0.1)

    def cmd(self, c: str) -> str:
        self.sock.sendall(c.encode() + b"\x1a")
        buf = b""
        while not buf.endswith(b"\x1a"):
            chunk = self.sock.recv(65536)
            if not chunk:
                raise FlashError("openocd_closed", "openocd 断开了")
            buf += chunk
        return buf[:-1].decode(errors="replace").strip()

    def idcode(self) -> int:
        out = self.cmd("[[target current] cget -dap] dpreg 0")
        m = re.search(r"0x[0-9a-fA-F]+", out)
        if not m:
            raise FlashError("idcode", f"openocd 读不到 DPIDR：{out[:120]}")
        return int(m.group(0), 16)

    def read(self, addr: int, n: int) -> bytes:
        out, data = "", bytearray()
        while len(data) < n:                                    # 分块：一次 4 KB，避免一条回复太长
            k = min(4096, n - len(data))
            out = self.cmd(f"read_memory 0x{addr + len(data):x} 8 {k}")
            vals = re.findall(r"0x[0-9a-fA-F]+", out)
            if len(vals) != k:
                raise FlashError("mem_read", f"openocd 读内存失败 @0x{addr + len(data):08x}：{out[:120]}")
            data += bytes(int(v, 16) for v in vals)
        return bytes(data)

    def load(self, path: str, base: int) -> None:
        p = pathlib.Path(path).as_posix()
        out = self.cmd(f"program {{{p}}} {'0x%x ' % base if p.endswith('.bin') else ''}verify")
        if re.search(r"error|failed|\*\* .*fail", out, re.I) and "Verified OK" not in out:
            raise FlashError("program", f"openocd 烧录失败：{out[-300:]}")

    def flash_size(self) -> int | None:
        m = re.search(r"size\s+(0x[0-9a-fA-F]+|\d+)", self.cmd("flash list") or "")
        return int(m.group(1), 0) if m else None

    def reset(self) -> None:
        self.cmd("reset run")

    def close(self) -> None:
        try:
            if self.proc:
                self.sock.sendall(b"shutdown\x1a")
            self.sock.close()
        except Exception:  # noqa: BLE001
            pass
        if self.proc:
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ------------------------------------------------------------------------------------------- J-Link
class JLinkBackend:
    """JLinkExe 命令文件，每个操作起一次进程（~0.3–1 s），能烧录 / 复位 / 读内存；实时变量刷新会慢，建议 ≥ 200 ms。"""
    def __init__(self, target: str, probe_kind: str = "jlink", serial: str | None = None, fcfg: dict | None = None):
        if probe_kind != "jlink":
            raise FlashError("probe_kind", f"J-Link 后端只认 J-Link 探针（现在是 {probe_kind}）",
                             "ST-Link / DAPLink 选 flash.tool = openocd / probe-rs / pyocd")
        fcfg = fcfg or {}
        self.exe, self.dev, self.serial = _exe("jlink", fcfg), chip_name("jlink", target, fcfg), serial
        self.speed = str(((fcfg.get("jlink") or {}) if isinstance(fcfg.get("jlink"), dict) else {}).get("speed", 4000))

    def _script(self, lines: list[str], timeout: float = 60) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".jlink", delete=False) as f:
            f.write("\n".join(["connect", *lines, "qc"]) + "\n")
        cmd = [self.exe, "-device", self.dev, "-if", "SWD", "-speed", self.speed, "-autoconnect", "1", "-NoGui", "1",
               "-ExitOnError", "1", "-CommandFile", f.name]
        if self.serial:
            cmd[1:1] = ["-USB", self.serial]
        try:
            return _run(cmd, timeout)
        finally:
            os.unlink(f.name)

    def idcode(self) -> int:
        out = self._script([])
        m = re.search(r"(?:SW-DP|DPIDR)[^\n]*?0x([0-9A-Fa-f]{8})", out)
        if not m:
            raise FlashError("idcode", "J-Link 没报出 SW-DP ID：" + out.strip()[-200:])
        return int(m.group(1), 16)

    def read(self, addr: int, n: int) -> bytes:
        out = self._script([f"mem8 0x{addr:08X}, 0x{n:X}"])
        data = bytearray()
        for m in re.finditer(r"^([0-9A-Fa-f]{8})\s*=\s*((?:[0-9A-Fa-f]{2}\s*)+)$", out, re.M):
            data += bytes.fromhex(m.group(2))
        if len(data) < n:
            raise FlashError("mem_read", f"J-Link 读内存只拿到 {len(data)}/{n} 字节")
        return bytes(data[:n])

    def load(self, path: str, base: int) -> None:
        self._script(["r", f"loadfile \"{path}\"" + (f" 0x{base:08X}" if path.endswith(".bin") else "")], timeout=180)

    def flash_size(self) -> int | None:
        return None

    def reset(self) -> None:
        self._script(["r", "g"])

    def close(self) -> None:
        pass


# ------------------------------------------------------------------------------------------- probe-rs
class ProbeRsBackend:
    """probe-rs CLI（ST-Link / CMSIS-DAP(DAPLink) / J-Link 都认）。每操作一次进程，实时变量刷新建议 ≥ 200 ms。"""
    def __init__(self, target: str, probe_kind: str = "stlink", serial: str | None = None, fcfg: dict | None = None):
        fcfg = fcfg or {}
        self.exe, self.chip = _exe("probe-rs", fcfg), chip_name("probe-rs", target, fcfg)
        self.common = ["--chip", self.chip, "--protocol", "swd"] + (["--probe", serial] if serial else [])

    def idcode(self) -> int:
        out = _run([self.exe, "info", "--protocol", "swd"] + (self.common[4:]), 30)
        m = re.search(r"DPIDR[^\n]*?0x([0-9A-Fa-f]{8})|IDCODE[^\n]*?0x([0-9A-Fa-f]{8})", out)
        if not m:
            raise FlashError("idcode", "probe-rs info 里没有 DPIDR：" + out.strip()[-200:])
        return int(m.group(1) or m.group(2), 16)

    def read(self, addr: int, n: int) -> bytes:
        out = _run([self.exe, "read", *self.common, "b8", f"0x{addr:x}", str(n)], 30)
        vals = re.findall(r"\b[0-9a-fA-F]{2}\b", out.split("\n", 1)[-1] if "Finished" in out.split("\n", 1)[0] else out)
        if len(vals) < n:
            raise FlashError("mem_read", f"probe-rs read 只拿到 {len(vals)}/{n} 字节")
        return bytes(int(v, 16) for v in vals[-n:])

    def load(self, path: str, base: int) -> None:
        extra = ["--binary-format", "bin", "--base-address", f"0x{base:x}"] if path.endswith(".bin") else []
        _run([self.exe, "download", *self.common, *extra, "--verify", path], 180)

    def flash_size(self) -> int | None:
        return None

    def reset(self) -> None:
        _run([self.exe, "reset", *self.common], 30)

    def close(self) -> None:
        pass


def make_backend(fcfg: dict):
    """按 flash.tool 造后端。probe_kind 不写：J-Link 工具默认 jlink，其他默认 stlink（用户主力；队友用 DAPLink 写 daplink）。"""
    tool = (fcfg.get("tool") or "pyocd").lower()
    if tool not in TOOLS:
        raise FlashError("tool", f"不认识烧录工具 {tool}", "flash.tool 写 " + " / ".join(TOOLS))
    if tool == "pyocd":
        from .flash import PyOCDBackend               # pyOCD 原生认 ST-Link / DAPLink（CMSIS-DAP）/ J-Link
        return PyOCDBackend(fcfg["target"], fcfg.get("probe"))
    kind = fcfg.get("probe_kind") or ("jlink" if tool == "jlink" else "stlink")
    if kind not in PROBE_KINDS:
        raise FlashError("probe_kind", f"不认识探针类型 {kind}", "flash.probe_kind 写 stlink / daplink / jlink")
    cls = {"openocd": OpenOCDBackend, "jlink": JLinkBackend, "probe-rs": ProbeRsBackend}[tool]
    return cls(fcfg["target"], kind, fcfg.get("probe"), fcfg)


def tool_status(fcfg: dict) -> dict:
    """自检用：当前 tool 的可执行文件在不在（不连探针）。"""
    tool = (fcfg.get("tool") or "pyocd").lower()
    if tool == "pyocd" or tool not in EXE:
        return {"tool": tool, "ok": tool in TOOLS, "exe": None}
    try:
        return {"tool": tool, "ok": True, "exe": _exe(tool, fcfg)}
    except FlashError as e:
        return {"tool": tool, "ok": False, "exe": None, "why": e.message, "fix": e.fix}
