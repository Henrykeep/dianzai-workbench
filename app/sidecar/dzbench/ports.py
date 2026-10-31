"""列出可用端口，自动探测波特率：每个候选波特率听一小段，看能不能解出合法 dzframe。"""
from __future__ import annotations

import os
import re
import shutil
import time

from ._dzlink import Parser
from .transport import SIM_PREFIX, sim_elf, sim_root

# 先试工作台各板默认值（board.yaml 里 LINK 常用），再试常见值
BAUDS = [460800, 921600, 115200, 230400, 1000000, 500000, 57600, 9600]


def _yaml_top(y) -> dict:
    """app.yaml / project.yaml 顶层键（只看 key: 开头的行，name 取值）。"""
    keys: dict = {}
    for ln in y.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if m:
            keys[m.group(1)] = m.group(2).split("#", 1)[0].strip().strip("\"'")
    return keys


def _sim_dirs():
    from . import paths
    for d in (sim_root() / "apps", sim_root() / "examples", paths.projects_dir()):
        if d.is_dir():
            yield from (a for a in sorted(d.iterdir()) if a.is_dir())


def sim_app_info() -> dict[str, dict]:
    """能当仿真板的应用 → {"name": 应用显示名}。条件（不写死题目名单）：
    有 sim_setup.c 且声明了 link:；或 #100：app.yaml / project.yaml 只声明了 plant:（通用对象板由 plantgen 生成）。"""
    found: dict[str, dict] = {}
    for a in _sim_dirs():
        tops = [_yaml_top(y) for y in (a / "app.yaml", a / "project.yaml") if y.exists()]
        if not tops or a.name in found:
            continue
        has_link = any("link" in t for t in tops) and any(a.rglob("sim_setup.c"))
        has_plant = any("plant" in t for t in tops)
        if has_link or has_plant:
            found[a.name] = {"name": next((t["name"] for t in tops if t.get("name")), "") or a.name, "dir": str(a.resolve())}
    if not found:   # 安装包里没有源码树：只列已经编好的
        hs = sim_root() / "build" / "host-sim"
        found = {p.name: {"name": p.name, "dir": None} for p in sorted(hs.iterdir()) if sim_elf(p.name).exists()} if hs.is_dir() else {}
    return found


def sim_apps() -> list[str]:
    return list(sim_app_info())


SIM_APPS = sim_apps()


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
    global SIM_APPS
    info = sim_app_info()                     # #100：每次列端口都重扫（新建项目不用重启侧车）
    SIM_APPS = list(info)
    can_sim = (os.name != "nt" and shutil.which("make")) or any(sim_elf(a).exists() for a in SIM_APPS)   # 安装包自带编好的仿真板
    if can_sim:
        for a in SIM_APPS:
            nm = info[a]["name"]
            out.append({"port": SIM_PREFIX + a, "app": a, "app_name": nm, "app_dir": info[a].get("dir"), "label": f"仿真 · {nm}",
                        "desc": f"仿真板 · {nm}（host-sim，无需硬件）", "kind": "sim", "likely": False})
        for a in SIM_APPS:
            nm = info[a]["name"]
            out.append({"port": SIM_PREFIX + a + "+hw", "app": a, "app_name": nm, "app_dir": info[a].get("dir"), "label": f"仿真当实板 · {nm}",
                        "desc": f"仿真板当实板 · {nm}（测确认卡 / pre-arm，实验要人点执行）", "kind": "sim", "likely": False})
    out += rtt_ports()
    return out


def rtt_ports() -> list[dict]:
    """装了 pyOCD（含 RTT）且配置了 flash.target 时，列一个 rtt:<目标>（经调试探针收发，不占串口）。"""
    try:
        import importlib.util
        if importlib.util.find_spec("pyocd") is None or importlib.util.find_spec("pyocd.debug.rtt") is None:
            return []
        from . import config
        f = config.load().get("flash") or {}
    except Exception:  # noqa: BLE001
        return []
    if not f.get("target"):
        return []
    spec = f["target"] + (f"@{f['probe']}" if f.get("probe") else "")
    return [{"port": "rtt:" + spec, "desc": f"RTT · {f['target']}（调试探针；固件要用 make LINK=rtt 编）", "kind": "rtt", "likely": False}]


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


LINES: dict = {}      # 运行时覆盖（server 的 serial_lines 操作）；空 = 读配置 serial.dtr / serial.rts


def line_settings() -> dict:
    """DTR/RTS：None = 不动（驱动默认，pyserial 打开时置高），True/False = 打开前就设好。
    ESP32 / 带自动下载电路的 CH340 板：DTR/RTS 一动就复位或进 BOOT，一般要设 False。"""
    if LINES:
        return dict(LINES)
    try:
        from . import config
        sec = config.load().get("serial") or {}
    except Exception:  # noqa: BLE001
        sec = {}
    return {k: sec.get(k) for k in ("dtr", "rts")}


def open_serial(device: str, baud: int, **kw):
    """POSIX 上独占打开（Windows 本来就独占）：两个窗口/程序抢同一个口时第二个直接报“被占用”，而不是两边都收到半截数据。
    DTR/RTS 在 open() 之前设好，避免打开瞬间的电平跳变把板子复位。"""
    import serial
    if os.name != "nt":
        kw.setdefault("exclusive", True)
    lines = {k: v for k, v in line_settings().items() if v is not None}
    if not lines:
        return serial.Serial(device, baud, **kw)
    s = serial.Serial(None, baud, **kw)
    s.port = device
    for k, v in lines.items():
        setattr(s, k, bool(v))
    s.open()
    return s


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
