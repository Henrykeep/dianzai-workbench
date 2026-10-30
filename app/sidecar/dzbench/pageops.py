"""页面操作的唯一实现：标定页（极性自检）、联调页（频谱 / 波形测量）。侧车 op 和内置 Agent 工具都调这里，不各写一份。"""
from __future__ import annotations

from .spectrum import spectrum
from .wavemeas import measure_window


def _period(s) -> float | None:
    sch = s.schema
    return ((sch.d["telemetry"].get("period_ms") or 0) / 1000 if sch else 0) or None


def polarity_check(s, m: dict) -> dict:
    """标定向导第 0 步：只读遥测窗口判方向（agent/polarity.py）。"""
    from .agent import polarity
    secs = float(m.get("seconds", 3.0))
    names = [n for n in (m["y"], m.get("e"), m.get("u")) if n]
    win = {n: s.window_field(n, secs) for n in names}
    r = polarity.check_window(win, m["step"], y=m["y"], e=m.get("e"), u=m.get("u"),
                              pushed_dir=int(m.get("pushed_dir", 1)), u_min=float(m.get("u_min", 0.0)))
    if "signs" in m:                 # 前端把 push/jog 两步的结果攒齐后再要结论
        g = m["signs"]
        r["verdict"] = polarity.verdict(g.get("sensor", 0), g.get("err", 0), g.get("ctrl", 0), g.get("act", 0))
    return r


def fft(s, m: dict) -> dict:
    name = m["field"]
    t, y = s.window_field(name, float(m.get("seconds", 30)))
    return spectrum(t, y, _period(s)) | {"field": name}


def wave_measure(s, m: dict) -> dict:
    name, secs = m["field"], float(m.get("seconds", 10))
    t, y = s.window_field(name, secs)
    ref = None
    if m.get("ref"):
        tr, ref = s.window_field(m["ref"], secs)
        k = min(len(y), len(ref))                   # 同一遥测帧里的两个字段 = 同批采样
        t, y, ref = t[-k:], y[-k:], ref[-k:]
    return measure_window(t, y, _period(s), ref) | {"field": name, "ref": m.get("ref")}
