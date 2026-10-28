"""board.yaml 的加载、Schema 校验与语义检查（冲突检查）。

被 validate_board.py（命令行校验）和 gen_board.py（代码生成）共用，保证"能生成的一定校验过"。
"""
from __future__ import annotations

import json
import re
import pathlib
from dataclasses import dataclass, field

import yaml
import jsonschema

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "board.schema.json"
RES_TYPES = ["gpio", "pwm", "encoder", "uart", "timer", "adc"]


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# STM32 型号第 11 位（STM32F407V[E]T6）是 Flash 容量代码，各系列通用（ST 命名规则）
STM32_FLASH_CODE = {"4": 16, "6": 32, "8": 64, "B": 128, "Z": 192, "C": 256, "D": 384, "E": 512, "F": 768,
                    "G": 1024, "H": 1536, "I": 2048}


def stm32_flash_kb(part: str | None) -> int | None:
    """STM32F407VET6 / STM32F407VETx -> 512；STM32F103C8T6 -> 64；不是 STM32 或认不出 -> None。"""
    m = re.fullmatch(r"STM32[A-Z]\d{3}[A-Z]([0-9A-Z])[A-Z0-9]{0,2}x?", part or "")
    return STM32_FLASH_CODE.get(m[1]) if m else None


def load_board(path: pathlib.Path, variant: str | None = None) -> dict:
    """读 board.yaml；有 mcu.variants 时按 variant（缺省 mcu.default_variant）把型号/Flash/RAM 覆盖进 mcu。

    同一块 PCB 的不同芯片容量（天空星 VET6/VGT6、C8T6/CBT6）引脚完全相同，只有 Flash/RAM 和链接脚本不同，
    所以做成同一个板卡插件的变体，而不是复制一份 board.yaml。"""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: 顶层必须是映射（key: value）")
    mcu = data.get("mcu") or {}
    vs = mcu.get("variants")
    if vs:
        v = variant or mcu.get("default_variant")
        if v not in vs:
            raise ValueError(f"{path}: 变体 {v!r} 不存在，可选 {sorted(vs)}")
        mcu.update({k: x for k, x in vs[v].items() if k != "note"})
        mcu["selected_variant"] = v
    elif variant:
        raise ValueError(f"{path}: 该板卡没有 mcu.variants，不能指定 VARIANT={variant}")
    return data


def _is_todo(v) -> bool:
    return isinstance(v, str) and v.strip().upper() == "TODO"


def _walk_todos(obj, prefix, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _walk_todos(v, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            label = v.get("name", i) if isinstance(v, dict) else i
            _walk_todos(v, f"{prefix}[{label}]", out)
    elif _is_todo(obj):
        out.append(prefix)


def schema_check(board: dict, rep: Report) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    for e in sorted(v.iter_errors(board), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in e.absolute_path) or "<根>"
        rep.err(f"[schema] {where}: {e.message}")


def generic_check(board: dict, rep: Report) -> None:
    res = board.get("resources", {}) or {}
    # 1) 同类资源重名
    for t in RES_TYPES:
        names = [r.get("name") for r in res.get(t, []) or []]
        for n in set(names):
            if names.count(n) > 1:
                rep.err(f"[重名] {t} 中逻辑名 {n} 出现 {names.count(n)} 次")
    # 2) 同一物理引脚被多个资源占用
    used: dict[str, list[str]] = {}
    def use(pin, who):
        if pin is None or _is_todo(pin):
            return
        used.setdefault(pin, []).append(who)
    for r in res.get("gpio", []) or []:
        use(r.get("pin"), f"gpio.{r.get('name')}")
    for r in res.get("pwm", []) or []:
        use(r.get("pin"), f"pwm.{r.get('name')}")
    for r in res.get("encoder", []) or []:
        use(r.get("pin_a"), f"encoder.{r.get('name')}.A")
        use(r.get("pin_b"), f"encoder.{r.get('name')}.B")
    for r in res.get("uart", []) or []:
        use(r.get("tx"), f"uart.{r.get('name')}.TX")
        use(r.get("rx"), f"uart.{r.get('name')}.RX")
    for r in res.get("adc", []) or []:
        use(r.get("pin"), f"adc.{r.get('name')}")
    for pin, who in used.items():
        if len(who) > 1:
            rep.err(f"[引脚冲突] {pin} 同时被 {', '.join(who)} 使用")
    # 3) 定时器用途冲突：编码器独占整个定时器；周期定时器独占；PWM 同一定时器频率必须一致
    owners: dict[str, list[str]] = {}
    pwm_freq: dict[str, set] = {}
    for r in res.get("pwm", []) or []:
        tim = r.get("timer")
        owners.setdefault(tim, []).append(f"pwm.{r.get('name')}")
        pwm_freq.setdefault(tim, set()).add(r.get("freq_hz"))
        chans = [x.get("channel") for x in res.get("pwm", []) if x.get("timer") == tim]
        if chans.count(r.get("channel")) > 1 and not _is_todo(r.get("channel")):
            rep.err(f"[通道冲突] {tim} 通道 {r.get('channel')} 被多个 PWM 使用")
    for t in ("encoder", "timer"):
        for r in res.get(t, []) or []:
            tim = r.get("timer") if t == "encoder" else r.get("instance")
            owners.setdefault(tim, []).append(f"{t}.{r.get('name')}")
    for tim, who in owners.items():
        exclusive = [w for w in who if not w.startswith("pwm.")]
        if exclusive and len(who) > 1:
            rep.err(f"[定时器冲突] {tim} 被 {', '.join(who)} 共用；编码器和周期定时器需要独占定时器")
    for tim, fs in pwm_freq.items():
        if len(fs) > 1:
            rep.err(f"[频率冲突] {tim} 上的 PWM 通道频率不一致 {sorted(fs)}；同一定时器所有通道共享频率")
    # 4) 串口实例重复
    insts = [r.get("instance") for r in res.get("uart", []) or []]
    for i in set(insts):
        if insts.count(i) > 1:
            rep.err(f"[串口冲突] {i} 被定义了 {insts.count(i)} 次")


def stm32f4_check(board: dict, rep: Report) -> None:
    from families import stm32f4 as F
    res = board.get("resources", {}) or {}

    def pin_ok(pin, where):
        if _is_todo(pin):
            return False
        if not F.PIN_RE.match(pin):
            rep.err(f"[引脚格式] {where}: {pin} 不是 STM32 引脚名（应形如 PA8）")
            return False
        if pin in F.RESERVED_PINS:
            rep.warn(f"[保留引脚] {where}: {pin} 是 {F.RESERVED_PINS[pin]}")
        return True

    clk = board.get("clock", {}) or {}
    cube = board.get("port") == "stm32-cubemx"   # CubeMX 管时钟与 DMA：这里只核对引脚复用，时钟/DMA 由 ioc_import 检查
    hse = 0 if cube else clk.get("hse_hz", 0)
    if hse == "TODO":
        hse = 0   # 已作为 TODO 记录；gen_board.py 生成固件时会拒绝
    if hse and (hse % 1_000_000 or not 2 <= hse // 1_000_000 <= 26):
        rep.err(f"[时钟] hse_hz={hse}：移植层要求 HSE 为 2~26 MHz 的整 MHz")
    if not cube and clk.get("sysclk_hz", 168_000_000) != 168_000_000:
        rep.err("[时钟] stm32f4-hal 移植层目前只实现 168 MHz（PLL N=336, P=2, Q=7）")

    for r in res.get("gpio", []) or []:
        pin_ok(r["pin"], f"gpio.{r['name']}")
    for r in res.get("pwm", []) or []:
        where = f"pwm.{r['name']}"
        tim, ch = r["timer"], r["channel"]
        if tim not in F.TIMERS:
            rep.err(f"[定时器] {where}: 未知定时器 {tim}")
            continue
        if not F.TIMERS[tim][3]:
            rep.err(f"[定时器] {where}: {tim} 没有 PWM 输出通道（基本定时器）")
            continue
        if pin_ok(r["pin"], where) and not _is_todo(ch):
            pins = F.TIMER_CH_PINS.get((tim, ch))
            if pins is None:
                rep.warn(f"[未核实] {where}: {tim}_CH{ch} 不在知识表中，请对照数据手册")
            elif r["pin"] not in pins:
                rep.err(f"[复用错误] {where}: {r['pin']} 不能作为 {tim}_CH{ch}，可选 {pins}")
    for r in res.get("encoder", []) or []:
        where = f"encoder.{r['name']}"
        tim = r["timer"]
        if tim not in F.TIMERS or not F.TIMERS[tim][2]:
            rep.err(f"[定时器] {where}: {tim} 不支持正交编码器模式（可用 TIM1/2/3/4/5/8）")
            continue
        for ch, key in ((1, "pin_a"), (2, "pin_b")):
            if pin_ok(r[key], f"{where}.{key}"):
                pins = F.TIMER_CH_PINS.get((tim, ch), [])
                if r[key] not in pins:
                    rep.err(f"[复用错误] {where}.{key}: {r[key]} 不能作为 {tim}_CH{ch}，可选 {pins}")
    dma_used: dict[tuple, str] = {}
    for r in res.get("uart", []) or []:
        where = f"uart.{r['name']}"
        inst = r["instance"]
        if inst not in F.UARTS:
            rep.err(f"[串口] {where}: 未知串口 {inst}")
            continue
        _, _, txs, rxs, _ = F.UARTS[inst]
        if pin_ok(r["tx"], where + ".tx") and r["tx"] not in txs:
            rep.err(f"[复用错误] {where}.tx: {r['tx']} 不能作为 {inst}_TX，可选 {txs}")
        if pin_ok(r["rx"], where + ".rx") and r["rx"] not in rxs:
            rep.err(f"[复用错误] {where}.rx: {r['rx']} 不能作为 {inst}_RX，可选 {rxs}")
        if cube:
            continue
        if not r.get("dma", True):
            rep.err(f"[移植层能力] {where}: stm32f4-hal 端口目前只实现 DMA 模式串口")
        for kind, table in (("RX", F.UART_DMA_RX), ("TX", F.UART_DMA_TX)):
            ok = False
            for cand in table[inst]:
                key = cand[:2]
                if key not in dma_used:
                    dma_used[key] = f"{inst}_{kind}"
                    ok = True
                    break
            if not ok:
                rep.err(f"[DMA 冲突] {inst}_{kind} 的所有可选数据流都已被占用：{table[inst]}")
    for r in res.get("timer", []) or []:
        if r["instance"] not in F.TIMERS:
            rep.err(f"[定时器] timer.{r['name']}: 未知定时器 {r['instance']}")
    for r in res.get("adc", []) or []:
        where = f"adc.{r['name']}"
        if r["instance"] not in F.ADCS:
            rep.err(f"[ADC] {where}: 只支持 {F.ADCS}")
        ch = r["channel"]
        if pin_ok(r["pin"], where) and not _is_todo(ch):
            exp = F.ADC_CH_PINS.get(ch)
            if exp != r["pin"]:
                rep.err(f"[复用错误] {where}: {r['instance']}_IN{ch} 对应 {exp}，不是 {r['pin']}")


FAMILY_CHECKS = {"stm32f4": stm32f4_check}


def cubemx_check(board: dict, rep: Report) -> None:
    """port: stm32-cubemx —— CubeMX 是唯一配置源：必须指明 .ioc；串口必须 DMA 接收（循环模式由 ioc_import 核对）。"""
    cs = board.get("config_source") or {}
    if cs.get("tool") != "cubemx" or not cs.get("file"):
        rep.err("[CubeMX] port: stm32-cubemx 必须写 config_source: {tool: cubemx, file: <相对本文件的 .ioc 路径>}")
    for r in (board.get("resources") or {}).get("uart") or []:
        if r.get("dma") is False:
            rep.err(f"[CubeMX] uart.{r['name']}: 本移植层要求 RX 为循环 DMA（在 CubeMX 里给该串口加 RX DMA，Mode=Circular）")


PORT_CHECKS = {"stm32-cubemx": cubemx_check}

TYPE_SIZE = {"u8": 1, "i8": 1, "u16": 2, "i16": 2, "u32": 4, "i32": 4, "f32": 4}
DZFRAME_MAX_PAYLOAD = 64   # 与 firmware/proto/dzframe/dzframe.h 的 DZFRAME_MAX_PAYLOAD 一致


def coprocessor_check(board: dict, rep: Report) -> None:
    """协处理板（kind: coprocessor）：通道/参数编号唯一、负载不超过 dzframe 上限、参数范围自洽。"""
    cp = board["coprocessor"]
    for key in ("channels", "params"):
        items = cp.get(key) or []
        for attr in ("id", "name"):
            vals = [x[attr] for x in items]
            for v in set(vals):
                if vals.count(v) > 1:
                    rep.err(f"[协处理板] {key} 的 {attr}={v} 重复")
    for ch in cp["channels"]:
        names = [f["name"] for f in ch["fields"]]
        if len(set(names)) != len(names):
            rep.err(f"[协处理板] 通道 {ch['name']} 字段名重复")
        size = sum(TYPE_SIZE[f["type"]] for f in ch["fields"])
        if size > DZFRAME_MAX_PAYLOAD:
            rep.err(f"[协处理板] 通道 {ch['name']} 负载 {size} 字节，超过 dzframe 上限 {DZFRAME_MAX_PAYLOAD}")
    for p in cp.get("params") or []:
        lo, hi, d = p.get("min"), p.get("max"), p.get("default")
        if lo is not None and hi is not None and lo > hi:
            rep.err(f"[协处理板] 参数 {p['name']} min>max")
        if d is not None and ((lo is not None and d < lo) or (hi is not None and d > hi)):
            rep.err(f"[协处理板] 参数 {p['name']} 默认值不在范围内")
    if cp["link"]["transport"] == "uart" and "baud" not in cp["link"]:
        rep.err("[协处理板] uart 链路必须写 baud（不知道就写 TODO）")


def check_board(board: dict) -> Report:
    rep = Report()
    schema_check(board, rep)
    if rep.errors:
        return rep  # 结构都不对，语义检查没有意义
    _walk_todos(board, "", rep.todos)
    if board.get("kind") == "coprocessor":
        coprocessor_check(board, rep)
        return rep
    generic_check(board, rep)
    mcu = board["mcu"]
    fk = stm32_flash_kb(mcu.get("part"))
    if fk and isinstance(mcu.get("flash_kb"), int) and mcu["flash_kb"] > fk:
        rep.err(f"[mcu] flash_kb={mcu['flash_kb']} 大于型号 {mcu['part']} 的实际 Flash {fk}KB：链接脚本会越界")
    fam = board["mcu"]["family"]
    if fam in FAMILY_CHECKS:
        FAMILY_CHECKS[fam](board, rep)
    elif fam != "host":
        rep.warn(f"[知识库] 没有 {fam} 系列的复用/DMA 知识表，只做了通用检查")
    if board.get("port") in PORT_CHECKS:
        PORT_CHECKS[board["port"]](board, rep)
    return rep


def check_requires(board: dict, app: dict, rep: Report) -> None:
    """检查板卡是否提供应用 app.yaml 里 requires 声明的全部逻辑资源，且这些资源没有 TODO。"""
    res = board.get("resources", {}) or {}
    for t, names in (app.get("requires") or {}).items():
        have = {r["name"]: r for r in res.get(t, []) or []}
        for n in names:
            if n not in have:
                rep.err(f"[缺资源] 应用需要 {t}.{n}，板卡 {board['name']} 未定义")
            else:
                todos: list[str] = []
                _walk_todos(have[n], f"{t}.{n}", todos)
                for td in todos:
                    rep.err(f"[未确认] 应用用到的 {td} 仍是 TODO，编译前必须确认")
