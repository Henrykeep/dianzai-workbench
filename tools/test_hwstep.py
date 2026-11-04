#!/usr/bin/env python3
"""硬件步骤工具测试（随机通用工程，不针对任何题）：gen_wiring / power_check / alloc --mcu（任意 STM32）/ gen_config。
随机：从 tools/catalog/parts.yaml 抽主控 + 2–5 个外设拼 scheme.yaml；从 STM32_open_pin_data 抽型号。种子 DZ_SEED 或时间，失败时打印。"""
import csv, json, os, random, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SEED = int(os.environ.get("DZ_SEED") or time.time())
rng = random.Random(SEED)
fails = []


def run(*a, env=None):
    r = subprocess.run([PY, *map(str, a)], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, env=env, timeout=600)
    try:
        js = json.loads(r.stdout)
    except ValueError:
        js = None
    return r.returncode, js, r


def check(c, msg):
    if not c:
        fails.append(msg); print("FAIL", msg)


def rand_scheme():
    parts = yaml.safe_load((ROOT / "tools/catalog/parts.yaml").read_text(encoding="utf-8"))["parts"]
    mcus = [p for p in parts if p["kind"] == "mcu"]
    per = [p for p in parts if p["kind"] != "mcu" and p.get("res") and p.get("provides")]
    picks = {}
    for p in rng.sample(per, min(len(per), rng.randint(2, 5))):
        picks.setdefault(p["provides"][0], p["id"])
    return {"mcu": rng.choice(mcus)["id"], "picks": picks}


def main() -> int:
    print(f"test_hwstep seed={SEED}")
    tmp = Path(tempfile.mkdtemp(prefix="dz-hw-"))
    ok_runs = 0
    for i in range(6):
        sc = rand_scheme(); sp = tmp / f"s{i}.yaml"
        sp.write_text(yaml.safe_dump(sc, allow_unicode=True), encoding="utf-8")
        o = tmp / f"w{i}"
        code, js, r = run("tools/gen_wiring.py", sp, "-o", o, "--json")
        check(js is not None and js.get("exit") == code, f"gen_wiring --json 输出 {sc}: {r.stdout[-300:]} {r.stderr[-300:]}")
        check(code in (0, 1), f"gen_wiring 退出码 {code} {sc}: {r.stderr[-400:]}")
        if code != 0:
            continue  # 主控资源不够（随机组合合法地分不下）= 1，已校验输出格式
        ok_runs += 1
        for f in ("wiring.yml", "wiring.csv", "bom.csv", "wiring.svg", "wiring.png"):
            check((o / f).is_file() and (o / f).stat().st_size > 0, f"缺 {f} {sc}")
        rows = list(csv.DictReader((o / "wiring.csv").open(encoding="utf-8")))
        svg = (o / "wiring.svg").read_text(encoding="utf-8")
        check(len(rows) == js.get("wires"), "wiring.csv 行数 ≠ wires")
        for row in rows[:10]:
            pin = next((v for k, v in row.items() if "mcu" in k.lower() and re.fullmatch(r"P[A-Z]\d+", v or "")), None)
            check(pin is None or pin in svg, f"接线图里没有 {pin}")
        bom = list(csv.DictReader((o / "bom.csv").open(encoding="utf-8")))
        check(len(bom) >= len(sc["picks"]), "BOM 少件")
        code, js, r = run("tools/power_check.py", sp, "-o", tmp / f"p{i}", "--json")
        check(code in (0, 1) and js and js["exit"] == code, f"power_check {code} {r.stderr[-300:]}")
        check(js and all(js["load_ma"].get(k, 0) > 0 for k in ("3V3",)), "power_check 无负载统计")
        # 电流超限：3V3 轨能力压到 1 mA
        sc2 = dict(sc, power={"rails": {"3V3": 1}}); sp2 = tmp / f"r{i}.yaml"; sp2.write_text(yaml.safe_dump(sc2, allow_unicode=True), encoding="utf-8")
        code, js, _ = run("tools/power_check.py", sp2, "--json")
        check(code == 1 and any(x["code"] == "RAIL_BUDGET" for x in js["issues"]), "RAIL_BUDGET 没报")
        # 电平：所有外设改 5 V 信号、主控不耐 5 V → 至少一条 LEVEL_* error
        sc3 = dict(sc, elec={pid: {"io_v": 5.0, "vcc": 5.0} for pid in sc["picks"].values()}); sp3 = tmp / f"l{i}.yaml"
        sp3.write_text(yaml.safe_dump(sc3, allow_unicode=True), encoding="utf-8")
        code, js, _ = run("tools/power_check.py", sp3, "--json")
        check(code == 1 and any(x["code"] in ("LEVEL_OVERVOLT", "LEVEL_BIDIR") for x in js["issues"]), f"5 V 电平没报 {sc3}")
    check(ok_runs >= 1, "6 个随机方案一个都没分配成功")
    # alloc --mcu 任意 STM32（STM32_open_pin_data）
    xml = sorted((ROOT / "third_party/STM32_open_pin_data/mcu").glob("STM32*.xml"))
    check(len(xml) > 500, f"STM32_open_pin_data 没取到（make fetch 带 stm32pins）：{len(xml)}")
    base = tmp / "base.yaml"; base.write_text(yaml.safe_dump({"mcu": "stm32f407vet6", "picks": {"sense.wheel_speed": "encoder_ab"}}), encoding="utf-8")
    for x in rng.sample(xml, min(5, len(xml))):
        m = re.search(r'RefName="([^"]+)"', x.read_text(encoding="utf-8", errors="replace")[:4000])
        part = re.sub(r"\(.*?\)", lambda g: g.group(0)[1], m.group(1)).replace("x", "6") if m else x.stem
        code, js, r = run("tools/alloc.py", base, "--mcu", part, "-o", tmp / "al" / part, "--json")
        check(code in (0, 1) and js is not None, f"alloc --mcu {part} 退出 {code}: {r.stderr[-300:]}")
    code, js, _ = run("tools/alloc.py", base, "--mcu", "STM32G431CBT6", "-o", tmp / "g4", "--json")
    check(code == 0, "STM32G431CBT6 编码器应能分配")
    code, _, _ = run("tools/alloc.py", base, "--no-such-flag")
    check(code == 2, "坏参数应退 2")
    # gen_config：缺工具 → 3；SysConfig 有 → 0
    env = dict(os.environ, STM32CUBEMX=str(tmp / "nope"), PATH=os.path.dirname(PY))
    code, js, _ = run("tools/gen_config.py", "cubemx", base, "-o", tmp / "cx", "--json", env=env)
    check(code == 3 and js and js["exit"] == 3, f"无 CubeMX 应退 3，实际 {code}")
    syscfg = ROOT / "boards/mspm0g3507-launchpad/ccs/launchpad.syscfg"
    code, js, r = run("tools/gen_config.py", "sysconfig", syscfg, "-o", tmp / "sc", "--json")
    check(code == 0 and any((tmp / "sc").iterdir()), f"SysConfig 生成失败 {code}: {r.stdout[-400:]} {r.stderr[-400:]}")
    shutil.rmtree(tmp, ignore_errors=True)
    print(("FAILED " if fails else "OK ") + f"test_hwstep seed={SEED} 成功方案 {ok_runs}/6")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
