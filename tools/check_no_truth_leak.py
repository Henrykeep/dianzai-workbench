#!/usr/bin/env python3
"""信息泄漏守卫：被控对象的真值（plant.json、randplant 的 feasible / 原因标签 / witness）只许判卷模块读。

唯一判卷模块：tools/tunegate_grade.py（另有出题方 tools/randplant*.py、tools/tunegate_plant.py、tools/feascheck.py 及其测试）。
被查的“非判卷代码”：
  - app/sidecar/dzbench/**（用户实际跑的整定 / Agent 代码）：不许出现 "plant.json" 字符串、不许 import randplant / feascheck /
    tunegate_plant / tunegate_grade / randplant_standin，不许按 feasible / feasibility / reason_category / infeasible_reason / witness 取键；
  - tools/tunegate.py（门禁驱动）：不许出现 "plant.json" 字符串、不许 import randplant / feascheck（判卷结果只从 tunegate_grade 拿）；
  - tools/ 下其余脚本（出题方 / 判卷模块 / 本守卫除外）：同后端规则。
任何形式引用真值键都算：字符串常量、属性名、变量名、关键字参数、取键 / .get()（汇总、按标签分桶都放进 tunegate_grade）。
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
ALLOWED = {"tunegate_grade.py", "randplant.py", "randplant_standin.py", "tunegate_plant.py", "feascheck.py", "check_no_truth_leak.py"}


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
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and n.value in TRUTH_KEYS:
            bad.append(f"{ln}: 引用真值键 {n.value!r}")
        elif isinstance(n, ast.Attribute) and n.attr in TRUTH_KEYS:
            bad.append(f"{ln}: 引用真值键 .{n.attr}")
        elif isinstance(n, ast.Name) and n.id in TRUTH_KEYS:
            bad.append(f"{ln}: 引用真值键 {n.id}")
        elif isinstance(n, ast.keyword) and n.arg in TRUTH_KEYS:
            bad.append(f"{ln}: 引用真值键 {n.arg}=")
    return bad


def files():
    for p in sorted((ROOT / "app/sidecar/dzbench").rglob("*.py")):
        yield p, True
    yield ROOT / "tools/tunegate.py", False
    for p in sorted((ROOT / "tools").glob("*.py")):
        if p.name not in ALLOWED | {"tunegate.py"} and not p.name.startswith("test_"):
            yield p, True


def selftest() -> int:
    cases = [('import json\nd = json.load(open(d + "/plant.json"))\n', True, 1), ('import randplant\n', True, 1),
             ('x = p["feasible"]\n', True, 1), ('x = p.get("witness")\n', True, 1), ('from feascheck import judge\n', False, 1),
             ('"""plant.json 只在判卷读"""\nx = 1\n', True, 0), ('import tunegate_grade\nr.get("feasible")\n', False, 1), ('import tunegate_grade\nS = G.summarize(rs)\n', False, 0),
             ('ok = r.feasibility\n', True, 1), ('reason_category = 1\n', True, 1), ('f(witness=1)\n', True, 1),
             ('k = "infeasible_reason"\n', False, 1),
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
