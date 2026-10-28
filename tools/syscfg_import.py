#!/usr/bin/env python3
"""syscfg_import.py —— TI SysConfig（.syscfg）→ board.yaml resources 的导入接口（第 0 阶段：接口 + 最小解析，未接 mspm0 移植层）。

MSPM0（嘉立创天猛星 MSPM0G3507）统一用 SysConfig + DriverLib：SysConfig 是唯一配置源，生成 ti_msp_dl_config.{c,h}；
将来的 ports/mspm0-driverlib 只包装其中的实例名（GPIO_LED_PIN_LED_PIN、PWM_MOTOR_A_INST…），与 CubeMX 流程同构。

命名约定（SysConfig 里每个实例的 Name 字段）：GPIO_<名> / PWM_<名> / ENC_<名> / UART_<名> / ADC_<名> / TIMER_<名>。

目前支持：GPIO（多引脚组）、PWM（ccp0..3）、UART、ENC（QEI 或 GPIO A/B）、TIMER；ADC 只报 TODO。
【部分验证】字段名（已用 SDK 2.11 官方例程 PWM/TIMER/QEI/GPIO 的 .syscfg 核对（tools/fixtures/syscfg/ti_*.syscfg）；
未用你本机 SysConfig 导出的文件核对。
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
        line = re.sub(r"/\*.*?\*/|//.*$", "", line)   # 行尾注释
        m = ASSIGN.match(line)
        if m and not line.lstrip().startswith(("const", "//", "*")):
            inst.setdefault(m[1], {})[m[2]] = m[3].strip().strip('"')
    return inst


def _int(v: str):
    return int(v) if v.isdigit() else "TODO"


def _pins(kv: dict) -> list[tuple[str, dict]]:
    """GPIO 组内的每个 associatedPins[i]：返回 (引脚名, 属性)。"""
    out: dict[int, dict] = {}
    for k, v in kv.items():
        m = re.match(r"associatedPins\[(\d+)\]\.(.+)", k)
        if m:
            out.setdefault(int(m[1]), {})[m[2]] = v
    for d in out.values():   # TI 例程常用 assignedPort/assignedPin（PORTA + "0"）而不是 pin.$assign
        if "pin.$assign" not in d and d.get("assignedPort", "").startswith("PORT") and d.get("assignedPin", "").isdigit():
            d["pin.$assign"] = "P" + d["assignedPort"][4:] + d["assignedPin"]
    return [(d.get("$name", f"PIN{i}"), d) for i, d in sorted(out.items())]


def extract(inst: dict) -> tuple[dict, list[str]]:
    """命名约定（新）：GPIO_<组> + 引脚名 → 逻辑名 <组>_<引脚>（宏 GPIO_<组>_<引脚>_PIN）；
    PWM_<定时器>（如 PWM_TIMG0）的 ccpN → <定时器>_CN，--check 时 PWM 按 timer+channel+pin 比对、不比名字（逻辑名在 board.yaml 里起）；ENC_<名> 可以是 QEI 模块（phA/phB 引脚）或 GPIO 组（引脚名含 A/B）；
    TIMER_<名> → timer 资源（周期 timerPeriod）。旧约定（GPIO_LED 单引脚、PWM_MOTOR_A 单通道）向下兼容。"""
    res: dict[str, list] = {}
    todo: list[str] = []
    for var, kv in inst.items():
        name = kv.get("$name", "")
        pre, _, logical = name.partition("_")
        if pre == "GPIO":
            for pn, d in _pins(kv):
                full = logical if pn in ("PIN", f"PIN_{logical}", logical) else f"{logical}_{pn}"
                res.setdefault("gpio", []).append({"name": full, "pin": d.get("pin.$assign", "TODO"),
                                                   "dir": "in" if d.get("direction") == "INPUT" else "out"})   # SysConfig 默认 OUTPUT
        elif pre == "PWM":
            chs = [c for c in range(4) if kv.get(f"peripheral.ccp{c}Pin.$assign")]
            for ch in chs:
                res.setdefault("pwm", []).append({
                    "name": f"{logical}_C{ch}", "timer": kv.get("peripheral.$assign", "TODO"),
                    "channel": ch, "pin": kv[f"peripheral.ccp{ch}Pin.$assign"],
                    **({"freq_hz": _int(kv["pwmClkFreq"])} if "pwmClkFreq" in kv else {})})   # 频率由时钟树决定，无此字段就不比
        elif pre == "UART":
            res.setdefault("uart", []).append({
                "name": logical, "instance": kv.get("peripheral.$assign", "TODO"),
                "tx": kv.get("peripheral.txPin.$assign", "TODO"), "rx": kv.get("peripheral.rxPin.$assign", "TODO"),
                "baud": _int(kv.get("targetBaudRate", ""))})
        elif pre in ("ENC", "QEI"):
            if "peripheral.ccp0Pin.$assign" in kv or "peripheral.phAPin.$assign" in kv:   # QEI
                a = kv.get("peripheral.phAPin.$assign") or kv.get("peripheral.ccp0Pin.$assign")
                b = kv.get("peripheral.phBPin.$assign") or kv.get("peripheral.ccp1Pin.$assign", "TODO")
                res.setdefault("encoder", []).append({"name": logical,
                                                      "timer": kv.get("peripheral.$assign", "TODO"), "pin_a": a, "pin_b": b})
            else:                                                                       # GPIO 中断 A/B 相
                ab = {pn.upper().rstrip("0123456789")[-1:]: d.get("pin.$assign", "TODO") for pn, d in _pins(kv)}
                if not {"A", "B"} <= ab.keys():
                    todo.append(f"{name}: GPIO 编码器引脚名需以 A/B 结尾")
                    continue
                res.setdefault("encoder", []).append({"name": logical, "mode": "gpio_isr", "pin_a": ab["A"], "pin_b": ab["B"]})
        elif pre == "TIMER":
            res.setdefault("timer", []).append({"name": logical, "instance": kv.get("peripheral.$assign", "TODO")})
        elif pre == "ADC":
            todo.append(f"{name}: ADC 导入未实现（需真实 .syscfg 样本）")
    return res, todo


def selftest() -> int:
    res, todo = extract(parse(FIXTURE.read_text(encoding="utf-8")))
    want = {"gpio": [{"name": "LED", "pin": "PA14", "dir": "out"},
                     {"name": "MOTOR_AIN1", "pin": "PA12", "dir": "out"},
                     {"name": "MOTOR_AIN2", "pin": "PA13", "dir": "out"}],
            "pwm": [{"name": "TIMA0_C0", "timer": "TIMA0", "channel": 0, "pin": "PA0", "freq_hz": 20000},
                    {"name": "TIMA0_C1", "timer": "TIMA0", "channel": 1, "pin": "PA1", "freq_hz": 20000}],
            "uart": [{"name": "LINK", "instance": "UART0", "tx": "PA10", "rx": "PA11", "baud": 115200}],
            "encoder": [{"name": "L", "timer": "TIMG8", "pin_a": "PA29", "pin_b": "PA30"},
                        {"name": "R", "mode": "gpio_isr", "pin_a": "PB4", "pin_b": "PB5"}],
            "timer": [{"name": "CTRL", "instance": "TIMG0"}]}
    ok = res == want and not todo
    # TI 官方 SDK 例程（BSD-3，原样拷贝）：验证真实导出格式
    r1, _ = extract(parse((FIXTURE.parent / "ti_pwm_edge_sleep.syscfg").read_text(encoding="utf-8")))
    r2, _ = extract(parse((FIXTURE.parent / "ti_periodic_sleep.syscfg").read_text(encoding="utf-8")))
    ok = ok and [(p["timer"], p["channel"], p["pin"]) for p in r1.get("pwm", [])] == [("TIMG0", 0, "PA12"), ("TIMG0", 1, "PA13")]
    ok = ok and r2.get("timer") == [{"name": "0", "instance": "TIMG0"}] and \
        [g["pin"] for g in r2.get("gpio", [])] == ["PA0", "PA15"]
    r3, _ = extract(parse((FIXTURE.parent / "ti_qei_mode.syscfg").read_text(encoding="utf-8")))
    ok = ok and r3.get("encoder") == [{"name": "0", "timer": "TIMG8", "pin_a": "PA29", "pin_b": "PA30"}]
    print(f"{'✓' if ok else '✗'} syscfg_synthetic+TI例程: {(res, todo) if not ok else 'GPIO/PWM/UART/ENC(QEI+GPIO)/TIMER 解析正确'}")
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
        def same(t, r, h):
            return all(h.get(k) == v for k, v in r.items() if not (t == "pwm" and k == "name"))
        bad = [f"{t}.{r['name']}" for t, rs in res.items() for r in rs
               if not any(same(t, r, h) for h in have.get(t) or [])]
        for b in bad:
            print(f"不一致  {b}")
        print(f"{'✗' if bad else '✓'} {a.syscfg} vs {a.check}")
        return 1 if bad else 0
    print(yaml.safe_dump({"resources": res}, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
