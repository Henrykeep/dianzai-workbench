#!/usr/bin/env python3
"""硬件模型（第 3/4 步共用）：scheme.yaml（+ 可选 board.yaml）→ 器件、信号线、供电。
gen_wiring.py（WireViz 接线表/图 + BOM）与 power_check.py（SKiDL ERC + 电平/电流规则）都从这里取，不各写一套。
通用：只读器件库 res + 分配结果，不认任何题目。"""
from __future__ import annotations

import json
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import alloc as A  # noqa: E402
import scheme as sch  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
# 资源字段 → (MCU 侧方向, 器件侧脚名)
PIN_KEYS = {"pin": ("io", "SIG"), "pin_a": ("in", "A"), "pin_b": ("in", "B"), "tx": ("out", "RX"), "rx": ("in", "TX"),
            "scl": ("bidir", "SCL"), "sda": ("bidir", "SDA"), "sck": ("out", "SCK"), "mosi": ("out", "MOSI"),
            "miso": ("in", "MISO"), "cs": ("out", "CS")}
EXIT = {"ok": 0, "spec": 1, "args": 2, "dep": 3, "board": 4, "confirm": 5, "internal": 10}


def rail(v: float) -> str:
    return "5V" if v > 4 else "3V3"


def elec_table() -> dict:
    return yaml.safe_load((ROOT / "tools/catalog/elec.yaml").read_text(encoding="utf-8"))


def build(scheme: dict, board: dict | None = None, parts: dict | None = None) -> dict:
    parts = parts or sch.load_catalog()
    et = elec_table()
    over = scheme.get("elec") or {}
    def elec(pid):
        p = parts.get(pid, {})
        e = dict(et["kinds"].get(p.get("kind", "sensor"), et["kinds"]["sensor"]))
        e.update(et.get("parts", {}).get(pid, {})); e.update(over.get(pid, {}))
        return e
    if board is None:
        board, _, extra = A.allocate(scheme, parts, None, "hw", None)
        ds = extra["ds"]
    else:
        ds = A.demands(scheme, parts)
    owner = {(d["type"], d["name"]): d["part"] for d in ds}
    mid = scheme["mcu"]
    devs = {mid: {"id": mid, "name": parts.get(mid, {}).get("name", mid), "kind": "mcu", "elec": elec(mid), "pins": []}}
    wires = []
    for t, rs in (board.get("resources") or {}).items():
        for r in rs or []:
            pid = owner.get((t, r["name"]), "调试链路（工作台）")
            if pid not in devs:
                devs[pid] = {"id": pid, "name": parts.get(pid, {}).get("name", pid), "kind": parts.get(pid, {}).get("kind", "link"),
                             "elec": elec(pid) if pid in parts else dict(et["kinds"]["link"]), "pins": []}
            for k, (d, side) in PIN_KEYS.items():
                if k not in r:
                    continue
                if k == "pin":
                    d = {"pwm": "out", "adc": "analog"}.get(t, r.get("dir", "out") if t == "gpio" else "io")
                    if t == "gpio":
                        d = "in" if r.get("dir") == "in" else "out"
                ppin = f"{r['name']}_{side}"
                devs[pid]["pins"].append(ppin)
                wires.append({"type": t, "res": r["name"], "mcu_pin": r[k], "dir": d, "dev": pid, "dev_pin": ppin})
    rails = dict(et["rails"]); rails.update(((scheme.get("power") or {}).get("rails") or {}))
    return {"mcu": mid, "mcu_part": (board.get("mcu") or {}).get("part"), "devices": list(devs.values()), "wires": wires, "rails": rails}


def load(scheme_path: str, board_path: str | None):
    s = yaml.safe_load(pathlib.Path(scheme_path).read_text(encoding="utf-8"))
    b = yaml.safe_load(pathlib.Path(board_path).read_text(encoding="utf-8")) if board_path else None
    return build(s, b)


def emit(ns, payload: dict, code: int, human: str) -> int:
    payload = {"ok": code == 0, "exit": code, **payload}
    print(json.dumps(payload, ensure_ascii=False, indent=1) if ns.json else human)
    return code
