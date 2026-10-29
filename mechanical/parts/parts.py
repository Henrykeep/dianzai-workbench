#!/usr/bin/env python3
"""参数化零件库（CadQuery，可选依赖）：导出 STEP（SolidWorks 打开/装配）+ STL（Bambu Studio 切片）。

  pip install cadquery                       # 可选；没装时本脚本打印跳过并退出 0
  python3 mechanical/parts/parts.py --list
  python3 mechanical/parts/parts.py motor_mount -o out/ --set motor_d=25 --set wall=4
  python3 mechanical/parts/parts.py all -o out/

每个零件 = 一个函数 + 一张默认参数表 PARAMS[名]（单位 mm）。默认值是常见 37 mm 减速电机 / 小编码器板 / 灰度传感器板的**示例**，
装前用卡尺量你的件再 --set 覆盖。STEP/STL 是派生产物：改参数重新导出，别手改网格。
与 SolidWorks 的关系：这里是“能直接打印的起点”；要精修就把 STEP 导入 SolidWorks（mechanical/README 的 .SLDPRT 主线不变）。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

try:
    import cadquery as cq
except ImportError:          # 可选依赖：没装就跳过，不影响仓库其他部分
    cq = None

PARAMS = {
    "motor_mount": {  # L 形电机座：竖板夹电机法兰，底板螺丝固定到车板
        "motor_d": 37.0, "boss_d": 12.5, "screw_pcd": 31.0, "screw_n": 6, "screw_d": 3.2,
        "wall": 4.0, "base_len": 30.0, "base_slot_d": 3.4, "base_slot_len": 6.0, "fillet": 2.0,
    },
    "encoder_bracket": {  # 平板：中心过轴孔 + 编码器板两个安装孔 + 两个固定孔
        "w": 40.0, "h": 30.0, "t": 3.0, "shaft_hole_d": 8.0, "pcb_hole_d": 2.2, "pcb_hole_dx": 24.0,
        "mount_hole_d": 3.2, "mount_hole_dy": 22.0, "mount_hole_x": -14.0,
    },
    "sensor_bracket": {  # 灰度/红外传感器板支架：底板固定 + 竖板长条孔调离地高度
        "pcb_w": 60.0, "wall": 3.0, "drop": 25.0, "base_len": 20.0, "slot_w": 3.4, "slot_len": 12.0,
        "slot_dx": 40.0, "base_hole_d": 3.2, "base_hole_dx": 40.0,
    },
}


def motor_mount(p):
    d = p["motor_d"] + 2 * p["wall"]
    face = (cq.Workplane("XZ").rect(d, d).extrude(-p["wall"])          # 竖板（法兰面），法向 +Y
            .faces(">Y").workplane().hole(p["boss_d"])
            .faces(">Y").workplane().polygon(p["screw_n"], p["screw_pcd"], forConstruction=True).vertices().hole(p["screw_d"]))
    face = face.translate((0, 0, d / 2))
    base = (cq.Workplane("XY").box(d, p["base_len"], p["wall"], centered=(True, False, False))
            .faces(">Z").workplane().pushPoints([(-d / 3, p["base_len"] / 2), (d / 3, p["base_len"] / 2)])
            .slot2D(p["base_slot_len"] + p["base_slot_d"], p["base_slot_d"], 90).cutThruAll())
    body = face.union(base)
    try:
        body = body.edges("|X and <Z and >Y").fillet(p["fillet"]) if p["fillet"] > 0 else body
    except Exception:  # noqa: BLE001  倒角失败不影响可用性
        pass
    return body


def encoder_bracket(p):
    return (cq.Workplane("XY").box(p["w"], p["h"], p["t"])
            .faces(">Z").workplane().hole(p["shaft_hole_d"])
            .faces(">Z").workplane().pushPoints([(-p["pcb_hole_dx"] / 2, 0), (p["pcb_hole_dx"] / 2, 0)]).hole(p["pcb_hole_d"])
            .faces(">Z").workplane().pushPoints([(p["mount_hole_x"], -p["mount_hole_dy"] / 2), (p["mount_hole_x"], p["mount_hole_dy"] / 2)])
            .hole(p["mount_hole_d"]))


def sensor_bracket(p):
    w, t = p["pcb_w"], p["wall"]
    base = (cq.Workplane("XY").box(w, p["base_len"], t, centered=(True, False, False))
            .faces(">Z").workplane().pushPoints([(-p["base_hole_dx"] / 2, p["base_len"] / 2), (p["base_hole_dx"] / 2, p["base_len"] / 2)])
            .hole(p["base_hole_d"]))
    drop = (cq.Workplane("XZ").center(0, -p["drop"] / 2 + t).rect(w, p["drop"]).extrude(t)
            .faces("<Y").workplane().pushPoints([(-p["slot_dx"] / 2, -p["drop"] / 2 + t), (p["slot_dx"] / 2, -p["drop"] / 2 + t)])
            .slot2D(p["slot_len"], p["slot_w"], 90).cutThruAll())
    return base.union(drop)


BUILD = {"motor_mount": motor_mount, "encoder_bracket": encoder_bracket, "sensor_bracket": sensor_bracket}


def build(name: str, over: dict | None = None):
    p = {**PARAMS[name], **(over or {})}
    return BUILD[name](p), p


def export(name: str, out: pathlib.Path, over: dict | None = None) -> list[pathlib.Path]:
    wp, p = build(name, over)
    out.mkdir(parents=True, exist_ok=True)
    step, stl = out / f"{name}.step", out / f"{name}.stl"
    cq.exporters.export(wp, str(step))
    cq.exporters.export(wp, str(stl), tolerance=0.05, angularTolerance=0.2)
    (out / f"{name}.params.txt").write_text("".join(f"{k} = {v}\n" for k, v in p.items()), encoding="utf-8", newline="\n")
    return [step, stl]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("part", nargs="?", default="all"); ap.add_argument("-o", default="out")
    ap.add_argument("--set", action="append", default=[], metavar="k=v"); ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        for k, v in PARAMS.items():
            print(k, " ".join(f"{x}={y:g}" for x, y in v.items()))
        return 0
    if cq is None:
        print("跳过：没装 CadQuery（可选依赖，pip install cadquery）")
        return 0
    over = {k: float(v) for k, v in (s.split("=", 1) for s in a.set)}
    for n in (PARAMS if a.part == "all" else [a.part]):
        for f in export(n, pathlib.Path(a.o), {k: v for k, v in over.items() if k in PARAMS[n]}):
            print("写入", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
