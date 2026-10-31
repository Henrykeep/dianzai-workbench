#!/usr/bin/env python3
"""link_schema.json：每个设定值通道（ref_for / 显式 hold）都带 hold，且与固件行为一致——
应用源码里有命令超时（cmd_timeout，超时目标归零）= timeout，否则设定值保持到改为止 = latched。hold 进哈希。"""
import pathlib, re, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import gen_link as G
fail = 0; rows = []
for y in sorted([*ROOT.glob("apps/*/app.yaml"), *ROOT.glob("examples/*/app.yaml")]):
    spec, params, _ = G.load(y)
    if not spec.get("telemetry"):
        continue
    sch = G.schema(spec, params)
    src = "".join(p.read_text(encoding="utf-8", errors="replace") for p in y.parent.glob("*.c"))
    want = "timeout" if re.search(r"\bcmd_timeout", src) else "latched"
    for f, raw in zip(sch["telemetry"]["fields"], spec["telemetry"]["fields"]):
        if not (raw.get("ref_for") or raw.get("hold")):
            continue
        rows.append(f"{y.parent.name}.{f['name']}={f.get('hold')}")
        if f.get("hold") != want:
            print(f"✗ [link/hold] {y.parent.name}.{f['name']}: hold={f.get('hold')}，固件行为是 {want}"); fail = 1
        if raw.get("hold") is None:
            print(f"✗ [link/hold] {y.parent.name}.{f['name']}: app.yaml 没写 hold（默认 timeout 不可靠，显式写）"); fail = 1
# 默认 timeout；hold 进哈希；非法值被拒
base = {"telemetry": {"fields": [{"name": "sp", "type": "float", "ref_for": "y"}, {"name": "y", "type": "float"}]}}
s0 = G.schema(base, [])
assert s0["telemetry"]["fields"][0]["hold"] == "timeout" and "hold" not in s0["telemetry"]["fields"][1]
base["telemetry"]["fields"][0]["hold"] = "latched"
assert G.schema(base, [])["hash"] != s0["hash"], "hold 不在哈希里"
base["telemetry"]["fields"][0]["hold"] = "forever"
assert any("hold" in e for e in G.check(base, [])), "非法 hold 未拒"
if not rows:
    print("✗ [link/hold] 没找到设定值通道"); fail = 1
if not fail:
    print("✓ link hold：" + "，".join(rows))
sys.exit(fail)
