#!/usr/bin/env python3
"""gen_syscfg.py —— alloc 草稿 board.yaml（MSPM0，引脚多为 TODO）→ .syscfg + ti_msp_dl_config.[ch] + 填好引脚的 board.yaml。

MSPM0 没有复用知识表，引脚交给 TI SysConfig 自己的求解器：
  第 1 遍：只写实例（不写 $assign 的让求解器分配），跑 SysConfig CLI，从 ti_msp_dl_config.h 读回实例 / 引脚；
  第 2 遍：把分到的引脚写成 $assign、PWM 实例按移植层约定改名 PWM_<定时器>，再生成一次（结果可复现，可在 GUI 打开核对）。
格式参照 boards/mspm0g3507-launchpad/ccs/launchpad.syscfg 与
refs/mspm0g-contest-skill/03_Fireware/*/empty.syscfg、refs/ext/nuedc-2026-h-ball-balance/firmware/beam_control/empty.syscfg（MIT）。
用法：gen_syscfg.py <alloc/board.yaml> <输出板目录> [--name N]
  输出：<目录>/board.yaml、ccs/<N>.syscfg、syscfg/ti_msp_dl_config.{c,h}
环境：SYSCFG_CLI（默认 third_party/sysconfig_1.28.0，其次 ~/ti/sysconfig_1.28.0）、M0_SDK_ROOT（默认 third_party/mspm0-sdk）。
【仿真】只在本机 SysConfig 1.28 + SDK 2.11 上生成并交叉编译过；未在 GUI 打开、未上板。
"""
import argparse, os, pathlib, re, subprocess, sys, tempfile
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
_LOCAL_CLI = REPO / "third_party/sysconfig_1.28.0/sysconfig_cli.sh"      # make fetch（tools/fetch_sysconfig.sh）装在这
CLI = pathlib.Path(os.environ.get("SYSCFG_CLI") or (_LOCAL_CLI if _LOCAL_CLI.exists() else pathlib.Path.home() / "ti/sysconfig_1.28.0/sysconfig_cli.sh"))
SDK = pathlib.Path(os.environ.get("M0_SDK_ROOT", REPO / "third_party/mspm0-sdk"))
T = lambda v: v in (None, "", "TODO")
HEAD = """/**
 * {name}：tools/gen_syscfg.py 由 alloc 草稿生成（SysConfig 求解器分配引脚，第 2 遍回写为 $assign）。
 * 【仿真】未在 SysConfig GUI 打开过、未上板；打开后若报冲突，以 GUI 为准改好再用 syscfg_import.py --check 回核 board.yaml。
 */
//@cliArgs --device "MSPM0G350X" --package "LQFP-64(PM)" --part "Default"
//@v2CliArgs --device "MSPM0G3507" --package "LQFP-64(PM)"
// @cliArgs --rtos nortos
"""


def script(r: dict, asg: dict, pwm_names: list) -> str:
    """r = board.yaml resources；asg = 上一遍读回的引脚（key → 引脚 / 外设）；pwm_names = 每组 PWM 实例名。"""
    L, mods = [], {}

    def inst(mod):
        if mod not in mods:
            L.append(f'const {mod} = scripting.addModule("/ti/driverlib/{mod}", {{}}, false);'); mods[mod] = 0
        mods[mod] += 1; v = f"{mod}{mods[mod]}"; L.append(f"const {v} = {mod}.addInstance();"); return v

    def pin(expr, key, val=None):
        p = val if not T(val) else asg.get(key)
        if p:
            L.append(f'{expr}.$assign = "{p}";')
    for g in r.get("gpio") or []:
        v = inst("GPIO"); n = g["name"]
        L += [f'{v}.$name = "GPIO_{n}";', f'{v}.associatedPins[0].$name = "{n}";']
        if g.get("dir") == "in":
            L.append(f'{v}.associatedPins[0].direction = "INPUT";')
            if g.get("pull"):
                L.append(f'{v}.associatedPins[0].internalResistor = "PULL_{g["pull"].upper()}";')
        pin(f"{v}.associatedPins[0].pin", f"gpio.{n}", g.get("pin"))
    for k, grp in enumerate(_pwm_groups(r)):
        v = inst("PWM"); f = grp[0].get("freq_hz") or 20000
        L += [f'{v}.$name = "{pwm_names[k]}";', f"{v}.timerCount = {32_000_000 // f};   /* 32 MHz / {f} Hz */",
              f"{v}.ccIndex = [{', '.join(str(i) for i in range(len(grp)))}];"]
        tim = asg.get(f"pwmgrp.{k}") or next((p["timer"] for p in grp if not T(p.get("timer"))), None)
        if tim:
            L.append(f'{v}.peripheral.$assign = "{tim}";')
        for i, p in enumerate(grp):
            pin(f"{v}.peripheral.ccp{i}Pin", f"pwm.{p['name']}", p.get("pin"))
    for k, e in enumerate(r.get("encoder") or []):
        n = e["name"]
        if k == 0 and e.get("mode") != "gpio_isr":          # G3507 只有 TIMG8 带 QEI：第一路给 QEI，其余走 GPIO 双边沿
            v = inst("QEI"); L += [f'{v}.$name = "ENC_{n}";', f'{v}.peripheral.$assign = "TIMG8";']
            pin(f"{v}.peripheral.ccp0Pin", f"enc.{n}.A", e.get("pin_a")); pin(f"{v}.peripheral.ccp1Pin", f"enc.{n}.B", e.get("pin_b"))
        else:
            v = inst("GPIO"); L += [f'{v}.$name = "ENC_{n}";', f"{v}.associatedPins.create(2);"]
            for i, ab in enumerate("AB"):
                L += [f'{v}.associatedPins[{i}].$name = "{ab}";', f'{v}.associatedPins[{i}].direction = "INPUT";',
                      f"{v}.associatedPins[{i}].interruptEn = true;", f'{v}.associatedPins[{i}].polarity = "RISE_FALL";']
                pin(f"{v}.associatedPins[{i}].pin", f"enc.{n}.{ab}", e.get("pin_" + ab.lower()))
    for u in r.get("uart") or []:
        v = inst("UART"); n = u["name"]
        L += [f'{v}.$name = "UART_{n}";', f"{v}.targetBaudRate = {u.get('baud') or 115200};", f'{v}.enabledInterrupts = ["RX"];']
        per = u.get("instance") if not T(u.get("instance")) else asg.get(f"uart.{n}")
        if per:
            L.append(f'{v}.peripheral.$assign = "{per}";')
        pin(f"{v}.peripheral.txPin", f"uart.{n}.tx", u.get("tx")); pin(f"{v}.peripheral.rxPin", f"uart.{n}.rx", u.get("rx"))
    for c in r.get("i2c") or []:
        v = inst("I2C"); n = c["name"]
        L += [f'{v}.$name = "I2C_{n}";', f"{v}.basicEnableController = true;"]
        per = c.get("instance") if not T(c.get("instance")) else asg.get(f"i2c.{n}")
        if per:
            L.append(f'{v}.peripheral.$assign = "{per}";')
        pin(f"{v}.peripheral.sclPin", f"i2c.{n}.scl", c.get("scl")); pin(f"{v}.peripheral.sdaPin", f"i2c.{n}.sda", c.get("sda"))
    for t in _timers(r):
        v = inst("TIMER"); n = t["name"]
        L += [f'{v}.$name = "TIMER_{n}";', f'{v}.timerMode = "PERIODIC";', f"{v}.timerClkPrescale = 32;   /* 1 MHz */",
              f'{v}.timerPeriod = "1 ms";', f'{v}.interrupts = ["ZERO"];']
        per = t.get("instance") if not T(t.get("instance")) else asg.get(f"timer.{n}")
        if per:
            L.append(f'{v}.peripheral.$assign = "{per}";')
    if r.get("dac"):                                          # DAC12 是单例模块，OUT0 = PA15（boardlib.check_dac 已拒绝别的实例 / 通道）
        L += ['const DAC12 = scripting.addModule("/ti/driverlib/DAC12");',
              "DAC12.dacOutputPinEn = true;", 'DAC12.dacAmplifier = "ON";', "DAC12.dacOutput12 = 0;"]
    L += ['const SYSCTL = scripting.addModule("/ti/driverlib/SYSCTL");', "SYSCTL.forceDefaultClkConfig = true;"]
    L += sysctl_extra(r)
    L += ['const ProjectConfig = scripting.addModule("/ti/project_config/ProjectConfig");', "ProjectConfig.genLinker = false;"]
    return "\n".join(L) + "\n"


def sysctl_extra(r: dict) -> list:
    """SYSCTL 里随外设自动打开的时钟：DAC12 必须有 MFPCLK（否则 SysConfig 报 "MFPCLK must be enabled when DAC12 peripheral is added"）。"""
    return ["SYSCTL.MFPCLKEn = true;   /* DAC12 需要 MFPCLK */"] if r.get("dac") else []


def _pwm_groups(r):
    """PWM 两路一组共用一个定时器（模板里已定定时器的按定时器分组）。"""
    ps = r.get("pwm") or []; fixed, free = {}, []
    for p in ps:
        (fixed.setdefault(p["timer"], []) if not T(p.get("timer")) else free).append(p)
    return list(fixed.values()) + [free[i:i + 2] for i in range(0, len(free), 2)]


def _timers(r):
    ts = list(r.get("timer") or [])
    return ts if any(t["name"] == "CTRL" for t in ts) else ts + [{"name": "CTRL"}]


def run_cli(text: str, wd: pathlib.Path) -> str:
    wd.mkdir(parents=True, exist_ok=True); sc = wd / "x.syscfg"; sc.write_text(text, encoding="utf-8")
    p = subprocess.run([str(CLI), "--product", str(SDK / ".metadata/product.json"), "--device", "MSPM0G350X", "--package", "LQFP-64(PM)",
                        "-o", str(wd / "o"), str(sc)], capture_output=True, text=True, timeout=600)
    h = wd / "o" / "ti_msp_dl_config.h"
    if not h.exists():
        sys.exit("✗ SysConfig 生成失败（资源可能不够分）：\n" + (p.stdout + p.stderr)[-3000:])
    return h.read_text(encoding="utf-8")


def readback(h: str, r: dict, pwm_tmp: list) -> dict:
    d = dict(re.findall(r"^#define\s+(\w+)\s+\(?([\w]+)\)?\s*$", h, re.M))
    pn = lambda port, pin: f"P{d[port][-1]}{int(d[pin].rsplit('_', 1)[1])}"
    a = {}
    for g in r.get("gpio") or []:
        n = g["name"]; a[f"gpio.{n}"] = pn(f"GPIO_{n}_PORT" if f"GPIO_{n}_PORT" in d else f"GPIO_{n}_{n}_PORT", f"GPIO_{n}_{n}_PIN")
    for k, grp in enumerate(_pwm_groups(r)):
        nm = pwm_tmp[k]; a[f"pwmgrp.{k}"] = d[f"{nm}_INST"]
        for i, p in enumerate(grp):
            a[f"pwm.{p['name']}"] = pn(f"GPIO_{nm}_C{i}_PORT", f"GPIO_{nm}_C{i}_PIN")
    for k, e in enumerate(r.get("encoder") or []):
        n = e["name"]
        if f"ENC_{n}_INST" in d:
            a[f"enc.{n}.A"] = pn(f"GPIO_ENC_{n}_PHA_PORT", f"GPIO_ENC_{n}_PHA_PIN"); a[f"enc.{n}.B"] = pn(f"GPIO_ENC_{n}_PHB_PORT", f"GPIO_ENC_{n}_PHB_PIN")
        else:
            for ab in "AB":
                g = f"ENC_{n}"                              # GPIO 组：<实例>_PORT / <实例>_<引脚>_PIN（跨端口时 <实例>_<引脚>_PORT）
                a[f"enc.{n}.{ab}"] = pn(f"{g}_PORT" if f"{g}_PORT" in d else f"{g}_{ab}_PORT", f"{g}_{ab}_PIN")
    for u in r.get("uart") or []:
        n = u["name"]; a[f"uart.{n}"] = d[f"UART_{n}_INST"]
        a[f"uart.{n}.tx"] = pn(f"GPIO_UART_{n}_TX_PORT", f"GPIO_UART_{n}_TX_PIN"); a[f"uart.{n}.rx"] = pn(f"GPIO_UART_{n}_RX_PORT", f"GPIO_UART_{n}_RX_PIN")
    for c in r.get("i2c") or []:
        n = c["name"]; a[f"i2c.{n}"] = d[f"I2C_{n}_INST"]
        a[f"i2c.{n}.scl"] = pn(f"GPIO_I2C_{n}_SCL_PORT", f"GPIO_I2C_{n}_SCL_PIN"); a[f"i2c.{n}.sda"] = pn(f"GPIO_I2C_{n}_SDA_PORT", f"GPIO_I2C_{n}_SDA_PIN")
    for t in _timers(r):
        a[f"timer.{t['name']}"] = d[f"TIMER_{t['name']}_INST"]
    return a


def fill(b: dict, a: dict, name: str) -> dict:
    r = b["resources"]
    for g in r.get("gpio") or []:
        g["pin"] = a[f"gpio.{g['name']}"]
    for k, grp in enumerate(_pwm_groups(r)):
        for i, p in enumerate(grp):
            p.update(timer=a[f"pwmgrp.{k}"], channel=i, pin=a[f"pwm.{p['name']}"])
    for k, e in enumerate(r.get("encoder") or []):
        e["pin_a"], e["pin_b"] = a[f"enc.{e['name']}.A"], a[f"enc.{e['name']}.B"]
        if k == 0 and e.get("mode") != "gpio_isr":
            e["timer"] = "TIMG8"; e.pop("mode", None)
        else:
            e.pop("timer", None); e["mode"] = "gpio_isr"
    for u in r.get("uart") or []:
        u.update(instance=a[f"uart.{u['name']}"], tx=a[f"uart.{u['name']}.tx"], rx=a[f"uart.{u['name']}.rx"], dma=False)
    for c in r.get("i2c") or []:
        c.update(instance=a[f"i2c.{c['name']}"], scl=a[f"i2c.{c['name']}.scl"], sda=a[f"i2c.{c['name']}.sda"])
    r["timer"] = [dict(t, instance=a[f"timer.{t['name']}"], clk_hz=1_000_000) for t in _timers(r)]
    b.update(name=name, config_source={"tool": "sysconfig", "file": f"ccs/{name}.syscfg"},
             clock={"sysclk_hz": 32_000_000}, toolchain={"compiler": "arm-none-eabi-gcc", "flasher": "xds110"})
    b["mcu"].setdefault("nvm_kb", 0)
    b["todo"] = ["【仿真】引脚由 SysConfig 求解器分配（tools/gen_syscfg.py），未在 GUI 打开、未上板：按实际接线核对后用 syscfg_import --check 回核"]
    b["description"] = (b.get("description") or "") + "；引脚由 gen_syscfg.py 经 SysConfig 求解器分配"
    return b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board"); ap.add_argument("out"); ap.add_argument("--name")
    x = ap.parse_args()
    b = yaml.safe_load(open(x.board, encoding="utf-8")); r = b.get("resources") or {}
    if (b.get("mcu") or {}).get("family") != "mspm0":
        sys.exit("✗ 只管 MSPM0（STM32 用 gen_ioc.py）")
    bad = [k for k in ("adc", "dac", "spi") if r.get(k)]
    if bad:
        sys.exit(f"✗ 还不会生成 {'/'.join(bad)}：在 SysConfig 里手配后用“导入已有工程”")
    if not CLI.exists():
        sys.exit(f"✗ 找不到 SysConfig CLI：{CLI}（在仓库根目录运行 make fetch 自动装 1.28，或设 SYSCFG_CLI）")
    out = pathlib.Path(x.out); name = x.name or out.name
    ng = len(_pwm_groups(r)); tmp = [f"PWM_G{k}" for k in range(ng)]
    with tempfile.TemporaryDirectory() as td:
        a = readback(run_cli(HEAD.format(name=name) + script(r, {}, tmp), pathlib.Path(td) / "p1"), r, tmp)
        final = HEAD.format(name=name) + script(r, a, [f"PWM_{a[f'pwmgrp.{k}']}" for k in range(ng)])
        run_cli(final, pathlib.Path(td) / "p2")
        (out / "ccs").mkdir(parents=True, exist_ok=True); (out / "syscfg").mkdir(exist_ok=True)
        (out / "ccs" / f"{name}.syscfg").write_text(final, encoding="utf-8")
        for f in ("ti_msp_dl_config.c", "ti_msp_dl_config.h"):
            (out / "syscfg" / f).write_text((pathlib.Path(td) / "p2/o" / f).read_text(encoding="utf-8"), encoding="utf-8")
    b = fill(b, a, name)
    (out / "board.yaml").write_text("# tools/gen_syscfg.py 生成：引脚由 SysConfig 求解器分配【仿真】\n" + yaml.safe_dump(b, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"✓ {out}/ccs/{name}.syscfg + syscfg/ti_msp_dl_config.[ch] + board.yaml（" + "，".join(f"{k}={v}" for k, v in a.items() if "." not in k[4:] or k.startswith("pwm.")) + "）")


if __name__ == "__main__":
    main()
