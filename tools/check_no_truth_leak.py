#!/usr/bin/env python3
"""信息泄漏守卫：被控对象的真值（plant.json、randplant 的 feasible / 原因标签 / witness）只许判卷模块读。

唯一判卷模块：tools/tunegate_grade.py（另有出题方 tools/randplant*.py、tools/tunegate_plant.py、tools/feascheck.py 及其测试）。
被查的“非判卷代码”：
  - app/sidecar/dzbench/**（用户实际跑的整定 / Agent 代码）：不许出现 "plant.json" 字符串、不许 import randplant / feascheck /
    tunegate_plant / tunegate_grade / randplant_standin，不许按 feasible / feasibility / reason_category / infeasible_reason / witness 取键；
  - tools/tunegate.py（门禁驱动）：不许出现 "plant.json" 字符串、不许 import randplant / feascheck（判卷结果只从 tunegate_grade 拿）。
用 AST 查（注释、文档字符串不算）。`--selftest` 自检规则本身。
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TRUTH_KEYS = {"feasible", "feasibility", "reason_category", "infeasible_reason", "witness"}
BACKEND_MODS = {"randplant", "feascheck", "tunegate_plant", "tunegate_grade", "randplant_standin"}
DRIVER_MODS = {"randplant", "feascheck"}


def _docstrings(tree) -> set[int]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            b = n.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                out.add(id(b.value))
    return out


def scan(src: str, backend: bool) -> list[str]:
    tree = ast.parse(src)
    docs = _docstrings(tree)
    mods = BACKEND_MODS if backend else DRIVER_MODS
    bad = []
    for n in ast.walk(tree):
        ln = getattr(n, "lineno", 0)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and "plant.json" in n.value:
            bad.append(f"{ln}: 读 plant.json")
        elif isinstance(n, ast.Import):
            bad += [f"{ln}: import {a.name}" for a in n.names if a.name.split(".")[0] in mods]
        elif isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] in mods:
            bad.append(f"{ln}: from {n.module} import")
        elif backend and isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and n.slice.value in TRUTH_KEYS:
            bad.append(f"{ln}: 取真值键 [{n.slice.value!r}]")
        elif backend and isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args \
                and isinstance(n.args[0], ast.Constant) and n.args[0].value in TRUTH_KEYS:
            bad.append(f"{ln}: 取真值键 .get({n.args[0].value!r})")
    return bad


def files():
    for p in sorted((ROOT / "app/sidecar/dzbench").rglob("*.py")):
        yield p, True
    yield ROOT / "tools/tunegate.py", False


def selftest() -> int:
    cases = [('import json\nd = json.load(open(d + "/plant.json"))\n', True, 1), ('import randplant\n', True, 1),
             ('x = p["feasible"]\n', True, 1), ('x = p.get("witness")\n', True, 1), ('from feascheck import judge\n', False, 1),
             ('"""plant.json 只在判卷读"""\nx = 1\n', True, 0), ('import tunegate_grade\nr.get("feasible")\n', False, 0),
             ('x = p["kp"]\n', True, 0)]
    for src, be, want in cases:
        got = len(scan(src, be))
        if got != want:
            print(f"check_no_truth_leak selftest 失败：{src!r} backend={be} 期望 {want} 处，得 {got}")
            return 1
    print(f"check_no_truth_leak selftest：{len(cases)} 例通过")
    return 0


def main(argv) -> int:
    if "--selftest" in argv:
        return selftest()
    errs = []
    for p, be in files():
        errs += [f"{p.relative_to(ROOT)}:{e}" for e in scan(p.read_text("utf-8"), be)]
    for e in errs:
        print("✗ 真值泄漏 " + e)
    print(f"check_no_truth_leak：{'失败 ' + str(len(errs)) + ' 处（真值只许 tools/tunegate_grade.py 读）' if errs else '通过'}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
