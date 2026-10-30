"""导入别的工具的曲线记录（缺口 13）：CSV（本工作台导出的 / Excel / SerialPlot / PlotJuggler）和 VOFA+ FireWater 文本。
做法：转成一份 .dzlog，每个样本写成一行 `名字=值,…` 的“收到”记录，时间戳照原样 → 回放走现有文本遥测路径（textparse），
导入的记录可以和真记录一样回放、拖时间轴、再导出。
FireWater 格式（VOFA+ 文档）：每行 `[可选前缀:]v1,v2,…\\n`；没有名字，通道叫 ch1、ch2…（VOFA+ 里默认 I1、I2…）。
思路参考 SerialWeb（文本模板解析、CSV 导出）与 VOFA+ FireWater 协议说明；代码自写。
"""
from __future__ import annotations

import csv
import io
import json
import pathlib
import re
import time

from .logfile import MAGIC, REC, RX

from .textparse import FIREWATER, _NUM as NUM
TIME_COLS = ("t_s", "time", "t", "timestamp", "时间", "time_s")
MAX_COLS = 16
_UNIT = re.compile(r"\[[^\]]*\]$")
_NAME = re.compile(r"[^\w]")


class ImportError_(Exception):
    def __init__(self, message: str, fix: str = ""):
        super().__init__(message); self.message, self.fix = message, fix


def _clean(h: str, k: int) -> str:
    n = _NAME.sub("_", _UNIT.sub("", h.strip())).strip("_")[:24]
    return n if n and not n[0].isdigit() else f"ch{k + 1}"


def _read_text(p: pathlib.Path) -> str:
    b = p.read_bytes()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "replace")


def parse(path, period_ms: float = 10.0) -> tuple[list[str], list[tuple[float, list[float]]], str]:
    """→ (通道名, [(t_s, 值…)], 格式)。没有时间列时按 period_ms 等间隔排。"""
    p = pathlib.Path(path)
    text = _read_text(p)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ImportError_(f"{p.name} 是空文件")
    first = lines[0]
    fw = FIREWATER.match(first) or ("," not in first and any(FIREWATER.match(x) for x in lines[1:20]))
    if fw:                                                          # VOFA FireWater / 无表头 CSV（开头的启动日志文字跳过）
        rows, n = [], 0
        for ln in lines:
            m = FIREWATER.match(ln)
            if not m:
                continue                                            # FireWater 里夹的日志文字跳过
            v = [float(x) for x in m.group(1).split(",")][:MAX_COLS]
            n = max(n, len(v)); rows.append(v)
        names = [f"ch{k + 1}" for k in range(n)]
        dt = period_ms / 1000.0
        return names, [(k * dt, r + [float("nan")] * (n - len(r))) for k, r in enumerate(rows)], "vofa"
    head = next(csv.reader([first]))
    rd = csv.reader(io.StringIO("\n".join(lines[1:])))
    tcol = next((k for k, h in enumerate(head) if _UNIT.sub("", h.strip()).lower() in TIME_COLS), None)
    body = list(rd)
    keep = []                                                       # 数值列（文字列如 state_txt 跳过）
    for k, h in enumerate(head):
        if k == tcol:
            continue
        vals = [r[k] for r in body[:50] if k < len(r) and r[k].strip()]
        if vals and all(re.fullmatch(NUM, x.strip()) for x in vals):
            keep.append(k)
    if not keep:
        raise ImportError_(f"{p.name} 里没有数值列", "CSV 第一行写列名，下面每行一个样本")
    keep = keep[:MAX_COLS]
    names, seen = [], set()
    for k in keep:
        n = _clean(head[k], k)
        while n in seen:
            n += "_"
        seen.add(n); names.append(n)
    rows = []
    for i, r in enumerate(body):
        try:
            t = float(r[tcol]) if tcol is not None else i * period_ms / 1000.0
        except (ValueError, IndexError):
            continue
        v = []
        for k in keep:
            try:
                v.append(float(r[k]))
            except (ValueError, IndexError):
                v.append(float("nan"))
        rows.append((t, v))
    if tcol is not None and rows and rows[-1][0] > 1e5:             # 毫秒 / 时间戳：换成从 0 开始的秒
        t0 = rows[0][0]
        scale = 1e-3 if (rows[-1][0] - t0) / max(len(rows), 1) > 0.5 else 1.0
        rows = [((t - t0) * scale, v) for t, v in rows]
    return names, rows, "csv"


def import_to_dzlog(path, out_dir, period_ms: float = 10.0) -> dict:
    names, rows, fmt = parse(path, period_ms)
    if not rows:
        raise ImportError_("没解析出样本")
    src = pathlib.Path(path)
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"import_{time.strftime('%Y%m%d_%H%M%S')}_{_NAME.sub('_', src.stem)[:32]}.dzlog"
    t0 = rows[0][0]
    hdr = {"port": f"import:{src.name}", "baud": 0, "start": time.strftime("%Y-%m-%d %H:%M:%S"), "schema_hash": None,
           "imported": {"from": str(src), "fmt": fmt, "rows": len(rows)}}
    with open(out, "wb") as f:
        f.write(MAGIC + json.dumps(hdr, ensure_ascii=False).encode() + b"\n")
        for t, v in rows:
            ln = ",".join(f"{n}={x:.9g}" for n, x in zip(names, v) if x == x).encode() + b"\n"   # NaN 不写
            f.write(REC.pack(max(t - t0, 0.0), RX, len(ln)) + ln)
    return {"path": str(out), "rows": len(rows), "channels": names, "fmt": fmt, "seconds": round(rows[-1][0] - t0, 3)}
