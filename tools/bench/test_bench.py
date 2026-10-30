"""make bench 评分口径单测（不起仿真板）：python3 tools/bench/test_bench.py"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import bench

acc = {"band": 1.0, "t_max_s": 3.0}
assert bench.score(True, {"ok": True, "overshoot_pct": 0.0, "settling_s": 1.0}, {"pass": True}, acc)[0] == 100.0
assert bench.score(True, {"ok": True, "overshoot_pct": 50.0, "settling_s": 3.0}, {"pass": False}, acc)[0] == 20.0
assert bench.score(False, {"ok": False}, {"pass": False}, acc)[0] == 0.0
cfg = json.loads((bench.ROOT / "dzbench.json").read_text())["step_tests"]
for p in json.loads((bench.ROOT / "tools/bench/cases.json").read_text())["cases"]:
    assert (p.get("experiment") or p["app"]) in cfg and "band" in p["accept"], p
print("✓ bench 评分口径")
