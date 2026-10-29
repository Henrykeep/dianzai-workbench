#!/usr/bin/env python3
"""gen_link.py —— 由 yaml 的 `link:` 段生成上位机链路代码与 schema（C 与桌面工作台同源）。

输入（app.yaml 或 project.yaml）：
  link:
    telemetry: { id: 2, period_ms: 20, fields: [ { name: t_ms, type: uint32, unit: ms }, ... ] }
    params:    [ { name: kp, type: float, default: 0.08, min: 0, max: 2, unit: "", desc: "" } ]   # 仅 app.yaml
  project.yaml 不写 link.params：直接用顶层 params（params_t，需带 min/max），生效的是当前参数档。

输出（-o 目录）：
  link_gen.h / link_gen.c   link_telem_t + link_telem_pack()、参数描述表 g_link_param_desc[]、LINK_SCHEMA_HASH
  link_schema.json          桌面工作台用：遥测字段、参数（含默认值/限幅/单位/说明）、哈希
哈希 = FNV-1a 32 位，算在规范化 JSON（不含 desc/default）上：字段或限幅一变，上位机就知道 schema 不匹配。

用法：gen_link.py <yaml> -o <目录>    |    gen_link.py --selftest
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import yaml

C_TYPES = {"float": ("float", "DZCTL_F32", "f32"), "uint32": ("uint32_t", "DZCTL_U32", "u32"),
           "int32": ("int32_t", "DZCTL_I32", "u32"), "uint16": ("uint16_t", "DZCTL_U16", "u16"),
           "int16": ("int16_t", "DZCTL_I16", "u16"), "uint8": ("uint8_t", "DZCTL_U8", "u8"),
           "bool": ("bool", "DZCTL_BOOL", "u8")}
WIRE = {"float": "f32", "uint32": "u32", "int32": "i32", "uint16": "u16", "int16": "i16", "uint8": "u8", "bool": "u8"}
TYPE_MAX = {"uint32": (0, 4294967295), "int32": (-2147483648, 2147483647), "uint16": (0, 65535),
            "int16": (-32768, 32767), "uint8": (0, 255), "bool": (0, 1)}


def fnv1a(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def check(spec: dict, params: list) -> list[str]:
    errs = []
    tel = spec.get("telemetry") or {}
    size = 0
    for f in tel.get("fields", []):
        if f.get("type") not in C_TYPES:
            errs.append(f"telemetry.{f.get('name')}: 类型 {f.get('type')} 不支持（{', '.join(C_TYPES)}）")
        else:
            size += {"f32": 4, "u32": 4, "i32": 4, "u16": 2, "i16": 2, "u8": 1}[WIRE[f["type"]]]
    if size > 64:
        errs.append(f"telemetry 负载 {size} 字节 > 64（dzframe 上限），拆成两个通道")
    if not 1 <= int(tel.get("id", 2)) <= 0x7D:
        errs.append("telemetry.id 须在 1..125（0x7E/0x7F 留给命令/急停）")
    if len(params) > 125:
        errs.append("参数超过 125 个")
    names = {f.get("name") for f in tel.get("fields", [])}
    for f in tel.get("fields", []):
        r = f.get("ref_for")
        if r and (r not in names or r == f.get("name")):
            errs.append(f"telemetry.{f.get('name')}: ref_for 指向不存在的字段 {r}")
    for f in tel.get("fields", []):
        c = f.get("cal")
        if c is not None:
            pts = c.get("pts") if isinstance(c, dict) else None
            if not (isinstance(pts, list) and len(pts) >= 2 and all(isinstance(q, list) and len(q) == 2 for q in pts)
                    and len({float(q[0]) for q in pts}) == len(pts) and c.get("unit")):
                errs.append(f"telemetry.{f.get('name')}: cal 须为 {{unit: cm, pts: [[原始, 物理], ...]}}，至少两点且原始值互不相同")
            elif c.get("mode", "linear") not in ("linear", "piecewise"):
                errs.append(f"telemetry.{f.get('name')}: cal.mode 只能是 linear / piecewise")
    plotted = {f.get("name") for f in tel.get("fields", []) if not f.get("enum")}
    pnames = {p.get("name") for p in params}
    for a in spec.get("accept") or []:
        if a.get("y") not in plotted or not any(f.get("ref_for") == a.get("y") for f in tel.get("fields", [])):
            errs.append(f"accept.{a.get('name')}: y={a.get('y')} 须是遥测字段且有 ref_for 指向它的设定值")
        if not float(a.get("band", 0)) > 0:
            errs.append(f"accept.{a.get('name')}: band 须 > 0（物理单位，和该字段 cal.unit 一致）")
    for lp in spec.get("loops") or []:
        if lp.get("y") not in plotted:
            errs.append(f"loops.{lp.get('name')}: y={lp.get('y')} 不是遥测字段")
        for g in lp.get("gains") or []:
            if g not in pnames:
                errs.append(f"loops.{lp.get('name')}: 增益 {g} 不在参数表里")
    for p in params:
        if "min" not in p or "max" not in p:
            errs.append(f"参数 {p['name']}: 缺 min/max（上位机写参数必须限幅）")
        elif not p["min"] <= p.get("default", 0) <= p["max"]:
            errs.append(f"参数 {p['name']}: 默认值 {p.get('default', 0)} 不在 [{p['min']}, {p['max']}]")
    return errs


def schema(spec: dict, params: list) -> dict:
    tel = spec.get("telemetry") or {}
    s = {"version": 1,
         "telemetry": {"id": int(tel.get("id", 2)), "period_ms": int(tel.get("period_ms", 20)),
                       "fields": [{"name": f["name"], "type": WIRE[f["type"]], "unit": f.get("unit", ""),
                                   **({"enum": f["enum"]} if f.get("enum") else {}),
                                   **({"na": int(f["na"])} if f.get("na") is not None else {}),
                                   # pin：顶栏状态块的标签（任何题目通用，界面不认具体字段名）；pin_with：块里附带显示的数值字段
                                   **({"pin": str(f["pin"]), "pin_with": list(f.get("pin_with") or [])} if f.get("pin") else {}),
                                   # ref_for：本字段是哪个字段的设定值——界面把它画成那条曲线上的虚线（显式声明，不按名字猜）
                                   **({"ref_for": str(f["ref_for"])} if f.get("ref_for") else {})}    # 这个值表示“无数据”，界面显示 —
                                  for f in tel.get("fields", [])]},
         "params": [{"name": p["name"], "type": WIRE[p["type"]], "min": p["min"], "max": p["max"],
                     "unit": p.get("unit", "")} for p in params]}
    s["hash"] = fnv1a(json.dumps(s, sort_keys=True, separators=(",", ":")).encode())
    for p, src in zip(s["params"], params):
        p["default"] = src.get("default", 0)
        p["desc"] = src.get("desc", "")
        if src.get("protect"):                 # 保护阈值表的分类（堵转电流/倾倒角/限幅/断线停车…），只给界面
            p["protect"] = str(src["protect"])
    # 下面都只给上位机看（标定、验收、串级分层），不进哈希：改它们不用重烧固件
    for f, src in zip(s["telemetry"]["fields"], tel.get("fields", [])):
        if src.get("cal"):
            f["cal"] = src["cal"]
    for k in ("accept", "loops", "protect_fixed"):
        if spec.get(k):
            s[k] = spec[k]
    return s


def cnum(v, t: str) -> str:
    if t == "float":
        return f"{float(v)!r}f" if math.isfinite(float(v)) else "0.0f"
    if t == "bool":
        return "true" if v else "false"
    return f"{int(v)}{'u' if t.startswith('u') else ''}"


def render(spec: dict, params: list, struct: str | None, sch: dict) -> tuple[str, str]:
    tel = spec.get("telemetry") or {}
    fields = tel.get("fields", [])
    own = struct is None
    struct = struct or "link_params_t"
    hdr = "/* 由 tools/gen_link.py 自动生成，勿手改 */"
    h = [hdr, "#ifndef LINK_GEN_H", "#define LINK_GEN_H", "#include <stdbool.h>", "#include <stdint.h>",
         '#include "dzframe.h"', '#include "dzctl.h"']
    if not own:
        h.append('#include "project_gen.h"')
    h += ["", f"#define LINK_SCHEMA_HASH 0x{sch['hash']:08X}u", f"#define LINK_TELEM_ID {sch['telemetry']['id']}u",
          f"#define LINK_TELEM_PERIOD_MS {sch['telemetry']['period_ms']}u", f"#define LINK_N_PARAMS {len(params)}u", "",
          "typedef struct {"]
    h += [f"    {C_TYPES[f['type']][0]} {f['name']};  /**< {f.get('unit', '')} */" for f in fields] or ["    uint8_t unused_;"]
    h += ["} link_telem_t;", ""]
    if own:
        h += ["typedef struct {"]
        h += [f"    {C_TYPES[p['type']][0]} {p['name']};  /**< [{p['min']}, {p['max']}] {p.get('unit', '')} {p.get('desc', '')} */"
              for p in params] or ["    uint8_t unused_;"]
        h += ["} link_params_t;", "", "extern link_params_t g_link_params;               /**< 当前生效（上位机可改） */",
              "extern const link_params_t g_link_params_default;", ""]
    h += ["extern const dzctl_param_t g_link_param_desc[];",
          "/** 打包遥测帧（kind/id 已填，seq 由调用方填）。 */",
          "bool link_telem_pack(dzframe_t *f, const link_telem_t *t);",
          f"/** 参数表：base 指向当前生效的 {struct}。 */",
          f"dzctl_table_t link_param_table({struct} *base);", "", "#endif", ""]
    c = [hdr, "#include <stddef.h>", "#include <string.h>", '#include "link_gen.h"', ""]
    if own:
        body = ", ".join(f".{p['name']} = {cnum(p.get('default', 0), p['type'])}" for p in params) or "0"
        c += [f"const link_params_t g_link_params_default = {{ {body} }};", f"link_params_t g_link_params = {{ {body} }};", ""]
    c.append("const dzctl_param_t g_link_param_desc[] = {")
    c += [f'    {{ "{p["name"]}", (uint16_t)offsetof({struct}, {p["name"]}), {C_TYPES[p["type"]][1]}, '
          f'{cnum(p["min"], "float")}, {cnum(p["max"], "float")} }},' for p in params] or ['    { "", 0, 0, 0.0f, 0.0f }']
    c += ["};", "", "bool link_telem_pack(dzframe_t *f, const link_telem_t *t)", "{",
          "    memset(f, 0, sizeof *f);", "    f->kind = DZF_DATA; f->id = LINK_TELEM_ID;"]
    puts = []
    for x in fields:
        w = WIRE[x["type"]]
        put = {"f32": "f32", "u32": "u32", "i32": "u32", "u16": "u16", "i16": "u16", "u8": "u8"}[w]
        cast = {"u32": "uint32_t", "u16": "uint16_t", "u8": "uint8_t"}.get(put, "")
        puts.append(f"dzframe_put_{put}(f, {'(' + cast + ')' if cast else ''}t->{x['name']})")
    c.append(f"    return {' && '.join(puts) or 'true'};")
    c += ["}", "", f"dzctl_table_t link_param_table({struct} *base)", "{",
          f"    dzctl_table_t t = {{ base, g_link_param_desc, (uint8_t)LINK_N_PARAMS, LINK_SCHEMA_HASH }};",
          "    return t;", "}", ""]
    return "\n".join(h), "\n".join(c)


def load(path: pathlib.Path) -> tuple[dict, list, str | None]:
    y = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    spec = y.get("link") or {}
    if "params" in spec:
        return spec, spec["params"] or [], None
    return spec, y.get("params") or [], "params_t"


def selftest() -> int:
    spec = {"telemetry": {"id": 2, "fields": [{"name": "t", "type": "uint32"}, {"name": "x", "type": "float"}]},
            "params": [{"name": "kp", "type": "float", "default": 1, "min": 0, "max": 2}]}
    s = schema(spec, spec["params"])
    bad = check({"telemetry": {"fields": [{"name": "x", "type": "float"}] * 17}},
                [{"name": "k", "type": "float", "default": 3, "min": 0, "max": 2}])
    ok = s["telemetry"]["fields"][1]["type"] == "f32" and len(bad) == 2 and s["hash"] == schema(spec, spec["params"])["hash"]
    print(f"{'✓' if ok else '✗'} gen_link 自检{'' if ok else ': ' + repr((s, bad))}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("yaml", nargs="?", type=pathlib.Path)
    ap.add_argument("-o", "--out", type=pathlib.Path)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    spec, params, struct = load(a.yaml)
    errs = check(spec, params)
    for e in errs:
        print(f"错误  {a.yaml}: {e}", file=sys.stderr)
    if errs:
        return 1
    sch = schema(spec, params)
    h, c = render(spec, params, struct, sch)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "link_gen.h").write_text(h, encoding="utf-8")
    (a.out / "link_gen.c").write_text(c, encoding="utf-8")
    (a.out / "link_schema.json").write_text(json.dumps(sch, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
