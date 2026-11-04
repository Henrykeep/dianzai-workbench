#!/usr/bin/env python3
"""#164 侧车会发出的每个原因码，都必须在界面用的原因表（docs/dev/reason_codes.json）里有中文。

通用检查，不针对某道题。码的来源（启发式，全部是对 app/sidecar/dzbench/**/*.py 的静态 AST 扫描，tests/ 不算）：
  1. 声明的登记表：原因码模块（默认 dzbench/agent/reason_codes.py 及其 from-import 的模块）里
     名字以 _ZH 结尾的 dict 字面量（含 X["k"] = ... 的追加），键就是码。
  2. dict 字面量里键为 reason / stop_reason / cause / reason_code 的字符串字面量值。
  3. dict 字面量里键为 causes 的 list/tuple 中的字符串字面量（只取形如 snake_case 的码，中文说明跳过）。
  4. 调用里的关键字参数 reason= / cause= / stop_reason= 的字符串字面量（含 link.state 的 reason）。
只收形如码的值：^[a-z][a-z0-9]*(_[a-z0-9]+)*$；动态拼出来的码扫不到（会在输出里注明）。
fix_action 是修复动作不是原因（界面另有动作表），只列出供参考，不判失败。
表里条目必须有非空 message_zh 或 zh（界面 codeZh 的取值顺序）。
退出码：0 全在表里；1 有缺失（逐条列出码和出处）；2 表文件缺失/格式错。不存在静默跳过。
用法：check_reason_codes.py [--root DIR] [--table PATH] [--selftest]
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
import tempfile

CODE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
REASON_KEYS = {"reason", "stop_reason", "cause", "reason_code"}
CAUSES_KEYS = {"causes"}
INFO_KEYS = {"fix_action"}
REGISTRY_FILES = ("dzbench/agent/reason_codes.py",)


def _s(n):
    return n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else None


def _add(d, code, where):
    if code and CODE_RE.match(code):
        d.setdefault(code, []).append(where)


def scan_file(path: pathlib.Path, rel: str, registry: bool, codes: dict, info: dict):
    try:
        tree = ast.parse(path.read_text("utf-8"), str(path))
    except SyntaxError as e:
        raise SystemExit(f"无法解析 {rel}：{e}")
    for node in ast.walk(tree):
        at = f"{rel}:{getattr(node, 'lineno', 0)}"
        if registry and isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id.endswith("_ZH") and isinstance(node.value, ast.Dict):
                    for k in node.value.keys:
                        _add(codes, _s(k), at + "（登记表 " + t.id + "）")
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id.endswith("_ZH")):
                    _add(codes, _s(t.slice), at + "（登记表 " + t.value.id + "）")
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                key = _s(k)
                if key in REASON_KEYS:
                    _add(codes, _s(v), at)
                elif key in CAUSES_KEYS and isinstance(v, (ast.List, ast.Tuple)):
                    for e in v.elts:
                        _add(codes, _s(e), at + "（causes）")
                elif key in INFO_KEYS:
                    _add(info, _s(v), at)
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in REASON_KEYS:
                    _add(codes, _s(kw.value), at)
                elif kw.arg in INFO_KEYS:
                    _add(info, _s(kw.value), at)


def collect(sidecar: pathlib.Path):
    codes, info = {}, {}
    pkg = sidecar / "dzbench"
    if not pkg.is_dir():
        raise SystemExit(f"找不到侧车源码目录 {pkg}")
    reg = {(sidecar / r).resolve() for r in REGISTRY_FILES}
    # 登记表模块 from .x import A_ZH 引入的模块也按登记表扫
    for r in list(reg):
        if r.exists():
            for n in ast.walk(ast.parse(r.read_text("utf-8"))):
                if isinstance(n, ast.ImportFrom) and n.level == 1 and n.module:
                    reg.add((r.parent / (n.module.replace(".", "/") + ".py")).resolve())
    files = sorted(p for p in pkg.rglob("*.py") if "tests" not in p.relative_to(sidecar).parts)
    if not files:
        raise SystemExit(f"{pkg} 下没有 .py 文件")
    for p in files:
        scan_file(p, str(p.relative_to(sidecar.parent.parent)), p.resolve() in reg, codes, info)
    return codes, info, len(files)


def load_table(path: pathlib.Path) -> dict:
    if not path.exists():
        print(f"原因表 {path} 不存在", file=sys.stderr)
        sys.exit(2)
    try:
        t = json.loads(path.read_text("utf-8"))
    except ValueError as e:
        print(f"原因表 {path} 不是合法 JSON：{e}", file=sys.stderr)
        sys.exit(2)
    if not isinstance(t, dict):
        print(f"原因表 {path} 顶层应是对象", file=sys.stderr)
        sys.exit(2)
    return t


def has_zh(e) -> bool:
    return isinstance(e, dict) and any(isinstance(e.get(k), str) and e[k].strip() for k in ("message_zh", "zh"))


def run(root: pathlib.Path, table: pathlib.Path, out=sys.stdout) -> int:
    codes, info, nfiles = collect(root / "app" / "sidecar")
    t = load_table(table)
    missing = {c: w for c, w in sorted(codes.items()) if c not in t}
    nozh = {c: w for c, w in sorted(codes.items()) if c in t and not has_zh(t[c])}
    print(f"原因码检查：扫了 {nfiles} 个侧车文件，找到 {len(codes)} 个原因码，原因表 {len(t)} 条。"
          "（只认字面量；动态拼出的码扫不到）", file=out)
    if info:
        print("参考（修复动作 fix_action，不判失败）：" + "、".join(sorted(info)), file=out)
    if not missing and not nozh:
        print("通过：侧车会发出的原因码都在原因表里且有中文。", file=out)
        return 0
    if missing:
        print(f"失败：{len(missing)} 个原因码不在原因表 {table.name} 里（界面会显示成「其他原因（代码…）」）：", file=out)
        for c, w in missing.items():
            print(f"  - {c}    出处：{w[0]}" + (f" 等 {len(w)} 处" if len(w) > 1 else ""), file=out)
    if nozh:
        print(f"失败：{len(nozh)} 个原因码在表里但没有中文（message_zh / zh 为空）：", file=out)
        for c, w in nozh.items():
            print(f"  - {c}    出处：{w[0]}", file=out)
    print("修法：把码加进 app/sidecar/dzbench/agent/reason_codes.py 的登记表，再跑 tools/gen_reason_codes.py。", file=out)
    return 1


def selftest() -> int:
    import io
    with tempfile.TemporaryDirectory(prefix="dz_rc_") as d:
        r = pathlib.Path(d)
        pkg = r / "app/sidecar/dzbench/agent"
        pkg.mkdir(parents=True)
        (pkg / "reason_codes.py").write_text('A_ZH = {"reg_code": "登记"}\nA_ZH["reg_two"] = "二"\n', "utf-8")
        (pkg.parent / "x.py").write_text(
            'def f(s):\n    s.emit({"type": "e", "reason": "alpha_code", "fix_action": "do_x", "causes": ["beta_cause", "中文说明"]})\n'
            '    s.state(reason="gamma")\n    return {"reason": None, "message": "Not A Code"}\n', "utf-8")
        (pkg.parent / "tests").mkdir()
        (pkg.parent / "tests/t.py").write_text('{"reason": "only_in_tests"}\n', "utf-8")
        tab = r / "t.json"
        full = {c: {"zh": "中"} for c in ("reg_code", "reg_two", "alpha_code", "beta_cause", "gamma")}
        tab.write_text(json.dumps(full), "utf-8")
        buf = io.StringIO()
        assert run(r, tab, buf) == 0, buf.getvalue()
        codes, info, _ = collect(r / "app/sidecar")
        assert set(codes) == set(full) and set(info) == {"do_x"}, (codes, info)
        part = dict(full); del part["beta_cause"]; part["gamma"] = {"zh": ""}
        tab.write_text(json.dumps(part), "utf-8")
        buf = io.StringIO()
        assert run(r, tab, buf) == 1
        o = buf.getvalue()
        assert "beta_cause" in o and "gamma" in o and "不在原因表" in o and "没有中文" in o, o
        part = dict(full); part["gamma"] = {"message_zh": "有"}
        tab.write_text(json.dumps(part), "utf-8")
        assert run(r, tab, io.StringIO()) == 0
    print("check_reason_codes 自测通过")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    ap.add_argument("--table", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    root = pathlib.Path(a.root)
    sys.exit(run(root, pathlib.Path(a.table) if a.table else root / "docs/dev/reason_codes.json"))
