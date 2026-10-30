"""重复定义检查（make check）：
1) ruff --select F811：同一作用域里函数/类/import 被重复定义（后一份悄悄覆盖前一份）；
2) server.py 的 op 分发：同一个 `if op == "x"` 出现两次（F811 抓不到——不是定义，是两条分支，后一条永远走不到）。
用法：python tools/check_redef.py [--selftest]"""
from __future__ import annotations

import collections
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
OP_RE = re.compile(r'^( *)(?:el)?if op == "([a-z_0-9.]+)"', re.M)


def ruff_f811(paths: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", "--select", "F811",
                            "--output-format", "concise", *paths], capture_output=True, text=True)
    except FileNotFoundError:
        return 2, ""
    if r.returncode not in (0, 1) or "No module named ruff" in r.stderr:
        return 2, r.stderr
    return r.returncode, r.stdout


def dup_ops(text: str) -> dict[str, list[int]]:
    ms = list(OP_RE.finditer(text))
    top = min((len(m[1]) for m in ms), default=0)        # 只看分发层；分支里面再按 op 细分的不算
    where = collections.defaultdict(list)
    for m in ms:
        if len(m[1]) == top:
            where[m[2]].append(text.count("\n", 0, m.start()) + 1)
    return {k: v for k, v in where.items() if len(v) > 1}


def run(sidecar: pathlib.Path, server: pathlib.Path) -> int:
    rc, out = ruff_f811([str(sidecar)])
    bad = 0
    if rc == 2:
        print("✗ [redef] ruff 没跑成 · 原因：没装 ruff · 处理：pip install -r app/sidecar/requirements.txt", file=sys.stderr)
        return 2
    if rc:
        print(out.strip(), file=sys.stderr)
        print("✗ [redef] 有重复定义（F811）· 处理：删掉多余的那份，保留一个实现", file=sys.stderr)
        bad = 1
    for op, lines in dup_ops(server.read_text(encoding="utf-8")).items():
        print(f"✗ [redef] {server.name}: op {op!r} 有 {len(lines)} 条分支（第 {', '.join(map(str, lines))} 行）· 原因：后面的永远走不到 · 处理：合并成一份", file=sys.stderr)
        bad = 1
    return bad


def selftest() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d)
        (p / "dup.py").write_text("def f():\n    return 1\n\n\ndef f():\n    return 2\n", encoding="utf-8")
        rc, out = ruff_f811([str(p / "dup.py")])
        assert rc == 1 and "F811" in out, (rc, out)
        (p / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        assert ruff_f811([str(p / "ok.py")])[0] == 0
    srv = 'async def _op(m):\n    op = m["op"]\n    if op == "a":\n        return 1\n    if op == "b":\n        return 2\n    if op == "a":\n        return 3\n'
    assert dup_ops(srv) == {"a": [3, 7]}, dup_ops(srv)
    nested = 'async def _op(m):\n    op = m["op"]\n    if op == "a" or op == "b":\n        if op == "a":\n            return 1\n        return 2\n'
    assert dup_ops(nested) == {}, dup_ops(nested)
    assert dup_ops(srv.replace('op == "a":\n        return 3', 'op == "c":\n        return 3')) == {}
    print("check_redef selftest: 5 ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    rc = run(ROOT / "app/sidecar", ROOT / "app/sidecar/dzbench/server.py")
    if rc == 0:
        print("✓ 无重复定义（ruff F811 + server.py op 分支）")
    sys.exit(rc)
