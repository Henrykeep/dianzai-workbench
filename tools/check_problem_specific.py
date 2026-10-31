#!/usr/bin/env python3
"""#80 核心代码里不许有「为某一道题写的」东西：题号、例题名、例题对象名、针对例题的写死整定常数。

扫描范围（核心代码）：app/sidecar/dzbench、app/ui/src、firmware/、tools/templates/。
不扫：examples/（例题本身）、tests/ 与测试夹具、第三方。
例题名自动从 examples/ 目录名里取（2026H_ball → 2026H_ball / 2026h-ball / 2026H），新增例题不用改本脚本。

已知存量写在 tools/problem_specific_allow.txt（每行：路径:规则:说明，带负责人/问题号），只减不增：
新出现的命中 → 红；存量里登记了但已经不存在 → 也红（提醒删登记，保证棘轮只往下走）。
用法：check_problem_specific.py [--list FILE.md] [--selftest]
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCOPES = ["app/sidecar/dzbench", "app/ui/src", "firmware", "tools/templates"]
EXCL = re.compile(r"(^|/)(tests?|fixtures|examples|__pycache__|node_modules|third_party)(/|$)|(^|/)test_[^/]*$|\.test\.ts$|\.spec\.ts$|(^|/)evals[^/]*\.json$")   # evals*.json = 评测题集（数据，不是逻辑）
EXTS = {".py", ".ts", ".tsx", ".js", ".c", ".h", ".json", ".yaml", ".yml", ".tmpl", ".jinja", ".svelte", ".vue", ".css", ".html", ".j2"}
ALLOW = ROOT / "tools" / "problem_specific_allow.txt"

FIXED = [("problem_code", r"(?<![0-9A-Za-z])(19|20)\d\d[A-Ha-hJ-Zj-z](?![a-zA-Z0-9])"),     # 2026H / 2023j 题号
         ("example_obj", r"小球|钢球|钢珠|滚球|板球|(?<![A-Za-z])ball(?![A-Za-z])"),
         ("example_obj", r"motor_pos"),
         ("magic_tuning", r"[\"']?(hold_s|return_tol|return_timeout_s|step_target|step_dur_ms|abs_tol)[\"']?\s*[:=]\s*\d")]


def rules(root: pathlib.Path = ROOT) -> list[tuple[str, re.Pattern]]:
    rs = list(FIXED)
    for d in sorted((root / "examples").glob("*")):
        if d.is_dir():
            n = d.name
            alts = {n, n.lower(), n.replace("_", "-").lower()}
            rs.append(("example_name", "|".join(re.escape(a) for a in sorted(alts))))
    return [(k, re.compile(p)) for k, p in rs]


def scan(root: pathlib.Path = ROOT) -> list[tuple[str, int, str, str]]:
    rs, out = rules(root), []
    for sc in SCOPES:
        for f in sorted((root / sc).rglob("*")):
            rel = f.relative_to(root).as_posix()
            if not f.is_file() or f.suffix not in EXTS or EXCL.search(rel):
                continue
            try:
                lines = f.read_text("utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for i, ln in enumerate(lines, 1):
                for k, r in rs:
                    if r.search(ln):
                        out.append((rel, i, k, ln.strip()[:160]))
                        break
    return out


def load_allow() -> dict[tuple[str, str], int]:
    """路径:规则 → 允许的条数（存量）。"""
    a: dict[tuple[str, str], int] = {}
    if ALLOW.exists():
        for ln in ALLOW.read_text("utf-8").splitlines():
            if ln.strip() and not ln.startswith("#"):
                p, k, n = ln.split("\t")[:3]
                a[(p, k)] = int(n)
    return a


def write_list(hits, path: str) -> None:
    by: dict[str, list] = {}
    for h in hits:
        by.setdefault(h[0].split("/")[0] + "/" + h[0].split("/")[1], []).append(h)
    md = ["# r10 #80 写死清单（核心代码里为例题定制的地方）", "",
          f"生成：`python3 tools/check_problem_specific.py --list`，共 {len(hits)} 处。规则：题号、例题对象（小球/ball/motor_pos）、例题目录名、写死整定常数。", ""]
    for g, hs in sorted(by.items()):
        md += [f"## {g}（{len(hs)}）", "", "| 文件:行 | 规则 | 内容 |", "|---|---|---|"]
        md += [f"| {p}:{i} | {k} | `{t.replace('|', '¦').replace('`', '')}` |" for p, i, k, t in hs] + [""]
    pathlib.Path(path).write_text("\n".join(md), "utf-8")


def selftest() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        r = pathlib.Path(d)
        (r / "examples" / "2031Q_fan").mkdir(parents=True)
        (r / "app/sidecar/dzbench").mkdir(parents=True)
        (r / "app/sidecar/dzbench/a.py").write_text('X = {"2031Q_fan": 1}\nif port == "sim:ball": pass\nok = 1\nh = {"hold_s": 5.0}\n', "utf-8")
        (r / "app/sidecar/dzbench/tests").mkdir()
        (r / "app/sidecar/dzbench/tests/t.py").write_text("2026H\n", "utf-8")
        ks = [h[2] for h in scan(r)]
        assert ks == ["problem_code", "example_obj", "magic_tuning"], ks
    print("✓ check_problem_specific selftest")


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        selftest()
        return 0
    hits = scan()
    if "--list" in argv:
        write_list(hits, argv[argv.index("--list") + 1])
    cnt: dict[tuple[str, str], int] = {}
    for p, _, k, _ in hits:
        cnt[(p, k)] = cnt.get((p, k), 0) + 1
    allow, bad = load_allow(), []
    for key, n in sorted(cnt.items()):
        if n > allow.get(key, 0):
            bad += [f"✗ {p}:{i} [{k}] {t}" for p, i, k, t in hits if (p, k) == key]
    stale = [f"✗ 登记了但已清掉，请从 {ALLOW.name} 删掉/调小：{p} {k} {n}→{cnt.get((p, k), 0)}"
             for (p, k), n in allow.items() if cnt.get((p, k), 0) < n]
    for b in bad + stale:
        print(b)
    if bad or stale:
        print("核心代码不许为某一道题写专门代码（#80）：题目差异写进工程声明，时序/幅度靠实测。")
        return 1
    print(f"✓ check_problem_specific：新增 0；存量登记 {sum(allow.values())} 处待清（{ALLOW.name}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
