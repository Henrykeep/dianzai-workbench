#!/usr/bin/env python3
"""第 3.3/4.2 步 接线表 + 接线图 + BOM：scheme.yaml（+ 可选 alloc 出的 board.yaml）→ WireViz YAML → 内置 WireViz 出 SVG/PNG/TSV。

  python3 tools/gen_wiring.py <scheme.yaml> [--board board.yaml] -o out/ [--json] [--no-render]

输出：out/wiring.yml（WireViz 输入）、wiring.svg、wiring.png、wiring.bom.tsv、bom.csv、wiring.csv（逐线接线表）。
退出码：0 成功 / 2 参数错 / 3 缺依赖（Graphviz dot、graphviz 包）/ 10+ 内部错误。
WireViz（GPL-3.0）放在 tools/vendor_gpl/wireviz，按原样以独立进程调用。"""
from __future__ import annotations

import argparse
import csv
import os
import pathlib
import shutil
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import hwmodel as H  # noqa: E402

WV = pathlib.Path(__file__).resolve().parent / "vendor_gpl" / "wireviz"
COLORS = ["BK", "RD", "OG", "YE", "GN", "BU", "VT", "GY", "WH", "BN", "PK", "TQ"]


def to_wireviz(m: dict) -> dict:
    refs = {d["id"]: ("U1" if d["kind"] == "mcu" else f"J{i}") for i, d in enumerate(m["devices"])}
    mcu = m["mcu"]
    mpins = sorted({w["mcu_pin"] for w in m["wires"]}) + ["3V3", "5V", "GND"]
    conns = {refs[mcu]: {"type": m.get("mcu_part") or mcu, "subtype": "主控", "pinlabels": mpins}}
    cables, links = {}, []
    for d in m["devices"]:
        if d["kind"] == "mcu":
            continue
        r = refs[d["id"]]
        r_v = H.rail(d["elec"]["vcc"])
        pins = d["pins"] + ["VCC", "GND"]
        conns[r] = {"type": d["name"], "subtype": d["id"], "pinlabels": pins}
        ws = [w for w in m["wires"] if w["dev"] == d["id"]]
        c = f"W{r}"
        n = len(ws) + 2
        cables[c] = {"wirecount": n, "colors": [COLORS[i % len(COLORS)] for i in range(n)], "category": "bundle"}
        links.append([{refs[mcu]: [w["mcu_pin"] for w in ws] + [r_v, "GND"]}, {c: list(range(1, n + 1))},
                      {r: [w["dev_pin"] for w in ws] + ["VCC", "GND"]}])
    return {"connectors": conns, "cables": cables, "connections": links}


def table(m: dict) -> list[dict]:
    rows = []
    for d in m["devices"]:
        if d["kind"] == "mcu":
            continue
        for w in [w for w in m["wires"] if w["dev"] == d["id"]]:
            rows.append({"from": f"{m['mcu']}.{w['mcu_pin']}", "to": f"{d['id']}.{w['dev_pin']}", "signal": f"{w['type']}.{w['res']}", "dir": w["dir"]})
        rows.append({"from": f"{m['mcu']}.{H.rail(d['elec']['vcc'])}", "to": f"{d['id']}.VCC", "signal": "power", "dir": "pwr"})
        rows.append({"from": f"{m['mcu']}.GND", "to": f"{d['id']}.GND", "signal": "ground", "dir": "pwr"})
    return rows


def bom(m: dict) -> list[dict]:
    out = [{"item": i + 1, "ref": "U1" if d["kind"] == "mcu" else f"J{i}", "id": d["id"], "name": d["name"], "kind": d["kind"], "qty": 1,
            "vcc_v": d["elec"]["vcc"], "ma": d["elec"]["ma"]} for i, d in enumerate(m["devices"])]
    nw = len(table(m))
    out.append({"item": len(out) + 1, "ref": "W*", "id": "dupont", "name": "杜邦线 / 排线（每根一个信号）", "kind": "wire", "qty": nw, "vcc_v": "", "ma": ""})
    return out


def write_csv(p: pathlib.Path, rows: list[dict]):
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["empty"])
        w.writeheader(); w.writerows(rows)


def render(yml: pathlib.Path) -> tuple[int, str]:
    if not shutil.which("dot"):
        return 3, "缺 Graphviz（dot 命令）：Windows 装 graphviz.org 安装包并加入 PATH；Linux apt install graphviz"
    try:
        import graphviz  # noqa: F401
    except ImportError:
        return 3, "缺 Python 包 graphviz：pip install -r tools/requirements-hw.txt"
    env = dict(os.environ, PYTHONPATH=str(WV) + os.pathsep + os.environ.get("PYTHONPATH", ""), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "wireviz.wv_cli", "-f", "spt", str(yml)], capture_output=True, text=True, env=env, encoding="utf-8")
    if r.returncode:
        return 10, (r.stderr or r.stdout)[-800:]
    return 0, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scheme"); ap.add_argument("--board"); ap.add_argument("-o", required=True)
    ap.add_argument("--json", action="store_true"); ap.add_argument("--no-render", action="store_true", help="只出 YAML/CSV，不调 Graphviz")
    try:
        ns = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        m = H.load(ns.scheme, ns.board)
    except (OSError, KeyError, yaml.YAMLError, ValueError) as e:
        return H.emit(ns, {"error": f"读不了方案/板：{e}"}, 2, f"✗ 读不了方案/板：{e}")
    o = pathlib.Path(ns.o); o.mkdir(parents=True, exist_ok=True)
    yml = o / "wiring.yml"
    yml.write_text(yaml.safe_dump(to_wireviz(m), allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    write_csv(o / "wiring.csv", table(m)); write_csv(o / "bom.csv", bom(m))
    files = {"yaml": str(yml), "wiring_csv": str(o / "wiring.csv"), "bom_csv": str(o / "bom.csv")}
    code, msg = (0, "") if ns.no_render else render(yml)
    if code == 0 and not ns.no_render:
        files.update(svg=str(o / "wiring.svg"), png=str(o / "wiring.png"), bom_tsv=str(o / "wiring.bom.tsv"))
    pay = {"files": files, "devices": len(m["devices"]), "wires": len(table(m))}
    if msg:
        pay["error"] = msg
    return H.emit(ns, pay, code, ("✓ " if code == 0 else "✗ ") + (msg or f"接线 {pay['wires']} 根、器件 {pay['devices']} 个 → {o}"))


if __name__ == "__main__":
    sys.exit(main())
