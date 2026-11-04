#!/usr/bin/env python3
"""第 4.3 步 电源与电平检查：scheme.yaml（+ 可选 board.yaml）→ 内置 SKiDL 建网表 → SKiDL ERC + 本仓库规则 → 报告 + BOM。

  python3 tools/power_check.py <scheme.yaml> [--board board.yaml] [-o out/] [--json]

附加规则（通用，只看 tools/catalog/elec.yaml 与 scheme.yaml elec/power 的电气参数）：
  LEVEL_OVERVOLT  高电平驱动低电平输入且接收端不耐 5 V → 错误（要电平转换/分压）
  LEVEL_LOW_VIH   驱动电平 < 0.7×接收端电平（3.3 V 推 5 V CMOS）→ 警告
  LEVEL_BIDIR     双向线（I2C 等）两端电平不同 → 错误（要双向电平转换）
  RAIL_BUDGET     某供电轨负载电流 > 能力（3V3 由 5V 经 LDO 供，3V3 负载也计入 5V）→ 错误
退出码：0 通过 / 1 有错误（不满足）/ 2 参数错 / 3 缺依赖 / 10+ 内部错误。"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import logging
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import hwmodel as H  # noqa: E402

SKIDL = pathlib.Path(__file__).resolve().parents[1] / "third_party" / "vendored" / "skidl"


def level_rules(m: dict) -> list[dict]:
    dev = {d["id"]: d for d in m["devices"]}
    mv = dev[m["mcu"]]["elec"]
    out = []
    for w in m["wires"]:
        de = dev[w["dev"]]["elec"]
        pairs = {"out": [(mv, de)], "io": [(mv, de)], "in": [(de, mv)], "analog": [(de, mv)], "bidir": [(mv, de), (de, mv)]}[w["dir"]]
        tag = f"{w['type']}.{w['res']}（{m['mcu']}.{w['mcu_pin']} ↔ {w['dev']}.{w['dev_pin']}）"
        if w["dir"] == "bidir" and abs(mv["io_v"] - de["io_v"]) > 0.3 and not (mv.get("tol_5v") and de.get("tol_5v")):
            out.append({"code": "LEVEL_BIDIR", "sev": "error", "where": tag, "msg": f"双向线两端 {mv['io_v']} V / {de['io_v']} V，加双向电平转换（如 BSS138）"})
            continue
        for drv, rcv in pairs:
            if drv["io_v"] > rcv["io_v"] + 0.3 and not rcv.get("tol_5v"):
                out.append({"code": "LEVEL_OVERVOLT", "sev": "error", "where": tag, "msg": f"{drv['io_v']} V 驱动 {rcv['io_v']} V 不耐压输入，加分压/电平转换"})
            elif drv["io_v"] < 0.7 * rcv["io_v"]:
                out.append({"code": "LEVEL_LOW_VIH", "sev": "warn", "where": tag, "msg": f"{drv['io_v']} V 驱动 {rcv['io_v']} V 输入，可能达不到 VIH"})
    return out


def rail_rules(m: dict) -> tuple[list[dict], dict]:
    load = {r: 0 for r in m["rails"]}
    for d in m["devices"]:
        r = H.rail(d["elec"]["vcc"])
        load[r] = load.get(r, 0) + d["elec"]["ma"]
    if "5V" in load and "3V3" in load:
        load["5V"] += load["3V3"]
    out = [{"code": "RAIL_BUDGET", "sev": "error", "where": r, "msg": f"{r} 负载 {v} mA > 能力 {m['rails'].get(r, 0)} mA"}
           for r, v in load.items() if v > m["rails"].get(r, 0)]
    return out, load


def skidl_erc(m: dict) -> tuple[list[dict], list[dict]]:
    sys.path.insert(0, str(SKIDL))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
        logging.disable(logging.WARNING)
        import skidl as S
        logging.disable(logging.NOTSET)
        S.reset()
        S.set_default_tool(S.SKIDL)
        T = S.Pin.types
        dfun = {"out": T.OUTPUT, "in": T.INPUT, "io": T.BIDIR, "bidir": T.BIDIR, "analog": T.PASSIVE}
        rfun = {"out": T.INPUT, "in": T.OUTPUT, "io": T.BIDIR, "bidir": T.BIDIR, "analog": T.OUTPUT}
        nets, parts = {r: S.Net(r) for r in ("3V3", "5V", "GND")}, {}
        src = S.Part(name="SUPPLY", tool=S.SKIDL, dest=S.TEMPLATE, pins=[S.Pin(num=1, name="3V3", func=T.PWROUT), S.Pin(num=2, name="5V", func=T.PWROUT), S.Pin(num=3, name="GND", func=T.PWROUT)])()
        src.ref = "PS1"
        for r in ("3V3", "5V", "GND"):
            nets[r] += src[r]
        for i, d in enumerate(m["devices"]):
            ws = [w for w in m["wires"] if (w["dev"] == d["id"]) or d["kind"] == "mcu"]
            if d["kind"] == "mcu":
                pins = [S.Pin(num=k + 3, name=w["mcu_pin"], func=dfun[w["dir"]]) for k, w in enumerate({w["mcu_pin"]: w for w in ws}.values())]
            else:
                pins = [S.Pin(num=k + 3, name=w["dev_pin"], func=rfun[w["dir"]]) for k, w in enumerate(ws)]
            p = S.Part(name=d["id"], tool=S.SKIDL, dest=S.TEMPLATE, pins=[S.Pin(num=1, name="VCC", func=T.PWRIN), S.Pin(num=2, name="GND", func=T.PWRIN)] + pins)()
            p.ref = "U1" if d["kind"] == "mcu" else f"J{i}"
            p.value = d["name"]
            parts[d["id"]] = p
            nets[H.rail(d["elec"]["vcc"])] += p["VCC"]; nets["GND"] += p["GND"]
        for w in m["wires"]:
            n = S.Net(f"{w['type']}_{w['res']}_{w['dev_pin']}")
            n += parts[m["mcu"]][w["mcu_pin"]], parts[w["dev"]][w["dev_pin"]]
        S.erc_logger.error.reset() if hasattr(S.erc_logger.error, "reset") else None
        e0, w0 = S.erc_logger.error.count, S.erc_logger.warning.count
        S.ERC()
        ne, nw = S.erc_logger.error.count - e0, S.erc_logger.warning.count - w0
        bomrows = [{"ref": p.ref, "part": p.name, "value": p.value, "qty": 1} for p in [src] + list(parts.values())]
    lines = [ln for ln in buf.getvalue().splitlines() if ln.startswith("ERC ") and "found while running" not in ln]
    found = [{"code": "SKIDL_ERC", "sev": "error" if "ERROR" in ln[:10] else "warn", "where": "netlist", "msg": ln} for ln in lines]
    if not lines and (ne or nw):
        found = [{"code": "SKIDL_ERC", "sev": "error", "where": "netlist", "msg": f"SKiDL ERC {ne} errors"}] * bool(ne)
    return found, bomrows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scheme"); ap.add_argument("--board"); ap.add_argument("-o"); ap.add_argument("--json", action="store_true")
    try:
        ns = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        m = H.load(ns.scheme, ns.board)
    except (OSError, KeyError, yaml.YAMLError, ValueError) as e:
        return H.emit(ns, {"error": f"读不了方案/板：{e}"}, 2, f"✗ 读不了方案/板：{e}")
    try:
        erc, bomrows = skidl_erc(m)
    except ImportError as e:
        return H.emit(ns, {"error": f"缺依赖：{e}（pip install -r tools/requirements-hw.txt）"}, 3, f"✗ 缺依赖：{e}")
    rails, load = rail_rules(m)
    issues = erc + level_rules(m) + rails
    errs = [i for i in issues if i["sev"] == "error"]
    files = {}
    if ns.o:
        o = pathlib.Path(ns.o); o.mkdir(parents=True, exist_ok=True)
        with (o / "power_bom.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["ref", "part", "value", "qty"]); w.writeheader(); w.writerows(bomrows)
        (o / "power_check.yaml").write_text(yaml.safe_dump({"rails": m["rails"], "load_ma": load, "issues": issues}, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
        files = {"bom_csv": str(o / "power_bom.csv"), "report": str(o / "power_check.yaml")}
    code = 1 if errs else 0
    human = "\n".join([f"{'✗' if i['sev'] == 'error' else '!'} [{i['code']}] {i['where']}：{i['msg']}" for i in issues]
                      + [f"{'✗' if errs else '✓'} 电源/电平：错误 {len(errs)}，警告 {len(issues) - len(errs)}；负载 {load} mA"])
    return H.emit(ns, {"issues": issues, "load_ma": load, "rails": m["rails"], "bom": bomrows, "files": files}, code, human)


if __name__ == "__main__":
    sys.exit(main())
