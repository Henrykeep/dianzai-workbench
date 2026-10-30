"""参数快照：比赛现场“这组好用，先存下”→ 一键恢复。按 schema 哈希分目录，换固件不会串。"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time


def base_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DZBENCH_HOME", pathlib.Path.home() / ".dzbench"))


def _dir(h: int) -> pathlib.Path:
    return base_dir() / "snapshots" / f"{h:08X}"


def save(h: int, name: str, values: dict, note: str = "", mode: str = "") -> pathlib.Path:
    """mode：环模式标签（speed / position / 空），只用来在列表里区分预设，固件不读。"""
    safe = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", name).strip("_") or time.strftime("snap_%H%M%S")
    p = _dir(h) / f"{safe}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"name": safe, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note, "mode": mode, "values": values},
                            ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def list_all(h: int) -> list[dict]:
    d = _dir(h)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
            out.append({"name": j["name"], "time": j.get("time", ""), "note": j.get("note", ""), "mode": j.get("mode", ""), "values": j["values"]})
        except (ValueError, KeyError):
            continue
    return out


def load(h: int, name: str) -> dict:
    return json.loads((_dir(h) / f"{name}.json").read_text(encoding="utf-8"))["values"]


MODES = {"": "", "speed": "速度环", "position": "位置环"}


def ramp_plan(cur: dict, target: dict, steps: int) -> list[dict]:
    """平滑切换预设：从 cur 线性插值到 target，分 steps 步，每步只含“本步要变的参数”；最后一步恰好等于 target。
    缺当前值的参数（还没读回）直接在最后一步写目标值。交互形态借鉴了 PID_Helper（GPL-3.0）的公开界面（草稿 / 生效值分离），未参考或复制其源码；逐步过渡为自写。"""
    steps = max(1, int(steps))
    out, prev = [], dict(cur)
    for k in range(1, steps + 1):
        a = k / steps
        st = {}
        for n, v in target.items():
            c = cur.get(n)
            x = float(v) if (c is None or k == steps) else float(c) + (float(v) - float(c)) * a
            if prev.get(n) != x:
                st[n] = x
                prev[n] = x
        if st:
            out.append(st)
    return out
