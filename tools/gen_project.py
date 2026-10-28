#!/usr/bin/env python3
"""由每题的 project.yaml 生成共享状态、参数档、测试项和子系统表（project_gen.h / project_gen.c）。

框架代码（firmware/framework）不认识任何题目；题目的全部"形状"都写在 project.yaml：
  state:       共享状态的各段，每段只有一个写者（owner：某个子系统 / io / coord）
  subsystems:  子系统列表（名字、周期、在哪块板上、owns 哪段、reads 哪些段）
  params:      参数字段定义（名字、类型、默认值）
  profiles:    参数档（只写与默认值不同的项）
  tests:       测试项（小题号、名字、默认参数档、限时）

用法：
  python3 tools/gen_project.py examples/2026H_ball/project.yaml -o build/.../gen [--role main]
  python3 tools/gen_project.py <project.yaml> --check        # 只校验
--role 用于多板分布：只生成 board 角色为该值的子系统（例如 main / aux）。
"""
import argparse
import pathlib
import re
import sys

import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

TYPES = {"float": "float", "int32": "int32_t", "uint32": "uint32_t", "uint16": "uint16_t",
         "int16": "int16_t", "uint8": "uint8_t", "bool": "bool"}
IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_OWNERS = {"io", "coord"}


ROOT = pathlib.Path(__file__).resolve().parent.parent


def board_kinds(p: dict) -> dict:
    """角色 -> kind（mcu/coprocessor）；找不到 board.yaml 或写 TODO 的角色视为 mcu。"""
    out = {}
    for role, name in (p.get("boards") or {"main": None}).items():
        kind = "mcu"
        f = ROOT / "boards" / str(name) / "board.yaml"
        if name and f.exists():
            kind = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("kind", "mcu")
        out[role] = (kind, f if name and f.exists() else None)
    return out


def check(p: dict) -> list[str]:
    err = []
    for k in ("name", "state", "subsystems", "tests", "profiles"):
        if k not in p:
            err.append(f"缺少顶层字段 {k}")
    if err:
        return err
    roles = set((p.get("boards") or {"main": None}).keys())
    sections = p["state"] or {}
    owners = {}
    for sec, d in sections.items():
        if not IDENT.match(sec):
            err.append(f"state 段名 {sec} 须为小写标识符")
        owner = (d or {}).get("owner")
        if not owner:
            err.append(f"state.{sec} 缺少 owner")
        owners[sec] = owner
        names = set()
        for f in (d or {}).get("fields", []) or []:
            if f.get("type") not in TYPES:
                err.append(f"state.{sec}.{f.get('name')} 类型 {f.get('type')} 不支持（{', '.join(TYPES)}）")
            if not IDENT.match(str(f.get("name", ""))):
                err.append(f"state.{sec} 字段名 {f.get('name')} 非法")
            if f.get("name") in names:
                err.append(f"state.{sec} 字段 {f['name']} 重复")
            names.add(f.get("name"))
    sub_names = []
    for s in p["subsystems"] or []:
        n = s.get("name", "")
        if not IDENT.match(n) or n in RESERVED_OWNERS:
            err.append(f"子系统名 {n} 非法或与保留名 io/coord 冲突")
        if n in sub_names:
            err.append(f"子系统 {n} 重复")
        sub_names.append(n)
        if not isinstance(s.get("period_ms"), int) or s["period_ms"] <= 0:
            err.append(f"子系统 {n} 的 period_ms 必须是正整数")
        if s.get("board", "main") not in roles:
            err.append(f"子系统 {n} 的 board 角色 {s.get('board')} 不在 boards: {sorted(roles)}")
        elif board_kinds(p)[s.get("board", "main")][0] == "coprocessor":
            err.append(f"子系统 {n} 被分配到协处理板角色 {s.get('board')}：协处理板不运行本框架代码，子系统只能放在 MCU/软核板上")
        for sec in s.get("owns", []) or []:
            if sec not in sections:
                err.append(f"子系统 {n} owns 不存在的段 {sec}")
            elif owners.get(sec) != n:
                err.append(f"段 {sec} 的 owner 是 {owners.get(sec)}，子系统 {n} 不能声明 owns")
        for sec in s.get("reads", []) or []:
            if sec not in sections:
                err.append(f"子系统 {n} reads 不存在的段 {sec}")
    for sec, o in owners.items():
        if o and o not in RESERVED_OWNERS and o not in sub_names:
            err.append(f"段 {sec} 的 owner {o} 不是已声明的子系统，也不是 io/coord")
    pnames = {x["name"] for x in p.get("params", []) or []}
    prof_names = [x.get("name") for x in p["profiles"] or []]
    if not prof_names:
        err.append("至少需要一个参数档")
    for pr in p["profiles"] or []:
        for k in (pr.get("set") or {}):
            if k not in pnames:
                err.append(f"参数档 {pr.get('name')} 设置了未定义的参数 {k}")
    ids = set()
    for t in p["tests"] or []:
        if t.get("profile") not in prof_names:
            err.append(f"测试项 {t.get('name')} 引用了不存在的参数档 {t.get('profile')}")
        if t.get("id") in ids:
            err.append(f"测试项编号 {t.get('id')} 重复")
        ids.add(t.get("id"))
    if len(p["subsystems"] or []) > 16:
        err.append("子系统超过 16 个（SUBSYS_MAX）")
    return err


def cval(v, typ):
    if typ == "bool":
        return "true" if v else "false"
    if typ == "float":
        return f"{float(v)!r}f"
    return str(int(v))


def gen(p: dict, role: str | None, src: str) -> tuple[str, str]:
    hdr = f"/* 自动生成，请勿手改。来源：{src}。改结构请改 project.yaml。 */\n"
    h = [hdr, "#ifndef PROJECT_GEN_H", "#define PROJECT_GEN_H", "",
         "#include <stdint.h>", "#include <stdbool.h>", '#include "subsys.h"', '#include "coord.h"', "",
         f'#define PROJECT_NAME "{p["name"]}"', f'#define PROJECT_ROLE "{role or "all"}"', ""]
    for sec, d in p["state"].items():
        h.append(f"/* 段 {sec}：唯一写者 = {d['owner']}。{d.get('desc', '')} */")
        h.append("typedef struct {")
        for f in d.get("fields", []) or []:
            unit = f" [{f['unit']}]" if f.get("unit") else ""
            h.append(f"    {TYPES[f['type']]} {f['name']};  /**< {f.get('desc', '')}{unit} */")
        if not d.get("fields"):
            h.append("    uint8_t unused_;")
        h.append(f"}} st_{sec}_t;\n")
    h.append("/** 整题共享状态：子系统之间只通过它交换数据 */")
    h.append("typedef struct {")
    for sec in p["state"]:
        h.append(f"    st_{sec}_t {sec};")
    h.append("} shared_state_t;\n")
    params = p.get("params", []) or []
    h.append("/** 参数档字段 */")
    h.append("typedef struct {")
    for x in params:
        h.append(f"    {TYPES[x['type']]} {x['name']};  /**< {x.get('desc', '')} */")
    if not params:
        h.append("    uint8_t unused_;")
    h.append("} params_t;\n")
    subs = [s for s in p["subsystems"] if role is None or s.get("board", "main") == role]
    for s in p["subsystems"]:
        h.append(f"#define PERIOD_MS_{s['name'].upper()} {s['period_ms']}u  /* 子系统里用这个宏，不要另写数字 */")
    for s in subs:
        h.append(f"extern const subsys_t SUBSYS_{s['name'].upper()};  /* owns {s.get('owns', [])} reads {s.get('reads', [])} */")
    h += ["", f"#define PROJECT_N_SUBSYS {len(subs)}u", f"#define PROJECT_N_TESTS {len(p['tests'])}u",
          f"#define PROJECT_N_PROFILES {len(p['profiles'])}u",
          "extern const subsys_t *const g_project_subsys[];", "extern const coord_test_t g_project_tests[];",
          "extern const coord_profile_t g_project_profiles[];", "extern params_t g_project_params[];  /* RAM：上位机经 dzctl 可改当前参数档 */", ""]
    for i, pr in enumerate(p["profiles"]):
        h.append(f"#define PROFILE_{pr['name'].upper()} {i}u")
    h += ["", "#endif", ""]

    c = [hdr, '#include "project_gen.h"', ""]
    c.append("const subsys_t *const g_project_subsys[] = {")
    c += [f"    &SUBSYS_{s['name'].upper()}," for s in subs] or ["    0"]
    c.append("};\n")
    prof_idx = {pr["name"]: i for i, pr in enumerate(p["profiles"])}
    c.append("params_t g_project_params[] = {")
    for pr in p["profiles"]:
        vals = dict((x["name"], x.get("default", 0)) for x in params)
        vals.update(pr.get("set") or {})
        body = ", ".join(f".{x['name']} = {cval(vals[x['name']], x['type'])}" for x in params) or "0"
        c.append(f"    {{ {body} }},  /* {pr['name']}：{pr.get('desc', '')} */")
    c.append("};\n")
    c.append("const coord_profile_t g_project_profiles[] = {")
    c += [f'    {{ "{pr["name"]}", &g_project_params[{i}] }},' for i, pr in enumerate(p["profiles"])]
    c.append("};\n")
    c.append("const coord_test_t g_project_tests[] = {")
    for t in p["tests"]:
        c.append(f'    {{ {t["id"]}u, "{t["name"]}", {prof_idx[t["profile"]]}u, {int(t.get("time_limit_s", 0) * 1000)}u }},')
    c.append("};\n")
    return "\n".join(h), "\n".join(c)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=pathlib.Path)
    ap.add_argument("-o", "--out", type=pathlib.Path)
    ap.add_argument("--role")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    p = yaml.safe_load(a.project.read_text(encoding="utf-8"))
    errs = check(p)
    for e in errs:
        print(f"错误  {e}", file=sys.stderr)
    if errs:
        print(f"✗ {a.project} 校验未通过", file=sys.stderr)
        return 1
    if a.check or not a.out:
        print(f"✓ {a.project} 结构正确：{len(p['subsystems'])} 个子系统，{len(p['tests'])} 个测试项，{len(p['profiles'])} 个参数档")
        return 0
    h, c = gen(p, a.role, a.project.as_posix())
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "project_gen.h").write_text(h, encoding="utf-8")
    (a.out / "project_gen.c").write_text(c, encoding="utf-8")
    print(f"✓ 已生成 {a.out}/project_gen.{{h,c}}")
    # 协处理板：为每个 kind: coprocessor 的角色生成 cp_<角色>.{h,c} 通道编解码
    import gen_coproc
    extra = []
    for role, (kind, f) in board_kinds(p).items():
        if kind == "coprocessor":
            if gen_coproc.run(f, a.out, f"cp_{role}") != 0:
                return 1
            extra.append(f"cp_{role}.c")
    # 给 Makefile 的源文件清单（make 会自动重新读入）
    srcs = " ".join(f"$(PROJ_GEN)/{x}" for x in ["project_gen.c"] + extra)
    (a.out / "project_gen.mk").write_text(f"# 自动生成\nPROJ_SRC := {srcs}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
