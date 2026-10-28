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


def probe_baud(device: str, bauds=BAUDS, listen_s: float = 0.25) -> tuple[int | None, str]:
    """返回 (波特率, 说明)。找不到时说明里给出排查建议。"""
    import serial
    try:
        s = serial.Serial(device, bauds[0], timeout=0.02)
    except serial.SerialException as e:
        msg = str(e)
        if "Permission" in msg or "Access is denied" in msg or "拒绝访问" in msg:
            return None, f"打不开 {device}：被占用或没权限。关掉串口助手/Keil 调试/另一个工作台窗口再试；Linux 把用户加入 dialout 组。"
        return None, f"打不开 {device}：{msg}。拔插 USB 线、确认驱动（CH340/CP210x）已装。"
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
