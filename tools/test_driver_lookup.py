#!/usr/bin/env python3
"""tools/driver_lookup.py 自测：--json 输出与退出码（0 找到 / 1 没找到 / 2 参数错 / 3 缺索引），索引与生成结果一致。"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
T = [sys.executable, str(ROOT / "tools/driver_lookup.py")]


def run(*a, env=None):
    r = subprocess.run([*T, *a], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout


def main() -> int:
    fails = []
    rc, out = run("ADC", "--json"); d = json.loads(out)
    if rc != 0 or not d["ok"] or not all(x["path"] is None or x["path"].startswith("firmware/drivers/") for x in d["results"]): fails.append("ADC 查询")
    if not any(x["part"] == "ADS1115" and x["compile"]["mspm0"] in ("pass", "fail") for x in d["results"]): fails.append("ADS1115 无编译状态")
    rc, out = run("no-such-part-xyz", "--json")
    if rc != 1 or json.loads(out)["ok"]: fails.append("未命中应退出 1")
    rc, out = run("--json")
    if rc != 2 or json.loads(out)["reason"] != "bad_args": fails.append("无参数应退出 2")
    rc, _ = run("--check")
    if rc != 0: fails.append("driver_index.json 过期")
    idx = ROOT / "firmware/drivers/driver_index.json"; bak = idx.read_bytes()
    try:
        idx.unlink(); rc, out = run("ADC", "--json")
        if rc != 3 or json.loads(out)["reason"] != "missing_dependency": fails.append("缺索引应退出 3")
    finally:
        idx.write_bytes(bak)
    print("test_driver_lookup:", "FAIL " + "; ".join(fails) if fails else "ok")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
