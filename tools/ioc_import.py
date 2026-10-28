#!/usr/bin/env python3
"""ioc_import.py —— 把 CubeMX 的 .ioc 变成（或核对）board.yaml 的 resources，并检查 CubeMX 配置是否满足移植层前提。

CubeMX 是唯一配置源：引脚/时钟/DMA/中断都在 .ioc 里改，board.yaml 的 resources 只是它的“逻辑名视图”。

逻辑名来自 CubeMX 的 GPIO User Label（Pinout 视图里右键引脚 → Enter User Label）：
    GPIO_<名>             -> resources.gpio
    PWM_<名>              -> resources.pwm（定时器/通道取自引脚信号 S_TIMx_CHy）
    ENC_<名>_A / _B       -> resources.encoder（TIMx_CH1/CH2，Encoder_Interface）
    UART_<名>_TX / _RX    -> resources.uart
    ADC_<名>              -> resources.adc
    节拍定时器没有引脚：用 --timer CTRL=TIM6 指定，或沿用 --base 板卡里同实例的名字。

检查（错误 = 退出码 1）：
    T1 HAL 时基必须是 SysTick（pal_micros 依赖）       N1 NVIC 优先级分组必须为 4（全抢占）
    N2 节拍定时器/串口/串口 DMA 的中断必须打开          N3 SysTick 优先级数值应 ≤ 其它已开中断（警告）
    D1 DMA 数据流不得被两个请求共用                     D2 串口 RX 必须有 DMA 且为 Circular；TX DMA 应为 Normal
    L1 标签前缀/信号不匹配、UART 缺 TX/RX、ENC 缺 A/B    U1（--project）main.c 的 USER CODE 钩子齐全且无冲突回调

用法：
    ioc_import.py X.ioc --out board.yaml [--base 旧board.yaml] [--timer CTRL=TIM6]   生成
    ioc_import.py X.ioc --check board.yaml [--project CubeMX工程目录]                核对（CI 用）
    ioc_import.py --selftest                                                          用合成 .ioc 跑违规样例
"""
from __future__ import annotations

import argparse
import copy
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "boards/stm32f407-skystar-cubemx/cubemx/skystar.ioc"
APB2_TIMERS = {"TIM1", "TIM8", "TIM9", "TIM10", "TIM11", "TIM15", "TIM16", "TIM17", "TIM20"}


def parse_ioc(text: str) -> dict[str, str]:
    d = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        d[k.replace("\\ ", " ").strip()] = v.replace("\\:", ":").replace("\\ ", " ").strip()
    return d


class Rep:
    def __init__(self):
        self.errors: list[tuple[str, str]] = []
        self.warnings: list[str] = []

    def err(self, code, msg):
        self.errors.append((code, msg))

    def warn(self, msg):
        self.warnings.append(msg)


def _nvic(ioc, irq):
    v = ioc.get(f"NVIC.{irq}")
    if v is None:
        return None
    f = v.split(":")
    return {"enabled": f[0] == "true", "prio": int(f[1]) if len(f) > 1 and f[1].isdigit() else None}


def extract(ioc: dict, timers: dict[str, str], rep: Rep) -> tuple[dict, dict]:
    """返回 (resources, meta)。"""
    # ---- 时基 / NVIC 分组
    if "NVIC.TimeBase" in ioc or ioc.get("VP_SYS_VS_Systick.Mode") != "SysTick":
        rep.err("T1", f"HAL 时基不是 SysTick（NVIC.TimeBase={ioc.get('NVIC.TimeBase')}）：SYS > Timebase Source 选 SysTick")
    if ioc.get("NVIC.PriorityGroup") != "NVIC_PRIORITYGROUP_4":
        rep.err("N1", f"NVIC 优先级分组为 {ioc.get('NVIC.PriorityGroup')}，必须为 NVIC_PRIORITYGROUP_4")

    labels = {}  # label -> (pin, signal)
    for k, v in ioc.items():
        m = re.fullmatch(r"(P[A-K]\d{1,2})\.GPIO_Label", k)
        if m:
            labels[v] = (m[1], ioc.get(f"{m[1]}.Signal", ""))

    res = {t: [] for t in ("gpio", "pwm", "encoder", "uart", "timer", "adc")}
    enc: dict[str, dict] = {}
    uart: dict[str, dict] = {}
    tim_used: set[str] = set()
    for lab, (pin, sig) in sorted(labels.items(), key=lambda x: x[0]):
        if lab.startswith("GPIO_"):
            if not sig.startswith("GPIO_"):
                rep.err("L1", f"{pin} 标签 {lab} 但信号是 {sig}（应为 GPIO_Output/GPIO_Input）")
                continue
            r = {"name": lab[5:], "pin": pin, "dir": "out" if sig == "GPIO_Output" else "in"}
            res["gpio"].append(r)
        elif lab.startswith("PWM_"):
            m = re.fullmatch(r"S_(TIM\d+)_CH(\d)", sig)
            if not m:
                rep.err("L1", f"{pin} 标签 {lab} 但信号是 {sig}（应为 TIMx_CHy 的 PWM Generation）")
                continue
            tim, ch = m[1], int(m[2])
            tim_used.add(tim)
            r = {"name": lab[4:], "timer": tim, "channel": ch, "pin": pin}
            psc, arr = ioc.get(f"{tim}.Prescaler"), ioc.get(f"{tim}.Period")
            tclk = ioc.get("RCC.APB2TimFreq_Value" if tim in APB2_TIMERS else "RCC.APB1TimFreq_Value")
            if psc and arr and tclk and psc.isdigit() and arr.isdigit():
                r["freq_hz"] = round(int(tclk) / ((int(psc) + 1) * (int(arr) + 1)))
            else:
                r["freq_hz"] = "TODO"
                rep.warn(f"{lab}: .ioc 里读不到 {tim} 的 Prescaler/Period/时钟，freq_hz 记 TODO（仅用于文档，实际频率以 CubeMX 为准）")
            res["pwm"].append(r)
        elif lab.startswith("ENC_"):
            m = re.fullmatch(r"(.+)_([AB])", lab[4:])
            s = re.fullmatch(r"S_(TIM\d+)_CH([12])", sig)
            if not m or not s or ioc.get(f"SH.{sig}.0", "").split(",")[-1] != "Encoder_Interface":
                rep.err("L1", f"{pin} 标签 {lab}：应为 ENC_<名>_A/B 且信号为 TIMx_CH1/2 的 Encoder_Interface（实际 {sig}）")
                continue
            e = enc.setdefault(m[1], {"name": m[1], "timer": s[1]})
            if e["timer"] != s[1]:
                rep.err("L1", f"编码器 {m[1]} 的 A/B 在不同定时器上")
            e["pin_a" if m[2] == "A" else "pin_b"] = pin
            tim_used.add(s[1])
        elif lab.startswith("UART_"):
            m = re.fullmatch(r"(.+)_(TX|RX)", lab[5:])
            s = re.fullmatch(r"((?:LP)?U(?:S)?ART\d+)_(TX|RX)", sig)
            if not m or not s or m[2] != s[2]:
                rep.err("L1", f"{pin} 标签 {lab} 与信号 {sig} 不匹配（应为 UART_<名>_TX 对应 USARTx_TX）")
                continue
            u = uart.setdefault(m[1], {"name": m[1], "instance": s[1]})
            if u["instance"] != s[1]:
                rep.err("L1", f"串口 {m[1]} 的 TX/RX 在不同实例上")
            u[m[2].lower()] = pin
        elif lab.startswith("ADC_"):
            s = re.fullmatch(r"ADC(?:x|\d)_IN(\d+)", sig)
            if not s:
                rep.err("L1", f"{pin} 标签 {lab} 但信号是 {sig}")
                continue
            sh = ioc.get(f"SH.{sig}.0", "")
            inst = re.match(r"(ADC\d)", sh)
            res["adc"].append({"name": lab[4:], "instance": inst[1] if inst else "ADC1",
                               "channel": int(s[1]), "pin": pin})
        else:
            rep.warn(f"{pin} 标签 {lab} 没有约定前缀（GPIO_/PWM_/ENC_/UART_/ADC_），忽略")

    for e in enc.values():
        if "pin_a" not in e or "pin_b" not in e:
            rep.err("L1", f"编码器 {e['name']} 缺 A 或 B 相标签")
            continue
        flt = ioc.get(f"{e['timer']}.IC1Filter")
        if flt and flt.isdigit():
            e["filter"] = int(flt)
        res["encoder"].append(e)

    # ---- DMA
    streams: dict[str, str] = {}
    dma: dict[str, dict] = {}
    for k, v in ioc.items():
        m = re.fullmatch(r"Dma\.([A-Z0-9_]+)\.(\d+)\.(Instance|Mode|Direction)", k)
        if m:
            dma.setdefault(m[1], {})[m[3]] = v
    for req, d in sorted(dma.items()):
        s = d.get("Instance")
        if s in streams:
            rep.err("D1", f"DMA 冲突：{s} 同时分配给 {streams[s]} 和 {req}")
        elif s:
            streams[s] = req
    for u in uart.values():
        if "tx" not in u or "rx" not in u:
            rep.err("L1", f"串口 {u['name']} 缺 TX 或 RX 标签")
            continue
        inst = u["instance"]
        rx, tx = dma.get(f"{inst}_RX"), dma.get(f"{inst}_TX")
        if not rx:
            rep.err("D2", f"{inst}（{u['name']}）没有 RX DMA：DMA Settings 里 Add {inst}_RX，Mode=Circular")
        elif rx.get("Mode") != "DMA_CIRCULAR":
            rep.err("D2", f"{inst}_RX DMA 模式为 {rx.get('Mode')}，必须为 DMA_CIRCULAR")
        if tx and tx.get("Mode") != "DMA_NORMAL":
            rep.err("D2", f"{inst}_TX DMA 模式为 {tx.get('Mode')}，必须为 DMA_NORMAL")
        b = ioc.get(f"{inst}.BaudRate")
        u["baud"] = int(b) if b and b.isdigit() else 115200
        u["dma"] = True
        irq = f"{inst}_IRQn"
        n = _nvic(ioc, irq)
        if not n or not n["enabled"]:
            rep.err("N2", f"{irq} 未打开（HAL 的 DMA 收发回调需要串口中断）")
        for d in (rx, tx):
            if d and d.get("Instance"):
                n = _nvic(ioc, f"{d['Instance']}_IRQn")
                if not n or not n["enabled"]:
                    rep.err("N2", f"{d['Instance']}_IRQn 未打开")
        res["uart"].append(u)

    # ---- 节拍定时器
    for name, inst in sorted(timers.items()):
        if inst in tim_used:
            rep.err("L1", f"节拍定时器 {name}={inst} 已被 PWM/编码器占用")
        irqs = [k[5:] for k, v in ioc.items() if k.startswith("NVIC.") and re.match(rf"{inst}(_|$)", k[5:])
                or re.fullmatch(rf"NVIC\.TIM\d+_UP_{inst}_IRQn", k)]
        if not any(_nvic(ioc, i) and _nvic(ioc, i)["enabled"] for i in irqs):
            rep.err("N2", f"节拍定时器 {name}={inst} 的更新中断未打开（NVIC Settings 勾选 {inst} global interrupt）")
        n = next((_nvic(ioc, i) for i in irqs if _nvic(ioc, i)), None)
        r = {"name": name, "instance": inst}
        if n and n["prio"] is not None:
            r["irq_priority"] = n["prio"]
        res["timer"].append(r)

    # ---- 优先级关系
    st = _nvic(ioc, "SysTick_IRQn")
    if st and st["prio"] is not None:
        for k in ioc:
            if k.startswith("NVIC.") and k.endswith("_IRQn") and k != "NVIC.SysTick_IRQn":
                n = _nvic(ioc, k[5:])
                if n and n["enabled"] and n["prio"] is not None and n["prio"] < st["prio"]:
                    rep.warn(f"N3 {k[5:]} 优先级 {n['prio']} 高于 SysTick({st['prio']})：该中断里不能用 HAL_Delay/HAL 超时，"
                             f"且 pal_micros 依赖回绕补偿")

    meta = {"part": ioc.get("Mcu.UserName", "TODO"), "family": ioc.get("Mcu.Family", "").lower(),
            "hse_hz": int(ioc["RCC.HSE_VALUE"]) if ioc.get("RCC.HSE_VALUE", "").isdigit() else "TODO",
            "sysclk_hz": int(ioc["RCC.SYSCLKFreq_VALUE"]) if ioc.get("RCC.SYSCLKFreq_VALUE", "").isdigit() else "TODO"}
    return {k: v for k, v in res.items() if v}, meta


def check_project(proj: pathlib.Path, rep: Rep) -> None:
    main = proj / "Core/Src/main.c"
    if not main.exists():
        rep.err("U1", f"找不到 {main}")
        return
    t = main.read_text(encoding="utf-8", errors="replace")
    def block(tag):
        m = re.search(rf"/\* USER CODE BEGIN {tag} \*/(.*?)/\* USER CODE END {tag} \*/", t, re.S)
        return m[1] if m else ""
    if '#include "dz_cubemx.h"' not in block("Includes"):
        rep.err("U1", 'main.c 的 USER CODE Includes 里缺 #include "dz_cubemx.h"')
    if "dz_cubemx_start()" not in block("2"):
        rep.err("U1", "main.c 的 USER CODE 2 里缺 dz_cubemx_start();")
    if "dz_cubemx_loop()" not in block("3"):
        rep.err("U1", "main.c 的 USER CODE 3（while 循环内）缺 dz_cubemx_loop();")
    for f in (proj / "Core/Src").glob("*.c"):
        s = f.read_text(encoding="utf-8", errors="replace")
        for cb in ("HAL_TIM_PeriodElapsedCallback", "HAL_UART_RxCpltCallback", "HAL_UART_ErrorCallback"):
            if re.search(rf"^\s*void\s+{cb}\s*\(", s, re.M):
                rep.err("U1", f"{f.name} 定义了 {cb}，与 ports/stm32-cubemx 冲突：删掉，需要的逻辑放进子系统")


def build_board(res: dict, meta: dict, base: dict | None, ioc_rel: str) -> dict:
    b = copy.deepcopy(base) if base else {
        "schema_version": 1, "name": "TODO", "vendor": "TODO", "description": "由 tools/ioc_import.py 从 .ioc 生成",
        "toolchain": {"compiler": "arm-none-eabi-gcc", "flasher": "openocd", "openocd_interface": "TODO",
                      "openocd_target": "TODO"}}
    b["port"] = "stm32-cubemx"
    b["config_source"] = {"tool": "cubemx", "file": ioc_rel}
    mcu = b.setdefault("mcu", {})
    mcu["part"] = meta["part"]
    mcu["family"] = meta["family"]
    mcu.setdefault("core", "TODO")
    b["clock"] = {"hse_hz": meta["hse_hz"], "sysclk_hz": meta["sysclk_hz"]}
    old = (base or {}).get("resources") or {}
    out = {}
    for t, items in res.items():
        prev = {r["name"]: r for r in old.get(t) or []}
        merged = []
        for r in items:
            m = dict(prev.get(r["name"], {}))   # 保留 verified/note/invert/scale 等人工信息
            m.update(r)
            merged.append(m)
        out[t] = merged
    b["resources"] = out
    return b


KEYS = {"gpio": ("pin",), "pwm": ("timer", "channel", "pin"), "encoder": ("timer", "pin_a", "pin_b"),
        "uart": ("instance", "tx", "rx", "baud"), "timer": ("instance",), "adc": ("instance", "channel", "pin")}


def diff(res: dict, board: dict) -> list[str]:
    out = []
    have = board.get("resources") or {}
    for t in KEYS:
        a = {r["name"]: r for r in res.get(t, [])}
        b = {r["name"]: r for r in have.get(t) or []}
        for n in sorted(set(a) | set(b)):
            if n not in b:
                out.append(f"{t}.{n}: .ioc 有，board.yaml 没有")
            elif n not in a:
                out.append(f"{t}.{n}: board.yaml 有，.ioc 没有（或标签不符合约定）")
            else:
                for k in KEYS[t]:
                    if a[n].get(k) != b[n].get(k):
                        out.append(f"{t}.{n}.{k}: .ioc={a[n].get(k)!r}  board.yaml={b[n].get(k)!r}")
    return out


def run(ioc_path, timers, rep):
    return extract(parse_ioc(pathlib.Path(ioc_path).read_text(encoding="utf-8")), timers, rep)


def selftest() -> int:
    base = FIXTURE.read_text(encoding="utf-8")
    cases = {
        "ok": (lambda s: s, set()),
        "timebase_tim": (lambda s: s.replace("VP_SYS_VS_Systick.Mode=SysTick", "VP_SYS_VS_tim7.Mode=TIM7") + "NVIC.TimeBase=TIM7_IRQn\n", {"T1"}),
        "prio_group2": (lambda s: s.replace("NVIC_PRIORITYGROUP_4", "NVIC_PRIORITYGROUP_2"), {"N1"}),
        "dma_conflict": (lambda s: s.replace("Dma.USART2_RX.2.Instance=DMA1_Stream5", "Dma.USART2_RX.2.Instance=DMA2_Stream2"), {"D1"}),
        "rx_not_circular": (lambda s: s.replace("Dma.USART1_RX.0.Mode=DMA_CIRCULAR", "Dma.USART1_RX.0.Mode=DMA_NORMAL"), {"D2"}),
        "ctrl_irq_off": (lambda s: s.replace("NVIC.TIM6_DAC_IRQn=true", "NVIC.TIM6_DAC_IRQn=false"), {"N2"}),
        "bad_label": (lambda s: s.replace("PA8.GPIO_Label=PWM_MOTOR_A", "PA8.GPIO_Label=GPIO_MOTOR_A"), {"L1"}),
        "enc_missing_b": (lambda s: s.replace("PD13.GPIO_Label=ENC_MOTOR_A_B", "PD13.GPIO_Label=X"), {"L1"}),
    }
    bad = 0
    for name, (mut, want) in cases.items():
        rep = Rep()
        extract(parse_ioc(mut(base)), {"CTRL": "TIM6"}, rep)
        got = {c for c, _ in rep.errors}
        ok = got == want
        bad += not ok
        print(f"{'✓' if ok else '✗'} ioc_{name}: 期望 {sorted(want)}，实际 {sorted(got)}")
        if not ok:
            for e in rep.errors:
                print("     ", e)
    # 钩子检查
    rep = Rep()
    check_project(FIXTURE.parent, rep)
    ok = not rep.errors
    bad += not ok
    print(f"{'✓' if ok else '✗'} ioc_project_hooks: {rep.errors or '钩子齐全'}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ioc", nargs="?", type=pathlib.Path)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--out", type=pathlib.Path, help="写出 board.yaml")
    g.add_argument("--check", type=pathlib.Path, help="与已有 board.yaml 对比，不一致退出 1")
    ap.add_argument("--base", type=pathlib.Path, help="生成时保留其中的名称/说明/verified/note 等人工信息")
    ap.add_argument("--timer", action="append", default=[], help="节拍定时器 名=实例，如 CTRL=TIM6")
    ap.add_argument("--project", type=pathlib.Path, help="CubeMX 工程目录（检查 main.c 的 USER CODE 钩子）")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.ioc:
        ap.error("需要 .ioc 路径")
    ref = a.check or a.base
    ref_board = yaml.safe_load(ref.read_text(encoding="utf-8")) if ref and ref.exists() else None
    timers = dict(t.split("=", 1) for t in a.timer)
    if not timers and ref_board:
        timers = {r["name"]: r["instance"] for r in (ref_board.get("resources") or {}).get("timer") or []}
    rep = Rep()
    res, meta = run(a.ioc, timers, rep)
    if a.project:
        check_project(a.project, rep)
    for w in rep.warnings:
        print(f"警告  {w}")
    for c, e in rep.errors:
        print(f"错误  [{c}] {e}")
    if rep.errors:
        print(f"✗ {a.ioc}: {len(rep.errors)} 处错误")
        return 1
    if a.check:
        d = diff(res, ref_board)
        for x in d:
            print(f"不一致  {x}")
        print(f"{'✗' if d else '✓'} {a.ioc} vs {a.check}: {len(d)} 处不一致")
        return 1 if d else 0
    if a.out:
        rel = pathlib.Path(a.ioc).resolve().relative_to(a.out.resolve().parent).as_posix() \
            if pathlib.Path(a.ioc).resolve().is_relative_to(a.out.resolve().parent) else str(a.ioc)
        b = build_board(res, meta, ref_board, rel)
        a.out.write_text("# 由 tools/ioc_import.py 从 CubeMX .ioc 生成；引脚/实例请改 .ioc 后重新导入，"
                         "这里只手改 name/verified/note/invert/scale 等说明字段\n"
                         + yaml.safe_dump(b, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"✓ 已写出 {a.out}")
        return 0
    print(yaml.safe_dump({"resources": res, "meta": meta}, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
