#!/usr/bin/env python3
"""第 3 步 资源分配：scheme.yaml（第 2 步）→ 资源需求 → 按芯片知识表自动分配 → board.yaml 草稿 + CubeMX 配置清单。

  python3 tools/alloc.py examples/2026H_ball/scheme.yaml -o out/ [--app app.yaml] [--fixed 现有board.yaml] [--name 板名]

  需求：选定件在 tools/catalog/parts.yaml 里的 res（逻辑名按 docs/05 标签约定；scheme.yaml 的 names 可覆盖），
        外加 1 路 LINK 调试串口（scheme.yaml debug_link_uart: false 可关）。offboard 的能力不占主控资源。
  分配：只对有知识表的系列自动分配（stm32f4 LQFP100、stm32f1 LQFP48，表在 tools/families/，与 validate_board 同一份）；
        其他系列（mspm0 等）输出需求清单和全 TODO 的草稿，引脚由人在 CubeMX/SysConfig 里定。
  --fixed：已有板子/PCB 的 board.yaml——同类型同名的资源原样沿用（接线已焊死），只给剩下的分配。
  校验：草稿交给 boardlib.check_board（+ --app 时 check_requires），**和 validate_board 是同一个检查**，这里不另写规则。

输出：board.yaml（草稿，顶部注明来源）、cubemx.md（逐项配置：引脚/User Label、定时器 PSC/ARR、编码器模式、
      串口 DMA 数据流、NVIC 优先级）、alloc.md（需求 → 分配结果表）。
"""
from __future__ import annotations

import argparse
import re
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import boardlib  # noqa: E402
import scheme as sch  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
TODO = "TODO"


# ── 需求 ─────────────────────────────────────────────────────────
def demands(s: dict, parts: dict) -> list[dict]:
    """[{type, name, part, ...参数}]，按逻辑名去重（同一件提供两个能力只算一次）。"""
    off = set(s.get("offboard", []))
    seen_parts, out, names = set(), [], set()
    for need, pid in s.get("picks", {}).items():
        if need in off or pid in seen_parts or pid not in parts:
            continue
        seen_parts.add(pid)
        over = (s.get("names") or {}).get(pid, {})
        for r in parts[pid].get("res", []):
            for k, n in enumerate(over.get(r["type"], r["names"])):
                key = (r["type"], n)
                if key in names:
                    raise ValueError(f"逻辑名冲突：{r['type']}.{n} 被两个件使用（scheme.yaml names 里改名）")
                names.add(key)
                out.append({**{k2: v for k2, v in r.items() if k2 != "names"}, "name": n, "part": pid})
    if s.get("debug_link_uart", True):
        out.append({"type": "uart", "name": "LINK", "baud": 115200, "irq": 5, "part": "调试链路（工作台）"})
    return out


# ── STM32 分配器（表驱动：families/stm32f4.py、stm32f1.py 同形状） ─────────────
# 偏好顺序：编码器先用通用定时器，把高级定时器 TIM1/8 留给 PWM；不存在的定时器/串口自动跳过
ENC_ORDER = ["TIM3", "TIM4", "TIM5", "TIM2", "TIM8", "TIM1"]
PWM_ORDER = ["TIM1", "TIM8", "TIM2", "TIM5", "TIM9", "TIM12", "TIM3", "TIM4", "TIM10", "TIM11", "TIM13", "TIM14"]
UART_ORDER = ["USART2", "USART3", "UART4", "UART5", "USART6", "USART1"]
F4_GPIO_ORDER = [f"P{p}{i}" for p in "EDCBA" for i in range(16)]   # F4 LQFP100：PE/PD 少有复用冲突
FAMILIES = ("stm32f4", "stm32f1")


class Stm32Alloc:
    def __init__(self, fam: str, board: dict):
        import importlib
        F = self.F = importlib.import_module(f"families.{fam}")
        self.fam, self.pins, self.tims, self.tgroup, self.dma = fam, set(F.RESERVED_PINS), {}, {}, {}
        self.uarts, self.i2c, self.spi, self.used_ch = set(), set(), set(), set()
        self.take(*(board.get("reserved_pins") or {}))
        if hasattr(F, "GPIO_PINS"):   # 普通 GPIO 先用不带外设复用的脚，坑脚（JTAG/PC13）最后
            af = {p for ps in F.TIMER_CH_PINS.values() for p in ps} | {p for u in F.UARTS.values() for p in u[2] + u[3]} \
                 | set(F.ADC_CH_PINS.values())
            trap = set(getattr(F, "TRAP_PINS", {}))
            self.gpio_order = sorted(F.GPIO_PINS, key=lambda p: (p in trap, p in af))
        else:
            self.gpio_order = F4_GPIO_ORDER

    # 引脚
    def take(self, *ps):
        self.pins.update(p for p in ps if p and p != TODO)

    def free(self, p):
        return p not in self.pins and bool(self.F.PIN_RE.match(p)) and (self.fam != "stm32f4" or p[1] in "ABCDE")

    # 定时器重映射组：F1 是整组（TIMER_REMAP），F4 每通道任选 → 一组、每通道多个候选
    def groups(self, tim):
        if hasattr(self.F, "TIMER_REMAP"):
            gs = [{c: [p] for c, p in g.items()} for g in self.F.TIMER_REMAP.get(tim, [])]
        else:
            gs = [{c: self.F.TIMER_CH_PINS.get((tim, c), []) for c in (1, 2, 3, 4)}]
        if tim in self.tgroup:
            return [gs[self.tgroup[tim]]]
        return gs

    def pairs(self, remap_attr, inst, *lists):
        if hasattr(self.F, remap_attr):
            return list(getattr(self.F, remap_attr)[inst])
        import itertools
        return list(itertools.product(*lists))

    def _lock_group(self, tim, used: dict):
        if hasattr(self.F, "TIMER_REMAP"):
            for i, g in enumerate(self.F.TIMER_REMAP.get(tim, [])):
                if all(g.get(c) == p for c, p in used.items()):
                    self.tgroup[tim] = i
                    return

    def seed(self, t: str, r: dict):
        """--fixed 沿用的资源先占位。"""
        for k in ("pin", "pin_a", "pin_b", "tx", "rx", "scl", "sda", "sck", "mosi", "miso", "cs"):
            self.take(r.get(k))
        if t == "encoder" and r.get("timer") not in (None, TODO):
            self.tims[r["timer"]] = ("enc", None); self._lock_group(r["timer"], {1: r["pin_a"], 2: r["pin_b"]})
        if t == "pwm" and r.get("timer") not in (None, TODO):
            self.tims.setdefault(r["timer"], ("pwm", r["freq_hz"])); self.used_ch.add((r["timer"], r["channel"]))
            self._lock_group(r["timer"], {r["channel"]: r["pin"]})
        if t == "timer":
            self.tims.setdefault(r["instance"], ("base", None))
        for kind, store in (("uart", self.uarts), ("i2c", self.i2c), ("spi", self.spi)):
            if t == kind:
                store.add(r["instance"])

    def encoder(self, d):
        for tim in ENC_ORDER:
            if tim in self.tims or tim not in self.F.TIMERS or not self.F.TIMERS[tim][2]:
                continue
            for gi, g in enumerate(self.groups(tim)):
                for a in g.get(1, []):
                    for b in g.get(2, []):
                        if self.free(a) and self.free(b):
                            self.tims[tim] = ("enc", None); self.take(a, b); self._lock_group(tim, {1: a, 2: b})
                            return {"name": d["name"], "timer": tim, "pin_a": a, "pin_b": b}
        return None

    def pwm_group(self, ds):
        """同一件的 PWM 放同一个定时器（频率相同、同步更新），且在同一重映射组内。"""
        f = ds[0]["freq_hz"]
        for tim in PWM_ORDER:
            st = self.tims.get(tim)
            if tim not in self.F.TIMERS or (st and st != ("pwm", f)):
                continue
            for g in self.groups(tim):
                got, taken = [], set()
                for d in ds:
                    for ch in (1, 2, 3, 4):
                        if (tim, ch) in self.used_ch or (tim, ch) in taken:
                            continue
                        pin = next((p for p in g.get(ch, []) if self.free(p) and p not in {x["pin"] for x in got}), None)
                        if pin:
                            got.append({"name": d["name"], "timer": tim, "channel": ch, "pin": pin, "freq_hz": f}); taken.add((tim, ch))
                            break
                if len(got) == len(ds):
                    self.tims[tim] = ("pwm", f); self.used_ch |= taken
                    self.take(*[x["pin"] for x in got]); self._lock_group(tim, {x["channel"]: x["pin"] for x in got})
                    return got
        return None

    def uart(self, d):
        for inst in UART_ORDER:
            if inst in self.uarts or inst not in self.F.UARTS:
                continue
            _, _, txs, rxs, _ = self.F.UARTS[inst]
            for tx, rx in self.pairs("UART_REMAP", inst, txs, rxs):
                if self.free(tx) and self.free(rx):
                    self.uarts.add(inst); self.take(tx, rx)
                    return {"name": d["name"], "instance": inst, "tx": tx, "rx": rx, "baud": d.get("baud", 115200)}
        return None

    def i2c_bus(self, d):
        for inst, (_, scls, sdas) in self.F.I2CS.items():
            if inst in self.i2c:
                continue
            for a, b in self.pairs("I2C_REMAP", inst, scls, sdas):
                if self.free(a) and self.free(b):
                    self.i2c.add(inst); self.take(a, b)
                    return {"name": d["name"], "instance": inst, "scl": a, "sda": b, "speed_hz": d.get("speed_hz", 400000)}
        return None

    def spi_dev(self, d):
        bus = getattr(self, "_spi_bus", {})
        self._spi_bus = bus
        for inst, (_, _, scks, misos, mosis) in self.F.SPIS.items():
            if inst in self.spi and inst not in bus:
                continue
            if inst not in bus:
                cand = [c for c in self.pairs("SPI_REMAP", inst, scks, misos, mosis) if all(self.free(x) for x in c)]
                if not cand:
                    continue
                self.take(*cand[0]); self.spi.add(inst); bus[inst] = cand[0]
            sck, miso, mosi = bus[inst]
            return {"name": d["name"], "instance": inst, "sck": sck, "miso": miso, "mosi": mosi, "cs": self.gpio_pin()}
        return None

    def adc(self, d):
        for ch, pin in self.F.ADC_CH_PINS.items():
            if self.free(pin):
                self.take(pin)
                return {"name": d["name"], "instance": "ADC1", "channel": ch, "pin": pin}
        return None

    def gpio_pin(self):
        for p in self.gpio_order:
            if self.free(p):
                self.take(p)
                return p
        return None

    def rx_dma(self, inst):
        for c in self.F.UART_DMA_RX.get(inst, []):
            if c[:2] not in self.dma:
                self.dma[c[:2]] = inst
                return c
        return None

    def tim_clk(self, tim):
        if hasattr(self.F, "TIM_CLK"):
            return self.F.TIM_CLK[self.F.TIMERS[tim][0]]
        return 168_000_000 if self.F.TIMERS[tim][0] == "APB2" else 84_000_000   # F407 168 MHz：APB2 84→定时器×2，APB1 42→×2

    def sysclk(self):
        return getattr(self.F, "SYSCLK", 168_000_000)


def allocate(s: dict, parts: dict, fixed: dict | None, name: str) -> tuple[dict, list[str], dict]:
    mpart = parts[s["mcu"]]
    mcu = dict(mpart.get("mcu") or {"family": TODO, "part": TODO})
    ds = demands(s, parts)
    fam = mcu.get("family")
    notes: list[str] = []
    res: dict[str, list] = {}
    fixed_res = (fixed or {}).get("resources", {}) or {}
    fixed_names = {(t, r["name"]): r for t in boardlib.RES_TYPES for r in fixed_res.get(t, []) or []}
    alloc = Stm32Alloc(fam, fixed or {}) if fam in FAMILIES else None
    pending = []
    for d in ds:
        hit = fixed_names.get((d["type"], d["name"]))
        if hit:
            res.setdefault(d["type"], []).append(dict(hit)); d["from"] = "沿用"
            if alloc:
                alloc.seed(d["type"], hit)
        else:
            pending.append(d)
    if fixed and alloc:   # 现有板上其他资源（没被需求用到的）也占着脚
        for t in boardlib.RES_TYPES:
            for r in fixed_res.get(t, []) or []:
                if (t, r["name"]) not in {(d["type"], d["name"]) for d in ds}:
                    alloc.seed(t, r)
    order = {"encoder": 0, "pwm": 1, "uart": 2, "spi": 3, "i2c": 4, "adc": 5, "gpio": 6}
    pending.sort(key=lambda d: order[d["type"]])
    done_pwm_parts = set()
    for d in pending:
        t, got = d["type"], None
        if alloc:
            if t == "pwm":
                if d["part"] in done_pwm_parts:
                    continue
                grp = [x for x in pending if x["type"] == "pwm" and x["part"] == d["part"]]
                g = alloc.pwm_group(grp)
                done_pwm_parts.add(d["part"])
                if g:
                    res.setdefault("pwm", []).extend(g)
                    for x in grp:
                        x["from"] = "分配"
                    continue
                for x in grp:
                    res.setdefault("pwm", []).append({"name": x["name"], "timer": TODO, "channel": TODO, "pin": TODO, "freq_hz": x["freq_hz"]})
                    x["from"] = "失败"
                notes.append(f"PWM {[x['name'] for x in grp]}：找不到一个能同时放下的定时器")
                continue
            got = {"encoder": alloc.encoder, "uart": alloc.uart, "i2c": alloc.i2c_bus, "spi": alloc.spi_dev, "adc": alloc.adc}.get(t, lambda _d: None)(d)
            if t == "gpio":
                p = alloc.gpio_pin()
                got = {"name": d["name"], "pin": p, "dir": d.get("dir", "out")} if p else None
                if got and d.get("dir") == "in":
                    got["pull"] = "up"
        if got:
            d["from"] = "分配"
        else:
            d["from"] = "失败" if alloc else "待人工"
            got = {"name": d["name"], **{"gpio": {"pin": TODO, "dir": d.get("dir", "out")},
                   "pwm": {"timer": TODO, "channel": TODO, "pin": TODO, "freq_hz": d.get("freq_hz", 20000)},
                   "encoder": {"timer": TODO, "pin_a": TODO, "pin_b": TODO},
                   "uart": {"instance": TODO, "tx": TODO, "rx": TODO, "baud": d.get("baud", 115200)},
                   "i2c": {"instance": TODO, "scl": TODO, "sda": TODO}, "adc": {"instance": TODO, "channel": TODO, "pin": TODO},
                   "spi": {"instance": TODO, "sck": TODO, "mosi": TODO, "miso": TODO, "cs": TODO}}[t]}
            if alloc:
                notes.append(f"{t}.{d['name']}：资源用完了，没分到")
        if t == "i2c" and any(r.get("instance") == got.get("instance") and got.get("instance") != TODO for r in res.get("i2c", [])):
            continue   # 同一条总线只写一条（boardlib 规则）——实际不会发生：每个 i2c 需求单独一条总线
        res.setdefault(t, []).append(got)
    if not alloc:
        notes.append(f"{fam} 系列没有复用知识表，未自动分配：引脚在 {'SysConfig' if fam == 'mspm0' else 'CubeMX'} 里定，再导入（ioc_import / syscfg_import）")
    board = {"schema_version": 1, "name": name, "description": f"tools/alloc.py 由 {s.get('_src', 'scheme.yaml')} 生成的草稿，未接线、未上板",
             "port": "mspm0-driverlib" if fam == "mspm0" else "stm32-cubemx",
             "config_source": {"tool": "sysconfig" if fam == "mspm0" else "cubemx", "file": TODO},
             "mcu": mcu, "todo": ["草稿：按 cubemx.md 在 CubeMX 里配一遍、生成后用 ioc_import 重新导出 board.yaml 覆盖本文件"] + notes,
             "resources": res}
    if alloc:
        board["clock"] = {"hse_hz": 8_000_000 if fam == "stm32f1" else TODO, "sysclk_hz": alloc.sysclk()}
    extra = {"ds": ds, "alloc": alloc}
    return board, notes, extra


# ── 输出 ─────────────────────────────────────────────────────────
def cubemx_md(board: dict, extra: dict, rtos: bool) -> str:
    al, res, ds = extra["alloc"], board["resources"], extra["ds"]
    irq = {d["name"]: d.get("irq") for d in ds if d["type"] == "uart"}
    base = 5 if rtos else 0      # FreeRTOS：configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY=5，调 RTOS API 的中断必须 ≥5
    L = [f"# CubeMX 配置清单（{board['mcu'].get('part')}）", "",
         "> tools/alloc.py 生成。按顺序做完再 GENERATE；User Label 必须和逻辑名一致（docs/05 标签约定），之后 `tools/ioc_import.py` 导出 board.yaml、`make ioc-check` 核对。", ""]
    if not al:
        L += ["**本系列没有自动分配**：下面只列需求，引脚自己定。", "", "| 类型 | 逻辑名 | 参数 |", "|---|---|---|"]
        L += [f"| {d['type']} | {d['name']} | {', '.join(f'{k}={v}' for k, v in d.items() if k not in ('type', 'name', 'part', 'from'))} |" for d in ds]
        return "\n".join(L) + "\n"
    clk_txt = ("HCLK = 72 MHz（APB1 36 MHz、定时器 ×2 = 72 MHz；APB2 72 MHz）" if al.fam == "stm32f1"
               else "HCLK = 168 MHz（APB1 42 MHz / APB2 84 MHz，定时器时钟各 ×2）")
    L += ["## 1. System Core", "", f"- RCC：HSE = Crystal/Ceramic Resonator；Clock Configuration 里 {clk_txt}",
          "- SYS：Debug = Serial Wire（PA13/PA14 保留给 ST-Link / DAPLink" + ("；F1 这样还会释放 PA15/PB3/PB4 的 JTAG 功能）" if al.fam == "stm32f1" else "）") + ("；Timebase Source 选一个空闲定时器（用了 FreeRTOS 时不要用 SysTick）" if rtos else ""),
          "- NVIC：Priority Group = 4 bits pre-emption（docs/11）", ""]
    L += ["## 2. 引脚与外设", "", "| 引脚 | 功能 | User Label |", "|---|---|---|"]
    for r in res.get("gpio", []):
        L.append(f"| {r['pin']} | GPIO_{'Input（上拉）' if r['dir'] == 'in' else 'Output'} | {r['name']} |")
    for r in res.get("pwm", []):
        L.append(f"| {r['pin']} | {r['timer']}_CH{r['channel']} | {r['name']} |")
    for r in res.get("encoder", []):
        L += [f"| {r['pin_a']} | {r['timer']}_CH1 | {r['name']}_A |", f"| {r['pin_b']} | {r['timer']}_CH2 | {r['name']}_B |"]
    for r in res.get("uart", []):
        L += [f"| {r['tx']} | {r['instance']}_TX | {r['name']}_TX |", f"| {r['rx']} | {r['instance']}_RX | {r['name']}_RX |"]
    for r in res.get("i2c", []):
        L += [f"| {r['scl']} | {r['instance']}_SCL | {r['name']}_SCL |", f"| {r['sda']} | {r['instance']}_SDA | {r['name']}_SDA |"]
    for r in res.get("spi", []):
        L += [f"| {r['sck']}/{r['miso']}/{r['mosi']} | {r['instance']} SCK/MISO/MOSI | — |", f"| {r['cs']} | GPIO_Output（片选） | {r['name']}_CS |"]
    for r in res.get("adc", []):
        L.append(f"| {r['pin']} | {r['instance']}_IN{r['channel']} | {r['name']} |")
    L += ["", "## 3. 定时器", "", "| 定时器 | 模式 | 参数 |", "|---|---|---|"]
    for tim in sorted({r["timer"] for r in res.get("pwm", []) if r["timer"] != TODO}):
        f = next(r["freq_hz"] for r in res["pwm"] if r["timer"] == tim)
        clk = al.tim_clk(tim); bits = al.F.TIMERS[tim][1]
        psc = 0
        while clk // (psc + 1) // f - 1 > (2 ** bits - 1):
            psc += 1
        arr = clk // (psc + 1) // f - 1
        chs = ", ".join(f"CH{r['channel']}" for r in res["pwm"] if r["timer"] == tim)
        L.append(f"| {tim} | PWM Generation {chs} | 时钟 {clk // 1_000_000} MHz → Prescaler={psc}，Counter Period={arr}（{f} Hz，占空分辨率 {arr + 1} 级）；auto-reload preload Enable |")
    for r in res.get("encoder", []):
        L.append(f"| {r['timer']} | Combined Channels = Encoder Mode TI1 and TI2 | Counter Period={2 ** al.F.TIMERS[r['timer']][1] - 1}；Input Filter 6–10（抗电机干扰）；{r['name']} |")
    L += ["", "## 4. 串口、DMA 与中断优先级", "", "| 串口 | 逻辑名 | 波特率 | RX DMA（Circular） | NVIC 抢占优先级 |", "|---|---|---|---|---|"]
    for r in sorted(res.get("uart", []), key=lambda r: irq.get(r["name"]) or 9):
        dma = al.rx_dma(r["instance"]) if r["instance"] != TODO else None
        dtxt = f"DMA{dma[0]} Stream{dma[1]} Channel{dma[2]}" if dma else "无空闲数据流 → 中断接收"
        pr = (irq.get(r["name"]) if irq.get(r["name"]) is not None else 6) + base
        L.append(f"| {r['instance']} | {r['name']} | {r['baud']} | {dtxt}；同时开 {r['instance']} global interrupt（IDLE 断帧） | {min(pr, 15)} |")
    L += ["", "优先级规则（数字小 = 先响应）：执行器链路（如 QD4310）> 视觉 > 姿态 > 调试链路 > 其他；控制节拍定时器比所有串口高一级。"
          + (" 用了 FreeRTOS：所有调 RTOS API 的中断 ≥ 5（configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY），表中已整体 +5。" if rtos else ""),
          "", "## 5. Project Manager", "", "- Toolchain/IDE：MDK-ARM（Keil）或 STM32CubeIDE / Makefile（EIDE）；Code Generator 勾选 “Generate peripheral initialization as a pair of .c/.h”", ""]
    return "\n".join(L) + "\n"


def alloc_md(board: dict, extra: dict, rep) -> str:
    L = ["# 资源分配结果", "", "| 类型 | 逻辑名 | 来自 | 结果 |", "|---|---|---|---|"]
    idx = {(t, r["name"]): r for t, rs in board["resources"].items() for r in rs}
    for d in extra["ds"]:
        r = idx.get((d["type"], d["name"]), {})
        L.append(f"| {d['type']} | {d['name']} | {d['part']} | {d.get('from')}：{', '.join(f'{k}={v}' for k, v in r.items() if k != 'name')} |")
    L += ["", f"校验（boardlib.check_board，与 validate_board 相同）：错误 {len(rep.errors)} / 警告 {len(rep.warnings)} / TODO {len(rep.todos)}"]
    L += [f"- 错误：{e}" for e in rep.errors] + [f"- 警告：{w}" for w in rep.warnings]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scheme"); ap.add_argument("-o", required=True); ap.add_argument("--app"); ap.add_argument("--fixed")
    ap.add_argument("--name"); ap.add_argument("--rtos", action="store_true", help="用 FreeRTOS：中断优先级整体 ≥5")
    ns = ap.parse_args(argv)
    sp = pathlib.Path(ns.scheme)
    s = yaml.safe_load(sp.read_text(encoding="utf-8")); s["_src"] = sp.as_posix()
    parts = sch.load_catalog()
    fixed = boardlib.load_board(pathlib.Path(ns.fixed)) if ns.fixed else None
    rtos = ns.rtos or bool(fixed and (fixed.get("config_source") or {}).get("rtos") == "freertos")
    board, notes, extra = allocate(s, parts, fixed, ns.name or re.sub(r"[^a-z0-9-]", "-", f"{sp.parent.name}-draft".lower()))
    rep = boardlib.check_board(board)
    if ns.app and not rep.errors:
        boardlib.check_requires(board, yaml.safe_load(pathlib.Path(ns.app).read_text(encoding="utf-8")), rep)
    o = pathlib.Path(ns.o); o.mkdir(parents=True, exist_ok=True)
    (o / "board.yaml").write_text("# tools/alloc.py 生成的草稿：CubeMX 配完后用 tools/ioc_import.py 导出的 board.yaml 覆盖它\n"
                                  + yaml.safe_dump(board, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8", newline="\n")
    (o / "cubemx.md").write_text(cubemx_md(board, extra, rtos), encoding="utf-8", newline="\n")
    (o / "alloc.md").write_text(alloc_md(board, extra, rep), encoding="utf-8", newline="\n")
    for e in rep.errors:
        print("✗", e)
    for n in notes:
        print("!", n)
    ok = sum(1 for d in extra["ds"] if d.get("from") in ("分配", "沿用"))
    print(f"alloc: {ok}/{len(extra['ds'])} 项已定，校验错误 {len(rep.errors)}；写入 {o}/board.yaml、cubemx.md、alloc.md")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
