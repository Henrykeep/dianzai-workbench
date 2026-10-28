"""列出可用端口，自动探测波特率：每个候选波特率听一小段，看能不能解出合法 dzframe。"""
from __future__ import annotations

import os
import shutil
import time

from ._dzlink import Parser
from .transport import ROOT, SIM_PREFIX, sim_elf

# 先试工作台各板默认值（board.yaml 里 LINK 常用），再试常见值
BAUDS = [460800, 921600, 115200, 230400, 1000000, 500000, 57600, 9600]
SIM_APPS = ["car_2wd", "2026H_ball"]


def list_ports() -> list[dict]:
    out = []
    try:
        from serial.tools import list_ports as lp
        for p in lp.comports():
            hint = " ".join(x for x in (p.description, p.manufacturer or "") if x and x != "n/a")
            out.append({"port": p.device, "desc": hint or p.device, "kind": "serial",
                        "likely": any(k in hint.upper() for k in ("CH340", "CH343", "CP210", "FTDI", "STLINK", "ST-LINK", "XDS", "USB"))})
    except ImportError:
        pass
    can_sim = os.name != "nt" and (shutil.which("make") or any(sim_elf(a).exists() for a in SIM_APPS))
    if can_sim:
        for a in SIM_APPS:
            out.append({"port": SIM_PREFIX + a, "desc": f"仿真板 · {a}（host-sim，无需硬件）", "kind": "sim", "likely": False})
    return out


def explain_open_error(device: str, e: Exception) -> tuple[str, str]:
    """pyserial 的英文报错 → 给用户看的中文 (说明, 怎么办)。"""
    msg = str(e)
    low = msg.lower()
    if any(k in low for k in ("permission", "access is denied", "exclusively lock", "resource busy", "拒绝访问")):
        return (f"打不开 {device}：被别的程序占着",
                "关掉串口助手 / Keil·CCS 调试 / 另一个工作台窗口再连；Linux 还要把用户加入 dialout 组")
    if any(k in low for k in ("no such file", "could not find", "cannot find", "filenotfound", "系统找不到")):
        names = [p["port"] for p in list_ports() if p["kind"] == "serial"]
        return (f"找不到 {device}：线拔了，或者插到别的 USB 口后编号变了",
                "现在能看到的串口：" + ("、".join(names) if names else "（一个都没有，检查 USB 线和 CH340/CP210x 驱动）"))
    return f"打不开 {device}：{msg}", "拔插 USB 线；确认驱动（CH340/CP210x）已装"


def open_serial(device: str, baud: int, **kw):
    """POSIX 上独占打开（Windows 本来就独占）：两个窗口/程序抢同一个口时第二个直接报“被占用”，而不是两边都收到半截数据。"""
    import serial
    if os.name != "nt":
        kw.setdefault("exclusive", True)
    return serial.Serial(device, baud, **kw)


def identity(device: str) -> tuple | None:
    """USB 身份（VID, PID, 序列号）：线拔了插到别的口、Windows 换了 COM 号时，靠它找回同一块板。"""
    try:
        from serial.tools import list_ports as lp
        for p in lp.comports():
            if p.device == device and p.vid is not None:
                return (p.vid, p.pid, p.serial_number)
    except Exception:  # noqa: BLE001
        pass
    return None


def candidates(ident: tuple | None) -> list[str]:
    """和 ident 同 VID/PID 的口（序列号有就也要相同）。CH340 多数没有序列号：两块同型号板会都在这里。"""
    if not ident:
        return []
    out = []
    try:
        from serial.tools import list_ports as lp
        for p in lp.comports():
            if (p.vid, p.pid) == ident[:2] and (ident[2] is None or p.serial_number == ident[2]):
                out.append(p.device)
    except Exception:  # noqa: BLE001
        pass
    return out


def heartbeat_id(device: str, baud: int, listen_s: float = 0.8) -> tuple[int, int] | None:
    """只听不发：返回板子心跳里的 (schema_hash, board_uid)；打不开（被别的程序占着）/ 没心跳返回 None。"""
    from ._dzlink import HEARTBEAT
    try:
        s = open_serial(device, baud, timeout=0.05)
    except Exception:  # noqa: BLE001
        return None
    try:
        p, t0 = Parser(), time.monotonic()
        while time.monotonic() - t0 < listen_s:
            for kind, _id, _seq, pl in p.feed(s.read(256)):
                if kind == HEARTBEAT and len(pl) >= 4:
                    return (int.from_bytes(pl[:4], "little"), int.from_bytes(pl[4:8], "little") if len(pl) >= 8 else 0)
        return None
    finally:
        s.close()


def pick_moved(port: str, ident: tuple | None, uid: int | None, schema_hash: int | None, baud: int,
               cands: list[str] | None = None) -> tuple[str | None, str]:
    """线拔了插到别的口后找回“同一块板”。返回 (新口 | None, 为什么)。
    有板 ID（固件心跳带 board_uid）→ 只认 ID 相同的；没有 ID 但 USB 序列号唯一 → 认序列号；
    都没有时只剩一个候选、且 schema 一样才跟；两个以上同型号候选 → 不跟（宁可不连也不连错板）。"""
    cands = [c for c in (candidates(ident) if cands is None else cands) if c != port]
    if not cands:
        return None, "none"
    if uid:
        for c in cands:
            h = heartbeat_id(c, baud)
            if h and h[1] == uid:
                return c, "uid"
        return None, "none"
    if ident and ident[2] is not None and len(cands) == 1:
        return cands[0], "serial"
    if len(cands) == 1:
        h = heartbeat_id(cands[0], baud)
        return (cands[0], "schema") if h and h[0] == schema_hash else (None, "none")
    return None, "ambiguous"


class PortOpenError(Exception):
    """口根本打不开（不存在 / 被占用）：和“打开了但没有 dzframe”是两类问题，给用户的建议不同。"""
    def __init__(self, what: str, fix: str):
        super().__init__(what)
        self.what, self.fix = what, fix


def probe_baud(device: str, bauds=BAUDS, listen_s: float = 0.25) -> tuple[int | None, str]:
    """返回 (波特率, 说明)；没收到 dzframe 时波特率为 None、说明里给排查建议。口打不开抛 PortOpenError。"""
    try:
        s = open_serial(device, bauds[0], timeout=0.02)
    except Exception as e:  # noqa: BLE001
        raise PortOpenError(*explain_open_error(device, e)) from e
    try:
        for b in bauds:
            s.baudrate = b
            s.reset_input_buffer()
            p, t0 = Parser(), time.monotonic()
            while time.monotonic() - t0 < listen_s:
                if p.feed(s.read(256)):
                    return b, f"{b} 波特：收到合法 dzframe"
        return None, (f"{device} 在 {', '.join(map(str, bauds))} 下都没有收到 dzframe。"
                      "检查：板子是否上电并已烧录工作台固件；TX/RX 是否交叉；是否共地；LINK 串口是不是接的这个口。")
    finally:
        s.close()
