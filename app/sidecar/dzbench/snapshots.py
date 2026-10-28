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


def save(h: int, name: str, values: dict, note: str = "") -> pathlib.Path:
    safe = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", name).strip("_") or time.strftime("snap_%H%M%S")
    p = _dir(h) / f"{safe}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"name": safe, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note, "values": values},
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
            out.append({"name": j["name"], "time": j.get("time", ""), "note": j.get("note", ""), "values": j["values"]})
        except (ValueError, KeyError):
            continue
    return out


def load(h: int, name: str) -> dict:
    return json.loads((_dir(h) / f"{name}.json").read_text(encoding="utf-8"))["values"]
