#!/usr/bin/env python3
"""link.watchdog_ms（wd_timeout_ms）进 schema 哈希：同一份 yaml 只改看门狗 1500 → 2300，哈希必须不同；
不改则哈希逐位相同（可复现）；只给上位机看的字段（desc/default）改了哈希不变。make test 调用。"""
import copy, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import gen_link as G
fail = 0
ys = sorted(y for y in ROOT.glob("apps/*/app.yaml") if G.load(y)[0].get("telemetry"))
assert ys, "没有带 link 的应用"
for y in ys:
    spec, params, _ = G.load(y)
    a = copy.deepcopy(spec); a["watchdog_ms"] = 1500
    b = copy.deepcopy(spec); b["watchdog_ms"] = 2300
    ha, hb = G.schema(a, params)["hash"], G.schema(b, params)["hash"]
    ha2 = G.schema(copy.deepcopy(a), copy.deepcopy(params))["hash"]
    d = copy.deepcopy(spec); d.pop("watchdog_ms", None)
    hd = G.schema(d, params)["hash"]
    p2 = copy.deepcopy(params)
    for p in p2:
        p["desc"] = "改说明不改固件"
    hp = G.schema(a, p2)["hash"]
    if ha == hb:
        print(f"✗ [link/wdhash] {y.parent.name}: watchdog_ms 1500 与 2300 哈希相同 0x{ha:08X}"); fail = 1
    if ha != ha2:
        print(f"✗ [link/wdhash] {y.parent.name}: 同一份声明两次哈希不同"); fail = 1
    if hd != ha:
        print(f"✗ [link/wdhash] {y.parent.name}: 不写 watchdog_ms 应等同默认 {G.WD_DEFAULT_MS}"); fail = 1
    if hp != ha:
        print(f"✗ [link/wdhash] {y.parent.name}: 只改 desc 哈希就变了"); fail = 1
    if G.schema(b, params)["wd_timeout_ms"] != 2300:
        print(f"✗ [link/wdhash] {y.parent.name}: 握手 wd_timeout_ms 不是 2300"); fail = 1
if not fail:
    print(f"✓ watchdog_ms 进 schema 哈希（{len(ys)} 个应用：1500≠2300，不改则相同，desc 不进哈希）")
sys.exit(fail)
