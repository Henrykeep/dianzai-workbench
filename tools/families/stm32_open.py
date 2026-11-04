"""任意 STM32 的资源知识表：直接读 ST 官方 STM32_open_pin_data（BSD-3，CubeMX 同源，tools/fetch_third_party.sh stm32pins 拉取）
的 mcu/<RefName>.xml，生成与 families/stm32f4.py 同形状的表（TIMERS、TIMER_CH_PINS、UARTS、I2CS、SPIS、ADC_CH_PINS…），
交给 alloc.py 的 Stm32Alloc 分配。只用 XML 里的「引脚 ↔ 信号」关系；AF 号、DMA 映射不在这份数据里，由 CubeMX 生成时定。"""
from __future__ import annotations

import functools
import os
import pathlib
import re
import types
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[2]
NS = "{http://dummy.com}"


def data_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DZ_STM32_PINDATA") or ROOT / "third_party/STM32_open_pin_data") / "mcu"


def _ref_re(ref: str) -> re.Pattern:
    out = ""
    for tok in re.findall(r"\([^)]*\)|.", ref):
        out += "[" + "".join(re.escape(c) for c in tok[1:-1].split("-")) + "]" if tok.startswith("(") else ("." if tok == "x" else re.escape(tok))
    return re.compile(out + "$", re.I)


@functools.lru_cache(maxsize=None)
def index() -> dict[str, pathlib.Path]:
    d = data_dir()
    return {p.stem: p for p in sorted(d.glob("STM32*.xml"))} if d.is_dir() else {}


def find(part: str) -> pathlib.Path | None:
    """器件型号（STM32G431CBT6 / STM32F407VETx）→ XML。末位温度/包装后缀可省。"""
    part = part.upper().strip()
    hits = [p for ref, p in index().items() if _ref_re(ref).match(part) or _ref_re(ref).match(part[:-1] + "X") or _ref_re(ref).match(part + "X")]
    return hits[0] if hits else None


@functools.lru_cache(maxsize=None)
def load(part: str) -> types.SimpleNamespace | None:
    x = find(part)
    if not x:
        return None
    root = ET.parse(x).getroot()
    freq = int(float(root.findtext(f"{NS}Frequency") or 72)) * 1_000_000
    pins: dict[str, list[str]] = {}
    for p in root.iter(f"{NS}Pin"):
        if p.get("Type") != "I/O":
            continue
        name = p.get("Name").split("-")[0].split(" ")[0].split("/")[0]
        if re.match(r"^P[A-Z]\d{1,2}$", name):
            pins[name] = [s.get("Name") for s in p.iter(f"{NS}Signal")]
    sig: dict[str, list[str]] = {}
    for pin, ss in pins.items():
        for s in ss:
            sig.setdefault(s, []).append(pin)
    tch: dict[tuple, list] = {}
    for s, ps in sig.items():
        m = re.match(r"^(TIM\d+)_CH(\d)$", s)
        if m:
            tch[(m.group(1), int(m.group(2)))] = ps
    tims = {}
    for t in sorted({k[0] for k in tch}, key=lambda t: int(t[3:])):
        chs = {c for (tt, c) in tch if tt == t}
        tims[t] = ("APB2" if t in ("TIM1", "TIM8", "TIM15", "TIM16", "TIM17", "TIM20") else "APB1",
                   32 if t in ("TIM2", "TIM5") else 16, {1, 2} <= chs, True, f"{t}_IRQ")
    for s in sig:  # 基本定时器（无通道引脚）不在 Signal 里：按 IP 列表补
        pass
    for ip in root.iter(f"{NS}IP"):
        inst = ip.get("InstanceName", "")
        if re.match(r"^TIM(6|7)$", inst):
            tims.setdefault(inst, ("APB1", 16, False, False, f"{inst}_IRQ"))
    def per(prefix_re, a, b, c=None):
        out = {}
        insts = sorted({m.group(1) for s in sig for m in [re.match(prefix_re, s)] if m})
        for i in insts:
            xs = [sig.get(f"{i}_{a}", []), sig.get(f"{i}_{b}", [])] + ([sig.get(f"{i}_{c}", [])] if c else [])
            if all(xs):
                out[i] = xs
        return out
    uarts = {i: (0, "APB2" if i in ("USART1", "USART6") else "APB1", v[0], v[1], f"{i}_IRQ")
             for i, v in per(r"^((?:US|U)ART\d+)_", "TX", "RX").items()}
    i2cs = {i: ("APB1", v[0], v[1]) for i, v in per(r"^(I2C\d+)_", "SCL", "SDA").items()}
    spis = {i: (0, "APB2" if i == "SPI1" else "APB1", v[0], v[1], v[2]) for i, v in per(r"^(SPI\d+)_", "SCK", "MISO", "MOSI").items()}
    adc = {}
    for s, ps in sig.items():
        m = re.match(r"^ADC1?_IN(\d+)$", s) or re.match(r"^ADC1_IN[NP]?(\d+)$", s)
        if m and int(m.group(1)) not in adc:
            adc[int(m.group(1))] = ps[0]
    swd = {p: f for p, f in (("PA13", "SWDIO"), ("PA14", "SWCLK")) if p in pins}
    reserved = {p: f"{f}（占用后无法用 SWD 下载/调试）" for p, f in swd.items()}
    for pin, ss in pins.items():
        if any(s.startswith("RCC_OSC") for s in ss):
            reserved[pin] = "晶振脚（" + ",".join(s for s in ss if s.startswith("RCC_OSC")) + "）"
    ports = "".join(sorted({p[1] for p in pins}))
    return types.SimpleNamespace(
        REF=x.stem, FAMILY=root.get("Family"), PACKAGE=root.get("Package"), SOURCE="STM32_open_pin_data/" + x.name,
        TIMERS=tims, TIMER_CH_PINS=tch, UARTS=uarts, I2CS=i2cs, SPIS=spis, ADC_CH_PINS=dict(sorted(adc.items())), ADCS=["ADC1"],
        UART_DMA_RX={}, UART_DMA_TX={}, SWD_PINS=swd, RESERVED_PINS=reserved, GPIO_PINS=sorted(pins, key=lambda p: (p[1], int(p[2:]))),
        PIN_RE=re.compile(rf"^P([{ports}])(1[0-5]|[0-9])$"), TIM_CLK={"APB1": freq, "APB2": freq}, SYSCLK=freq)
