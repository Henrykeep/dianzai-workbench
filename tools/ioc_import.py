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
    D1 DMA 数据流不得被两个请求共用                     D2 串口 RX：Circular DMA 最佳；Normal DMA / 无 DMA(仅中断) 可用但给警告；TX DMA 应为 Normal
    L1 标签前缀/信号不匹配、UART 缺 TX/RX、ENC 缺 A/B    U1（--project）main.c 的 USER CODE 钩子齐全且无冲突回调

用法：
    ioc_import.py X.ioc --out board.yaml [--base 旧board.yaml] [--timer CTRL=TIM6]   生成
    ioc_import.py X.ioc --check board.yaml [--project CubeMX工程目录]                核对（CI 用）
    ioc_import.py --selftest                                                          用合成 .ioc 跑违规样例
"""
from __future__ import annotations

import argparse
import copy
import os
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from boardlib import stm32_flash_kb  # noqa: E402

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
        self.infos: list[str] = []

    def info(self, msg):
        self.infos.append(msg)

    def err(self, code, msg):
        self.errors.append((code, msg))

    def warn(self, msg):
        self.warnings.append(msg)


FAMILY_CORE = {"stm32f0": "cortex-m0", "stm32g0": "cortex-m0plus", "stm32f1": "cortex-m3", "stm32f2": "cortex-m3",
               "stm32f3": "cortex-m4f", "stm32f4": "cortex-m4f", "stm32g4": "cortex-m4f", "stm32l4": "cortex-m4f",
               "stm32f7": "cortex-m7f"}
PWM_MOTOR_MIN_HZ = 5000   # 低于此频率的非舵机 PWM 给警告（电机啸叫）


def _nvic(ioc, irq):
    v = ioc.get(f"NVIC.{irq}")
    if v is None:
        return None
    f = v.split(":")
    return {"enabled": f[0] == "true", "prio": int(f[1]) if len(f) > 1 and f[1].isdigit() else None}


CORE_EXC = {"NonMaskableInt_IRQn", "HardFault_IRQn", "MemoryManagement_IRQn", "BusFault_IRQn", "UsageFault_IRQn",
            "SVCall_IRQn", "DebugMonitor_IRQn", "PendSV_IRQn", "SysTick_IRQn"}
# CubeMX 不写入 .ioc 的默认 HSE_VALUE（只收录查证过的系列；其它系列缺省时记 TODO）
HSE_DEFAULT = {"stm32f1": 8_000_000, "stm32f4": 25_000_000}
PREFIXES = ("GPIO_", "PWM_", "ENC_", "UART_", "ADC_")
FREERTOS_MAX_SYSCALL_PRIO = 5   # CubeMX FreeRTOS 默认 configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY


def ioc_int(v):
    """CubeMX 数值字段可以是表达式，如 Period=2000-1、Prescaler=84-1。只接受整数与 + - * 。"""
    if v is None:
        return None
    v = v.strip()
    if re.fullmatch(r"\d+", v):
        return int(v)
    if re.fullmatch(r"\d+(\s*[-+*]\s*\d+)+", v):
        return int(eval(v, {"__builtins__": {}}))  # 已用正则限定为纯整数四则（无除法）
    return None


def norm_name(label: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_]", "_", label).upper().strip("_")
    if not n or not n[0].isalpha():
        n = "P_" + n
    return n[:32]


def pins_of(ioc: dict) -> dict[str, dict]:
    """收集每个物理引脚的属性。键里可能带复用后缀（PA0-WKUP、PC14-OSC32_IN），统一成 PA0/PC14。"""
    pins: dict[str, dict] = {}
    for k, v in ioc.items():
        m = re.fullmatch(r"(P[A-K]\d{1,2})(?:-[A-Za-z0-9_]+)?\.(Signal|GPIO_Label|GPIO_PuPd|Mode)", k)
        if m:
            pins.setdefault(m[1], {})[m[2]] = v
    return pins


def tim_mode(ioc, sig):
    """定时器通道模式：优先 SH.<信号>.0（CubeMX 真实工程总会写），缺省时看 TIMx.Channel-PWM GenerationN CHy。"""
    m = ioc.get(f"SH.{sig}.0", "").split(",")[-1]
    if m:
        return m
    t = re.fullmatch(r"S_(TIM\d+)_CH(\d)(?:_ETR)?", sig)
    if t and any(re.fullmatch(rf"{t[1]}\.Channel-PWM Generation\d CH{t[2]}", k) for k in ioc):
        return f"PWM Generation CH{t[2]}"
    return ""


def extract(ioc: dict, timers: dict[str, str], rep: Rep) -> tuple[dict, dict]:
    """返回 (resources, meta)。

    逻辑名优先取 User Label（约定前缀可强制类型），否则按引脚信号推断类型；没有标签的引脚用引脚号/外设实例
    作为名字并给出警告——导入永远把 .ioc 里真实用到的东西列出来，绝不静默丢弃。"""
    ips = {v for k, v in ioc.items() if re.fullmatch(r"Mcu\.IP\d+", k)}
    rtos = "FREERTOS" in ips
    family = ioc.get("Mcu.Family", "").lower()

    # ---- 时基 / NVIC 分组
    tb = ioc.get("NVIC.TimeBaseIP") or ("SysTick" if ioc.get("VP_SYS_VS_Systick.Mode") == "SysTick" else None)
    if tb is None:
        m = next((v for k, v in ioc.items() if re.fullmatch(r"VP_SYS_VS_tim\d+\.Mode", k)), None)
        tb = m if m and re.fullmatch(r"TIM\d+", m) else None
    if tb is None:
        rep.err("T1", f"认不出 HAL 时基（NVIC.TimeBase={ioc.get('NVIC.TimeBase')}）：SYS > Timebase Source 选 SysTick 或某个 TIMx")
    elif tb != "SysTick":
        # 移植层支持 TIM 时基：pal_micros 改读该定时器计数；main.c 里 CubeMX 生成的 HAL_TIM_PeriodElapsedCallback
        # 需在 USER CODE Callback 1 调 dz_cubemx_tim_callback(htim)（check_project 会核对）
        rep.info(f"HAL 时基是 {tb}（{'FreeRTOS 工程的推荐配置' if rtos else '裸机也可以，但 SysTick 更省一个定时器'}）："
                 f"移植层按 TIM 时基工作，main.c 的 HAL_TIM_PeriodElapsedCallback 里要调用 dz_cubemx_tim_callback(htim)")
    if ioc.get("NVIC.PriorityGroup") != "NVIC_PRIORITYGROUP_4":
        rep.err("N1", f"NVIC 优先级分组为 {ioc.get('NVIC.PriorityGroup')}，必须为 NVIC_PRIORITYGROUP_4")

    pins = pins_of(ioc)
    res = {t: [] for t in ("gpio", "pwm", "encoder", "uart", "timer", "adc")}
    enc: dict[str, dict] = {}       # timer -> {pins, labels}
    uart: dict[str, dict] = {}      # instance -> {tx, rx, labels}
    other: dict[str, list] = {}     # 暂不支持的外设实例 -> [(signal, pin)]
    tim_used: set[str] = set()
    names: dict[tuple, str] = {}

    def claim(kind, name, pin):
        if (kind, name) in names:
            rep.err("L1", f"{kind}.{name} 重名（{names[(kind, name)]} 和 {pin}）：在 CubeMX 里给其中一个改 User Label")
            return False
        names[(kind, name)] = pin
        return True

    for pin in sorted(pins, key=lambda p: (p[1], int(p[2:]))):
        p = pins[pin]
        sig, lab = p.get("Signal", ""), p.get("GPIO_Label")
        pre = next((x for x in PREFIXES if lab and lab.startswith(x)), None)
        base = norm_name(lab[len(pre):] if pre else lab) if lab else None
        tm = re.fullmatch(r"S_(TIM\d+)_CH(\d)(?:_ETR)?", sig)
        um = re.fullmatch(r"((?:LP)?U(?:S)?ART\d+)_(TX|RX)", sig)
        am = re.fullmatch(r"ADC(?:x|\d)_IN(\d+)", sig)

        if sig.startswith("GPIO_") and sig in ("GPIO_Output", "GPIO_Input"):
            if pre and pre != "GPIO_":
                rep.err("L1", f"{pin} 标签 {lab} 但信号是 {sig}（前缀 {pre} 要求对应外设信号）")
                continue
            name = base or pin
            if not lab:
                rep.warn(f"{pin} 是 {sig} 但没有 User Label，逻辑名暂用 {pin}（建议在 CubeMX 里补标签）")
            r = {"name": name, "pin": pin, "dir": "out" if sig == "GPIO_Output" else "in"}
            pull = {"GPIO_PULLUP": "up", "GPIO_PULLDOWN": "down"}.get(p.get("GPIO_PuPd", ""))
            if pull:
                r["pull"] = pull
            if claim("gpio", name, pin):
                res["gpio"].append(r)
        elif tm:
            tim, ch, mode = tm[1], int(tm[2]), tim_mode(ioc, sig)
            tim_used.add(tim)
            if pre == "GPIO_" or pre == "UART_" or pre == "ADC_":
                rep.err("L1", f"{pin} 标签 {lab} 但信号是 {sig}（{mode}）")
                continue
            if mode.startswith("PWM Generation") and pre != "ENC_":
                name = base or f"{tim}_CH{ch}"
                if not lab:
                    rep.warn(f"{pin}（{tim}_CH{ch} PWM）没有 User Label，逻辑名暂用 {name}")
                r = {"name": name, "timer": tim, "channel": ch, "pin": pin}
                psc, arr = ioc_int(ioc.get(f"{tim}.Prescaler")), ioc_int(ioc.get(f"{tim}.Period"))
                tclk = ioc_int(ioc.get("RCC.APB2TimFreq_Value" if tim in APB2_TIMERS else "RCC.APB1TimFreq_Value"))
                if psc is not None and arr is not None and tclk:
                    r["freq_hz"] = round(tclk / ((psc + 1) * (arr + 1)))
                    if r["freq_hz"] < PWM_MOTOR_MIN_HZ and "SERVO" not in name.upper():
                        rep.warn(f"{name}: PWM 只有 {r['freq_hz']} Hz——若驱动电机（TB6612 等），低于 {PWM_MOTOR_MIN_HZ} Hz "
                                 f"会有明显啸叫和电流纹波，建议 10~20 kHz（改 {tim} 的 Prescaler/Period）；舵机/LED 请忽略，"
                                 f"舵机建议标签写 PWM_SERVO_xxx")
                else:
                    r["freq_hz"] = "TODO"
                    rep.warn(f"{name}: .ioc 里读不到 {tim} 的 Prescaler/Period/时钟，freq_hz 记 TODO")
                if claim("pwm", name, pin):
                    res["pwm"].append(r)
            elif mode == "Encoder_Interface" and ch in (1, 2):
                e = enc.setdefault(tim, {"labels": {}})
                e["pin_a" if ch == 1 else "pin_b"] = pin
                if lab:
                    e["labels"][ch] = (pre, lab)
            else:
                rep.err("L1", f"{pin} 标签 {lab}：信号 {sig} 模式为 {mode or '未知'}"
                        + ("（ENC_ 标签要求 TIMx_CH1/2 的 Encoder_Interface）" if pre == "ENC_" else
                           "（输入捕获/输出比较等模式 resources 暂不支持）"))
        elif um:
            u = uart.setdefault(um[1], {"labels": []})
            u[um[2].lower()] = pin
            if lab:
                u["labels"].append((pre, lab, um[2]))
            if pre and pre != "UART_":
                rep.err("L1", f"{pin} 标签 {lab} 与信号 {sig} 不匹配")
        elif am:
            sh = ioc.get(f"SH.{sig}.0", "")
            inst = re.match(r"(ADC\d)", sh)
            name = base or f"ADC_IN{am[1]}"
            if claim("adc", name, pin):
                res["adc"].append({"name": name, "instance": inst[1] if inst else "ADC1", "channel": int(am[1]), "pin": pin})
        else:
            if pre:
                rep.err("L1", f"{pin} 标签 {lab} 但信号是 {sig}（与前缀 {pre} 不符）")
                continue
            m = re.match(r"([A-Z][A-Z0-9]*?\d+)_", sig)
            if m and not sig.startswith(("RCC_", "SYS_")):
                other.setdefault(m[1], []).append((sig, pin, lab))

    # ---- 编码器：标签 ENC_<名>_A/B，或任意标签的公共前缀，或定时器名
    for tim, e in sorted(enc.items()):
        if "pin_a" not in e or "pin_b" not in e:
            rep.err("L1", f"编码器 {tim} 缺 A 或 B 相（CH1/CH2 都要设为 Encoder_Interface）")
            continue
        labs = e["labels"]
        name = None
        if labs:
            if any(p == "ENC_" for p, _ in labs.values()):
                ms = {ch: re.fullmatch(r"ENC_(.+)_([AB])", l) for ch, (p, l) in labs.items()}
                if len(labs) < 2 or not all(ms.values()) or len({m[1] for m in ms.values()}) != 1 \
                        or {ch: m[2] for ch, m in ms.items()} != {1: "A", 2: "B"}:
                    rep.err("L1", f"编码器 {tim}：ENC_ 标签应为 ENC_<名>_A（CH1）/ENC_<名>_B（CH2），实际 "
                            f"{[l for _, l in labs.values()]}")
                    continue
                name = norm_name(next(iter(ms.values()))[1])
            else:
                ls = [l for _, l in labs.values()]
                cp = re.sub(r"[_\-]?[AB12]?$", "", os.path.commonprefix(ls)) if len(ls) == 2 else ""
                name = norm_name(cp) if cp else None
        if not name:
            name = tim
            rep.warn(f"编码器 {tim}（{e['pin_a']}/{e['pin_b']}）没有可用的 User Label，逻辑名暂用 {tim}"
                     f"（建议标 ENC_<名>_A / ENC_<名>_B）")
        r = {"name": name, "timer": tim, "pin_a": e["pin_a"], "pin_b": e["pin_b"]}
        flt = ioc_int(ioc.get(f"{tim}.IC1Filter"))
        if flt is not None:
            r["filter"] = flt
        if claim("encoder", name, tim):
            res["encoder"].append(r)

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

    # ---- 串口
    for inst, u in sorted(uart.items()):
        if "tx" not in u or "rx" not in u:
            rep.err("L1", f"串口 {inst} 只配了 {'TX' if 'tx' in u else 'RX'}（移植层要求 TX/RX 都在）")
            continue
        name = None
        uls = [(p, l, d) for p, l, d in u["labels"]]
        if uls:
            bases = set()
            for p, l, d in uls:
                m = re.fullmatch(r"(?:UART_)?(.+)_(TX|RX)", l)
                if not m or m[2] != d:
                    rep.err("L1", f"串口 {inst} 标签 {l} 与方向 {d} 不匹配（应为 UART_<名>_{d}）")
                    bases = None
                    break
                bases.add(m[1])
            if bases is None:
                continue
            if len(bases) != 1 or len(uls) != 2:
                rep.err("L1", f"串口 {inst} 的 TX/RX 标签不成对：{[l for _, l, _ in uls]}")
                continue
            name = norm_name(bases.pop())
        if not name:
            name = inst
            rep.warn(f"串口 {inst}（TX {u['tx']} / RX {u['rx']}）没有 User Label，逻辑名暂用 {inst}"
                     f"（建议标 UART_<名>_TX / UART_<名>_RX）")
        rx, tx = dma.get(f"{inst}_RX"), dma.get(f"{inst}_TX")
        if not rx:
            rep.warn(f"D2 {inst}（{name}）没有 RX DMA：移植层退化为逐字节中断接收（每字节一次中断，"
                         f"{ioc_int(ioc.get(f'{inst}.BaudRate')) or 115200} baud 时约 {(ioc_int(ioc.get(f'{inst}.BaudRate')) or 115200) // 10} 次/秒）；"
                         f"高波特率/大流量建议在 DMA Settings 里 Add {inst}_RX，Mode=Circular")
        elif rx.get("Mode") != "DMA_CIRCULAR":
            rep.warn(f"D2 {inst}_RX DMA 模式为 {rx.get('Mode')}：移植层在每次收满后自动重启 DMA（可用），"
                     f"重启期间新字节暂存在串口数据寄存器里，只要 DMA 完成中断被延迟不超过 1 个字节时间（115200 时约 87 µs）就不丢；"
                     f"改成 DMA_CIRCULAR 最稳")
        if tx and tx.get("Mode") != "DMA_NORMAL":
            rep.err("D2", f"{inst}_TX DMA 模式为 {tx.get('Mode')}，必须为 DMA_NORMAL")
        b = ioc_int(ioc.get(f"{inst}.BaudRate"))
        r = {"name": name, "instance": inst, "tx": u["tx"], "rx": u["rx"], "baud": b if b else 115200, "dma": bool(rx)}
        n = _nvic(ioc, f"{inst}_IRQn")
        if not n or not n["enabled"]:
            rep.err("N2", f"{inst}_IRQn 未打开（HAL 的 DMA 收发回调需要串口中断）")
        for d in (rx, tx):
            if d and d.get("Instance"):
                n = _nvic(ioc, f"{d['Instance']}_IRQn")
                if not n or not n["enabled"]:
                    rep.err("N2", f"{d['Instance']}_IRQn 未打开")
        if claim("uart", name, inst):
            res["uart"].append(r)

    # ---- 节拍定时器：显式指定的 + .ioc 里“开了更新中断、没有引脚、不是 HAL 时基”的定时器（自动发现）
    def tim_irqs(inst):
        return [k[5:] for k in ioc if k.startswith("NVIC.") and k.endswith("_IRQn")
                and (re.match(rf"NVIC\.{inst}(_|$)", k) or re.search(rf"_{inst}(_|$)", k[5:]))]
    named = set(timers.values())
    auto = {}
    for ip in sorted(ips):
        if re.fullmatch(r"TIM\d+", ip) and ip not in tim_used and ip not in named and ip != tb:
            if any(_nvic(ioc, i) and _nvic(ioc, i)["enabled"] for i in tim_irqs(ip)):
                auto[ip] = ip
                rep.warn(f"{ip} 没有引脚、开了中断，视为节拍定时器，逻辑名暂用 {ip}（用 --timer CTRL={ip} 改名）")
            else:
                rep.warn(f"{ip} 已启用但没有引脚也没有开中断，未纳入 resources（用途不明）")
    for name, inst in sorted(list(timers.items()) + list(auto.items())):
        if inst in tim_used:
            rep.err("L1", f"节拍定时器 {name}={inst} 已被 PWM/编码器占用")
        irqs = tim_irqs(inst)
        if not any(_nvic(ioc, i) and _nvic(ioc, i)["enabled"] for i in irqs):
            rep.err("N2", f"节拍定时器 {name}={inst} 的更新中断未打开（NVIC Settings 勾选 {inst} global interrupt）")
        n = next((_nvic(ioc, i) for i in irqs if _nvic(ioc, i)), None)
        r = {"name": name, "instance": inst}
        if n and n["prio"] is not None:
            r["irq_priority"] = n["prio"]
        psc, arr = ioc_int(ioc.get(f"{inst}.Prescaler")), ioc_int(ioc.get(f"{inst}.Period"))
        tclk = ioc_int(ioc.get("RCC.APB2TimFreq_Value" if inst in APB2_TIMERS else "RCC.APB1TimFreq_Value"))
        if psc is not None and arr is not None and tclk:
            r["note"] = f"按 .ioc 计算更新频率 {tclk / ((psc + 1) * (arr + 1)):g} Hz"
        if claim("timer", name, inst):
            res["timer"].append(r)

    # ---- 暂不支持的外设：列出来，不静默丢弃
    for inst, lst in sorted(other.items()):
        rep.info(f"{inst} 已配置（{', '.join(f'{s}={p}' for s, p, _ in lst)}），board.yaml 的 resources 暂无该类型，未导入")

    # ---- 中断优先级关系（只看外设中断，内核异常不算）
    st = _nvic(ioc, "SysTick_IRQn")
    hi, bad_rtos = [], []
    for k in sorted(ioc):
        if k.startswith("NVIC.") and k.endswith("_IRQn") and k[5:] not in CORE_EXC:
            n = _nvic(ioc, k[5:])
            if not n or not n["enabled"] or n["prio"] is None:
                continue
            if st and st["prio"] is not None and n["prio"] < st["prio"] and not rtos:
                hi.append(f"{k[5:]}={n['prio']}")
            if rtos and n["prio"] < FREERTOS_MAX_SYSCALL_PRIO:
                bad_rtos.append(f"{k[5:]}={n['prio']}")
    if hi:
        rep.warn(f"N3 这些中断优先级高于 SysTick({st['prio']})：{', '.join(hi)}——中断里不能用 HAL_Delay/带超时的 HAL 调用")
    if bad_rtos:
        rep.warn(f"R1 FreeRTOS：这些中断优先级数值 < {FREERTOS_MAX_SYSCALL_PRIO}（configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY），"
                 f"里面不能调用任何 FreeRTOS ...FromISR API：{', '.join(bad_rtos)}")

    # ---- 残留：functionlistsort 里有 MX_xxx_Init 但该外设已不在 IP 列表（CubeMX 删外设后常见）
    for m in re.finditer(r"\d+-MX_([A-Z0-9]+?)(?:_UART)?_Init-([A-Z0-9]+)-", ioc.get("ProjectManager.functionlistsort", "")):
        if m[2] not in ips and m[2] not in ("GPIO", "DMA"):
            rep.warn(f"ProjectManager.functionlistsort 里还有 MX_{m[1]}_Init，但 {m[2]} 已不在启用外设列表：可能是删掉外设后的残留，"
                     f"main.c 里若还调用 MX_{m[1]}_Init 会编译失败")

    # ---- 元信息
    hse = ioc_int(ioc.get("RCC.HSE_VALUE"))
    uses_hse = "HSE" in ioc.get("RCC.PLLSourceVirtual", "") or "HSE" in ioc.get("RCC.SYSCLKSource", "")
    hse_src = "ioc"
    if hse is None and uses_hse and family in HSE_DEFAULT:
        hse, hse_src = HSE_DEFAULT[family], "cubemx_default"
        rep.warn(f".ioc 没写 RCC.HSE_VALUE（CubeMX 只保存非默认值），按 {family} 默认 {hse} Hz；请对照板上晶振丝印确认")
    part = ioc.get("Mcu.CPN") or ioc.get("Mcu.UserName", "TODO")
    meta = {"part": part, "family": family, "package": ioc.get("Mcu.Package"),
            "flash_kb": stm32_flash_kb(part), "rtos": "freertos" if rtos else None,
            "hal_timebase": tb, "cubemx": ioc.get("MxCube.Version"), "fw": ioc.get("ProjectManager.FirmwarePackage"),
            "hse_hz": hse if hse is not None else ("TODO" if uses_hse else None), "hse_source": hse_src,
            "sysclk_hz": ioc_int(ioc.get("RCC.SYSCLKFreq_VALUE")) or "TODO",
            "unsupported": {k: [f"{s}={p}" for s, p, _ in v] for k, v in sorted(other.items())}}
    return {k: v for k, v in res.items() if v}, {k: v for k, v in meta.items() if v not in (None, {})}


def check_project(proj: pathlib.Path, rep: Rep, rtos: bool = False, tim_timebase: bool = False) -> None:
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
    if rtos:
        # FreeRTOS：osKernelStart() 之后 main 的 while 不再执行，app_loop 放进默认任务的循环
        fr = proj / "Core/Src/freertos.c"
        ft = fr.read_text(encoding="utf-8", errors="replace") if fr.exists() else ""
        m = re.search(r"/\* USER CODE BEGIN StartDefaultTask \*/(.*?)/\* USER CODE END StartDefaultTask \*/", ft, re.S)
        if "dz_cubemx_loop()" not in block("5") and not (m and "dz_cubemx_loop()" in m[1]):
            rep.err("U1", "FreeRTOS 工程：StartDefaultTask 的 for 循环里（main.c USER CODE 5 或 freertos.c USER CODE StartDefaultTask）"
                          "缺 dz_cubemx_loop(); osDelay(1);")
    elif "dz_cubemx_loop()" not in block("3"):
        rep.err("U1", "main.c 的 USER CODE 3（while 循环内）缺 dz_cubemx_loop();")
    for f in (proj / "Core/Src").glob("*.c"):
        s = f.read_text(encoding="utf-8", errors="replace")
        for cb in ("HAL_TIM_PeriodElapsedCallback", "HAL_UART_RxCpltCallback", "HAL_UART_ErrorCallback"):
            if re.search(rf"^\s*void\s+{cb}\s*\(", s, re.M):
                if cb == "HAL_TIM_PeriodElapsedCallback" and f.name == "main.c" and tim_timebase:
                    # TIM 时基工程：CubeMX 强制在 main.c 生成此回调（给 HAL_IncTick），移植层改由钩子接管
                    if "dz_cubemx_tim_callback(htim)" not in block("Callback 1"):
                        rep.err("U1", "main.c 的 HAL_TIM_PeriodElapsedCallback 里 USER CODE Callback 1 缺 dz_cubemx_tim_callback(htim);")
                    continue
                rep.err("U1", f"{f.name} 定义了 {cb}，与 ports/stm32-cubemx 冲突：删掉，需要的逻辑放进子系统")


def build_board(res: dict, meta: dict, base: dict | None, ioc_rel: str) -> dict:
    b = copy.deepcopy(base) if base else {
        "schema_version": 1, "name": "TODO", "vendor": "TODO", "description": "由 tools/ioc_import.py 从 .ioc 生成",
        "toolchain": {"compiler": "arm-none-eabi-gcc", "flasher": "openocd", "openocd_interface": "TODO",
                      "openocd_target": "TODO"}}
    b["port"] = "stm32-cubemx"
    b["config_source"] = {"tool": "cubemx", "file": ioc_rel,
                          **{k: meta[k] for k in ("hal_timebase", "rtos") if meta.get(k)}}
    mcu = b.setdefault("mcu", {})
    mcu["part"] = meta["part"]
    mcu["family"] = meta["family"]
    if mcu.get("core", "TODO") == "TODO":
        mcu["core"] = FAMILY_CORE.get(meta["family"], "TODO")
    if meta.get("flash_kb") and "variants" not in mcu:
        mcu["flash_kb"] = meta["flash_kb"]
    b["clock"] = {"hse_hz": meta.get("hse_hz", "TODO"), "sysclk_hz": meta["sysclk_hz"]}
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
        "timebase_tim": (lambda s: s.replace("VP_SYS_VS_Systick.Mode=SysTick", "VP_SYS_VS_tim7.Mode=TIM7") + "NVIC.TimeBase=TIM7_IRQn\n", set()),
        "timebase_unknown": (lambda s: s.replace("VP_SYS_VS_Systick.Mode=SysTick", "") + "NVIC.TimeBase=TIM7_IRQn\n", {"T1"}),
        "prio_group2": (lambda s: s.replace("NVIC_PRIORITYGROUP_4", "NVIC_PRIORITYGROUP_2"), {"N1"}),
        "dma_conflict": (lambda s: s.replace("Dma.USART2_RX.2.Instance=DMA1_Stream5", "Dma.USART2_RX.2.Instance=DMA2_Stream2"), {"D1"}),
        "rx_not_circular": (lambda s: s.replace("Dma.USART1_RX.0.Mode=DMA_CIRCULAR", "Dma.USART1_RX.0.Mode=DMA_NORMAL"), set()),
        "rx_no_dma_no_irq": (lambda s: s.replace("Dma.USART1_RX.0.", "X.").replace("NVIC.USART1_IRQn=true", "NVIC.USART1_IRQn=false"), {"N2"}),
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
        check_project(a.project, rep, rtos=bool(meta.get("rtos")),
                      tim_timebase=meta.get("hal_timebase", "SysTick") != "SysTick")
    if a.check and ref_board:
        cs = ref_board.get("config_source") or {}
        for k, dflt in (("hal_timebase", "SysTick"), ("rtos", None)):
            if meta.get(k, dflt) != cs.get(k, dflt):
                rep.err("T1", f"config_source.{k}: .ioc={meta.get(k, dflt)!r}  board.yaml={cs.get(k, dflt)!r}（重新导入或手改 board.yaml）")
    for i in rep.infos:
        print(f"信息  {i}")
    for w in rep.warnings:
        print(f"警告  {w}")
    if not (a.out or a.check):   # 只看清单：不论是否满足移植层前提，都先把 .ioc 里有什么列出来
        print(yaml.safe_dump({"resources": res, "meta": meta}, allow_unicode=True, sort_keys=False))
    for c, e in rep.errors:
        print(f"错误  [{c}] {e}")
    if rep.errors:
        print(f"✗ {a.ioc}: {len(rep.errors)} 处不满足移植层前提（上面的清单仍然有效）" if not (a.out or a.check)
              else f"✗ {a.ioc}: {len(rep.errors)} 处错误")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
