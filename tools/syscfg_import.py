#!/usr/bin/env python3
"""syscfg_import.py —— TI SysConfig（.syscfg）→ board.yaml resources 的导入接口（第 0 阶段：接口 + 最小解析，未接 mspm0 移植层）。

MSPM0（嘉立创天猛星 MSPM0G3507）统一用 SysConfig + DriverLib：SysConfig 是唯一配置源，生成 ti_msp_dl_config.{c,h}；
将来的 ports/mspm0-driverlib 只包装其中的实例名（GPIO_LED_PIN_LED_PIN、PWM_MOTOR_A_INST…），与 CubeMX 流程同构。

命名约定（SysConfig 里每个实例的 Name 字段）：GPIO_<名> / PWM_<名> / ENC_<名> / UART_<名> / ADC_<名> / TIMER_<名>。

目前支持：GPIO（单引脚）、PWM（ccp0/ccp1 引脚）、UART。ENC（QEI）、ADC、TIMER 只识别并报 TODO —— 需要真实 .syscfg 样本再补。
用法：
    syscfg_import.py X.syscfg                  打印解析出的 resources
    syscfg_import.py X.syscfg --check board.yaml
    syscfg_import.py --selftest
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tools/fixtures/syscfg/synthetic.syscfg"
ASSIGN = re.compile(r'^\s*(\w+)\.([\w\[\]\.\$]+)\s*=\s*(.+?);?\s*$')


def parse(text: str) -> dict[str, dict[str, str]]:
    inst: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        m = ASSIGN.match(line)
        if m and not line.lstrip().startswith(("const", "//", "*")):
            inst.setdefault(m[1], {})[m[2]] = m[3].strip().strip('"')
    return inst


def extract(inst: dict) -> tuple[dict, list[str]]:
    res: dict[str, list] = {}
    todo: list[str] = []
    for var, kv in inst.items():
        name = kv.get("$name", "")
        pre, _, logical = name.partition("_")
        if pre == "GPIO":
            pin = kv.get("associatedPins[0].pin.$assign", "TODO")
            d = "out" if kv.get("associatedPins[0].direction") == "OUTPUT" else "in"
            res.setdefault("gpio", []).append({"name": logical, "pin": pin, "dir": d})
        elif pre == "PWM":
            for ch in (0, 1):
                pin = kv.get(f"peripheral.ccp{ch}Pin.$assign")
                if pin:
                    res.setdefault("pwm", []).append({
                        "name": logical if ch == 0 else f"{logical}_CH1", "timer": kv.get("peripheral.$assign", "TODO"),
                        "channel": ch, "pin": pin, "freq_hz": int(kv["pwmClkFreq"]) if kv.get("pwmClkFreq", "").isdigit() else "TODO"})
        elif pre == "UART":
            b = kv.get("targetBaudRate", "")
            res.setdefault("uart", []).append({
                "name": logical, "instance": kv.get("peripheral.$assign", "TODO"),
                "tx": kv.get("peripheral.txPin.$assign", "TODO"), "rx": kv.get("peripheral.rxPin.$assign", "TODO"),
                "baud": int(b) if b.isdigit() else "TODO"})
        elif pre in ("ENC", "ADC", "TIMER"):
            todo.append(f"{name}: {pre} 导入未实现（需真实 .syscfg 样本）")
    return res, todo


def selftest() -> int:
    res, todo = extract(parse(FIXTURE.read_text(encoding="utf-8")))
    want = {"gpio": [{"name": "LED", "pin": "PA14", "dir": "out"}],
            "pwm": [{"name": "MOTOR_A", "timer": "TIMA0", "channel": 0, "pin": "PA0", "freq_hz": 20000}],
            "uart": [{"name": "LINK", "instance": "UART0", "tx": "PA10", "rx": "PA11", "baud": 115200}]}
    ok = res == want and not todo
    print(f"{'✓' if ok else '✗'} syscfg_synthetic: {res if not ok else 'GPIO/PWM/UART 解析正确'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("syscfg", nargs="?", type=pathlib.Path)
    ap.add_argument("--check", type=pathlib.Path)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.syscfg:
        ap.error("需要 .syscfg 路径")
    res, todo = extract(parse(a.syscfg.read_text(encoding="utf-8")))
    for t in todo:
        print(f"TODO  {t}")
    if a.check:
        have = (yaml.safe_load(a.check.read_text(encoding="utf-8")).get("resources") or {})
        bad = [f"{t}.{r['name']}" for t, rs in res.items() for r in rs
               if not any(all(h.get(k) == v for k, v in r.items()) for h in have.get(t) or [])]
        for b in bad:
            print(f"不一致  {b}")
        print(f"{'✗' if bad else '✓'} {a.syscfg} vs {a.check}")
        return 1 if bad else 0
    print(yaml.safe_dump({"resources": res}, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
