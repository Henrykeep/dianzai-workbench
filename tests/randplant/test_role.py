#!/usr/bin/env python3
"""参数角色 role（make test）：
  A. gen_link：未知 role 拒绝（中文报错）；没写 role → link_schema.json 里 null；role 不进 schema 哈希（改角色不用重烧）。
  B. randplant（RANDPLANT_SEEDS）：app.yaml 每个可调参数都带 role，和对象内部 roles 一一对应。
  C. host-sim 握手：编出的仿真板心跳 schema_hash = 生成的 link_schema.json 的 hash，该表的参数都带对的 role。
"""
from __future__ import annotations

import json
import os
import shutil
import pathlib
import struct
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_link  # noqa: E402
import randplant  # noqa: E402

HOME = ROOT / "build" / "randplant-role"
os.environ["DZBENCH_HOME"] = str(HOME)
import test_step_result as tsr  # noqa: E402

fail = 0


def ok(cond, msg):
    global fail
    print(("✓ " if cond else "✗ ") + msg)
    fail += not cond


def part_a():
    tel = {"telemetry": {"id": 2, "fields": [{"name": "t", "type": "uint32"}, {"name": "x", "type": "float"}]}}
    base = {"name": "g1", "type": "float", "default": 1, "min": 0, "max": 2}
    for bad in ("Kp", "p", "PID", 1, "feedforward"):
        errs = gen_link.check(tel, [dict(base, role=bad)])
        ok(len(errs) == 1 and "role 只能是" in errs[0], f"未知 role {bad!r} 被拒：{errs}")
    for good in gen_link.ROLES:
        ok(not gen_link.check(tel, [dict(base, role=good)]), f"role {good} 合法")
    s0 = gen_link.schema(tel, [base, dict(base, name="g2")])
    ok([p["role"] for p in s0["params"]] == [None, None], "没写 role → null")
    s1 = gen_link.schema(tel, [dict(base, role="P"), dict(base, name="g2", role="LIM")])
    ok([p["role"] for p in s1["params"]] == ["P", "LIM"], "写了 role 原样带出")
    ok(s0["hash"] == s1["hash"], "role 不进 schema 哈希")
    # 命令行：坏 role 退出非 0、打印中文原因
    with tempfile.TemporaryDirectory() as d:
        y = pathlib.Path(d) / "app.yaml"
        y.write_text(yaml.safe_dump({"link": {**tel, "params": [dict(base, role="Kp")]}}, allow_unicode=True), encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "tools/gen_link.py"), str(y), "--out", d], capture_output=True, text=True)
        ok(r.returncode != 0 and "role 只能是" in (r.stdout + r.stderr), f"gen_link 命令行拒绝坏 role（rc={r.returncode}）")


def part_bc(seeds):
    shutil.rmtree(HOME, ignore_errors=True)
    for seed in seeds:
        p = randplant.gen(seed)
        want = {nm: ro for ro, nm in p["roles"].items()}
        decl = yaml.safe_load(randplant.app_yaml(p))["link"]["params"]
        ok({q["name"]: q.get("role") for q in decl} == want and set(want.values()) <= set(gen_link.ROLES),
           f"seed {seed}：app.yaml role = 内部角色 {want}")
        bd = ROOT / "build/host-sim" / p["name"]                  # 同名仿真板别的测试也编（APP_DIR 不同）：前后都清，免得旧 .o 重复链接
        shutil.rmtree(bd, ignore_errors=True)
        randplant.write(p, HOME / "projects" / p["name"])
        exe, sch = tsr.build(p["name"])
        ok({q["name"]: q["role"] for q in sch["params"]} == want, f"seed {seed}：link_schema.json 参数 role 正确")
        _, fr = tsr.run(exe, ["600 end"])
        hb = [struct.unpack_from("<I", b, 0)[0] for _, k, _, b in fr if k == tsr.HB and len(b) >= 4]
        ok(bool(hb) and all(h == sch["hash"] for h in hb), f"seed {seed}：握手心跳 schema_hash 指向带 role 的这张表（{len(hb)} 帧）")
        shutil.rmtree(bd, ignore_errors=True)


def main() -> int:
    part_a()
    part_bc([int(s) for s in os.environ.get("RANDPLANT_SEEDS", "3 5 7 10 20").split()])
    print(f"{'✗' if fail else '✓'} 参数角色 role：失败 {fail}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
