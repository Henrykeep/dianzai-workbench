#!/usr/bin/env python3
"""由 board.yaml 生成板级代码。生成物放在构建目录，不提交到 Git（board.yaml 才是唯一真相）。

生成：
  board_gen.h   逻辑 ID（RES_GPIO_LED 等）与资源数量 —— 所有板卡格式相同，应用只包含它
  board_gen.c   移植层需要的资源表 + 时钟使能 + 中断入口（按 mcu.family 生成）
  board_gen.mk  给 Makefile 用的变量（端口名、宏定义、链接脚本等）

用法：
  python3 tools/gen_board.py boards/stm32f407-skystar/board.yaml -o build/stm32f407-skystar/gen \
          [--app apps/motor_speed_demo/app.yaml]

生成前先跑与 validate_board.py 完全相同的检查，有错误就不生成。
"""
import argparse
import re
import hashlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import boardlib  # noqa: E402
import yaml  # noqa: E402

HEADER = "/* 自动生成，请勿手改。来源：{src}（sha256 {sha}）。改引脚请改 board.yaml 后重新生成。 */\n"


def _is_todo(r: dict) -> bool:
    return any(isinstance(v, str) and v.strip().upper().startswith("TODO") for v in r.values())


def usable(board: dict) -> dict:
    """去掉仍含 TODO 字段的资源。它们不进入资源表，ID 宏定义为 PAL_ID_NONE（调用返回 DZ_ENODEV）。"""
    res = board.get("resources", {}) or {}
    return {t: [r for r in (res.get(t) or []) if not _is_todo(r)] for t in boardlib.RES_TYPES}


def gen_header(board: dict, src: str, sha: str) -> str:
    res = usable(board)
    todo = {t: [r for r in (board.get("resources", {}) or {}).get(t) or [] if _is_todo(r)] for t in boardlib.RES_TYPES}
    out = [HEADER.format(src=src, sha=sha[:12]), "#ifndef BOARD_GEN_H", "#define BOARD_GEN_H", "",
           '#include "pal.h"', "",
           f'#define BOARD_NAME "{board["name"]}"',
           f'#define BOARD_FAMILY_{board["mcu"]["family"].upper()} 1',
           f'#define BOARD_HAS_FPU {1 if board["mcu"].get("fpu") else 0}', ""]
    for t in boardlib.RES_TYPES:
        items = res.get(t, []) or []
        out.append(f"/* {t} */")
        for i, r in enumerate(items):
            out.append(f"#define RES_{t.upper()}_{r['name']} ((pal_id_t){i})")
        for r in todo[t]:
            out.append(f"#define RES_{t.upper()}_{r['name']} PAL_ID_NONE  /* board.yaml 中仍为 TODO，未生成 */")
        out.append(f"#define BOARD_{t.upper()}_COUNT {len(items)}u")
        out.append("")
    out += ["#endif /* BOARD_GEN_H */", ""]
    return "\n".join(out)


def _pin(p: str):
    return f"GPIO{p[1]}", f"GPIO_PIN_{int(p[2:])}"


def gen_stm32f4(board: dict, src: str, sha: str) -> tuple[str, dict]:
    from families import stm32f4 as F
    res = usable(board)
    c = [HEADER.format(src=src, sha=sha[:12]), '#include "board_gen.h"', '#include "port_stm32f4.h"', ""]
    ports, rcc, irqs = set(), [], {}

    def need_port(p):
        ports.add(p[1])

    def add_irq(vector, body):
        if vector in irqs:
            raise SystemExit(f"中断向量 {vector} 被两个资源共用，生成器不支持，请换外设实例")
        irqs[vector] = body

    # GPIO
    rows = []
    for r in res.get("gpio", []) or []:
        need_port(r["pin"])
        port, pin = _pin(r["pin"])
        pull = {"none": "GPIO_NOPULL", "up": "GPIO_PULLUP", "down": "GPIO_PULLDOWN"}[r.get("pull", "none")]
        rows.append(f"    {{ {port}, {pin}, {1 if r['dir'] == 'out' else 0}, {pull}, "
                    f"{int(r.get('active_low', False))}, {int(r.get('init', False))}, {int(r.get('open_drain', False))} }}, /* {r['name']} {r['pin']} */")
    c += _table("p4_gpio_t", "g_p4_gpio", rows)

    # PWM
    rows, tims = [], set()
    for r in res.get("pwm", []) or []:
        need_port(r["pin"]); tims.add(r["timer"])
        port, pin = _pin(r["pin"])
        apb = 2 if F.TIMERS[r["timer"]][0] == "APB2" else 1
        rows.append(f"    {{ {r['timer']}, TIM_CHANNEL_{r['channel']}, {port}, {pin}, GPIO_AF{F.TIMER_AF[r['timer']]}_{r['timer']}, "
                    f"{apb}, {r['freq_hz']}u }}, /* {r['name']} */")
    c += _table("p4_pwm_t", "g_p4_pwm", rows)

    # 编码器
    rows = []
    for r in res.get("encoder", []) or []:
        need_port(r["pin_a"]); need_port(r["pin_b"]); tims.add(r["timer"])
        pa, na = _pin(r["pin_a"]); pb, nb = _pin(r["pin_b"])
        bits = F.TIMERS[r["timer"]][1]
        rows.append(f"    {{ {r['timer']}, {pa}, {na}, {pb}, {nb}, GPIO_AF{F.TIMER_AF[r['timer']]}_{r['timer']}, "
                    f"{bits}, {int(r.get('invert', False))}, {r.get('filter', 6)} }}, /* {r['name']} */")
    c += _table("p4_enc_t", "g_p4_enc", rows)

    # 串口
    rows, bufs, dmas, dma_taken, uarts = [], [], set(), set(), []
    for i, r in enumerate(res.get("uart", []) or []):
        inst = r["instance"]
        need_port(r["tx"]); need_port(r["rx"])
        af, bus, _, _, irqname = F.UARTS[inst]
        pick = {}
        for kind, table in (("rx", F.UART_DMA_RX), ("tx", F.UART_DMA_TX)):
            for cand in table[inst]:
                if cand[:2] not in dma_taken:
                    dma_taken.add(cand[:2]); pick[kind] = cand; break
        (rd, rs, rch), (td, ts, tch) = pick["rx"], pick["tx"]
        dmas.update({rd, td})
        tp, tn = _pin(r["tx"]); rp, rn = _pin(r["rx"])
        rx_n, tx_n = r.get("rx_buf", 512), r.get("tx_buf", 256)
        bufs.append(f"static uint8_t s_uart{i}_rx[{rx_n}];\nstatic uint8_t s_uart{i}_tx[{tx_n}];")
        rows.append(f"    {{ {inst}, {tp}, {tn}, {rp}, {rn}, GPIO_AF{af}_{inst}, {r['baud']}u,\n"
                    f"      DMA{rd}_Stream{rs}, DMA_CHANNEL_{rch}, DMA{rd}_Stream{rs}_IRQn,\n"
                    f"      DMA{td}_Stream{ts}, DMA_CHANNEL_{tch}, DMA{td}_Stream{ts}_IRQn, {irqname}n,\n"
                    f"      s_uart{i}_rx, {rx_n}u, s_uart{i}_tx, {tx_n}u }}, /* {r['name']} */")
        add_irq(f"DMA{rd}_Stream{rs}_IRQHandler", f"p4_uart_rx_dma_irq({i});")
        add_irq(f"DMA{td}_Stream{ts}_IRQHandler", f"p4_uart_tx_dma_irq({i});")
        add_irq(f"{irqname}Handler", f"p4_uart_irq({i});")
        uarts.append(inst)
    c += bufs
    c += _table("p4_uart_t", "g_p4_uart", rows)

    # 周期定时器
    rows = []
    for i, r in enumerate(res.get("timer", []) or []):
        t = r["instance"]; tims.add(t)
        apb = 2 if F.TIMERS[t][0] == "APB2" else 1
        irq = F.TIMERS[t][4]
        rows.append(f"    {{ {t}, {apb}, {irq}n, {r.get('irq_priority', 1)}u }}, /* {r['name']} */")
        add_irq(f"{irq}Handler", f"p4_timer_irq({i});")
    c += _table("p4_timer_t", "g_p4_timer", rows)

    # ADC
    rows, adcs = [], set()
    for r in res.get("adc", []) or []:
        need_port(r["pin"]); adcs.add(r["instance"])
        p, n = _pin(r["pin"])
        rows.append(f"    {{ {r['instance']}, ADC_CHANNEL_{r['channel']}, {p}, {n}, "
                    f"{{ {r.get('bits', 12)}u, {r.get('vref_mv', 3300)}u, {r.get('scale_num', 1)}u, {r.get('scale_den', 1)}u }} }}, /* {r['name']} */")
    c += _table("p4_adc_t", "g_p4_adc", rows)

    # 时钟使能
    for p in sorted(ports):
        rcc.append(f"__HAL_RCC_GPIO{p}_CLK_ENABLE();")
    for t in sorted(tims):
        rcc.append(f"__HAL_RCC_{t}_CLK_ENABLE();")
    for u in uarts:
        rcc.append(f"__HAL_RCC_{u}_CLK_ENABLE();")
    for d in sorted(dmas):
        rcc.append(f"__HAL_RCC_DMA{d}_CLK_ENABLE();")
    for a in sorted(adcs):
        rcc.append(f"__HAL_RCC_{a}_CLK_ENABLE();")
    c.append("void board_gen_clock_enable(void)\n{")
    c += [f"    {x}" for x in rcc] or ["    /* 无外设 */"]
    c.append("}\n")
    c.append(f'const char *const g_board_name = BOARD_NAME;\n')
    c.append("/* 中断入口：由生成器按资源分配，转发给移植层 */")
    for vec, body in irqs.items():
        c.append(f"void {vec}(void) {{ {body} }}")
    c.append("")

    clk = board.get("clock", {}) or {}
    if clk.get("hse_hz") == "TODO":
        raise SystemExit("✗ clock.hse_hz 为 TODO：晶振频率未核实，拒绝生成时钟配置（错的 HSE 会让所有波特率/PWM 频率都错）")
    part = board["mcu"]["part"]
    mk = {
        "BOARD_PORT": board["port"],
        "BOARD_FAMILY": "stm32f4",
        "BOARD_DEFS": f"-DSTM32F407xx -DUSE_HAL_DRIVER -DHSE_VALUE={clk.get('hse_hz', 8000000)}u",
        "BOARD_FLASH_KB": str(board["mcu"].get("flash_kb", 512)),
        "BOARD_PART": part,
    }
    return "\n".join(c), mk


def gen_host(board: dict, src: str, sha: str) -> tuple[str, dict]:
    res = usable(board)
    freqs = ", ".join(f"{r['freq_hz']}u" for r in res["pwm"]) or "0u"
    c = (HEADER.format(src=src, sha=sha[:12]) + '#include "board_gen.h"\nconst char *const g_board_name = BOARD_NAME;\n'
         f"const uint32_t g_host_pwm_freq[] = {{ {freqs} }};\n")
    return c, {"BOARD_PORT": board["port"], "BOARD_FAMILY": "host", "BOARD_DEFS": ""}


CPU_FLAGS = {
    "cortex-m0":   "-mcpu=cortex-m0 -mthumb -mfloat-abi=soft",
    "cortex-m0plus": "-mcpu=cortex-m0plus -mthumb -mfloat-abi=soft",
    "cortex-m3":   "-mcpu=cortex-m3 -mthumb -mfloat-abi=soft",
    "cortex-m4":   "-mcpu=cortex-m4 -mthumb -mfloat-abi=soft",
    "cortex-m4f":  "-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard",
    "cortex-m7f":  "-mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard",
    "cortex-m33f": "-mcpu=cortex-m33 -mthumb -mfpu=fpv5-sp-d16 -mfloat-abi=hard",
}


def _cube_handle(inst: str) -> str:
    """CubeMX 句柄命名：TIM3 -> htim3，USART1/UART4/LPUART1 -> huart1/huart4/hlpuart1，ADC1 -> hadc1。"""
    m = re.fullmatch(r"(TIM|USART|UART|LPUART|ADC)(\d+)", inst)
    if not m:
        raise SystemExit(f"✗ 无法推出 CubeMX 句柄名：{inst}")
    pre = {"TIM": "htim", "USART": "huart", "UART": "huart", "LPUART": "hlpuart", "ADC": "hadc"}[m[1]]
    return f"{pre}{m[2]}"


# STM32F1 的 HAL 器件宏按 Flash 容量分档（stm32f1xx.h）：x6=16/32K，xB=64/128K，xE=256~512K，xG=768K/1M
F1_DENSITY = {"4": "6", "6": "6", "8": "B", "B": "B", "C": "E", "D": "E", "E": "E", "F": "G", "G": "G"}


def cube_define(part: str) -> str:
    """STM32F407VETx -> STM32F407xx；STM32F103C8T6 -> STM32F103xB；STM32G431CBU6 -> STM32G431xx（CubeMX/HAL 的器件宏）。"""
    m = re.fullmatch(r"(STM32[A-Z]\d{3})[A-Z]([0-9A-Z])[A-Z0-9]{0,2}x?", part)
    if not m:
        raise SystemExit(f"✗ mcu.part={part!r} 无法推出 HAL 器件宏；请先填写真实型号（看芯片丝印）")
    if m[1] in ("STM32F105", "STM32F107"):
        return m[1] + "xC"
    if m[1].startswith("STM32F10"):
        if m[2] not in F1_DENSITY:
            raise SystemExit(f"✗ {part}: 认不出 F1 的 Flash 容量代码 {m[2]}")
        return m[1] + "x" + F1_DENSITY[m[2]]
    return m[1] + "xx"


def gen_cubemx(board: dict, src: str, sha: str) -> tuple[str, dict]:
    """port: stm32-cubemx —— 只生成“逻辑 ID -> CubeMX 句柄”表；外设配置全在 .ioc / CubeMX 生成代码里。"""
    res = usable(board)
    c = [HEADER.format(src=src, sha=sha[:12]), '#include "port_cubemx.h"', '#include "board_gen.h"', ""]
    handles = []
    def need(inst, typ):
        h = _cube_handle(inst)
        if h not in [x for x, _ in handles]:
            handles.append((h, typ))
        return h
    rows = {k: [] for k in ("gpio", "pwm", "encoder", "uart", "timer", "adc")}
    for r in res["gpio"]:
        port, pin = _pin(r["pin"])
        rows["gpio"].append(f"    {{ {port}, {pin}, {int(bool(r.get('active_low')))}u }}, /* {r['name']} {r['pin']} */")
    for r in res["pwm"]:
        rows["pwm"].append(f"    {{ &{need(r['timer'], 'TIM')}, TIM_CHANNEL_{r['channel']} }}, /* {r['name']} */")
    for r in res["encoder"]:
        rows["encoder"].append(f"    {{ &{need(r['timer'], 'TIM')}, {int(bool(r.get('invert')))}u }}, /* {r['name']} */")
    bufs = []
    for i, r in enumerate(res["uart"]):
        rx_n, tx_n = r.get("rx_buf", 512), r.get("tx_buf", 256)
        bufs.append(f"static uint8_t s_uart{i}_rx[{rx_n}];\nstatic uint8_t s_uart{i}_tx[{tx_n}];")
        rows["uart"].append(f"    {{ &{need(r['instance'], 'UART')}, s_uart{i}_rx, {rx_n}u, s_uart{i}_tx, {tx_n}u }}, /* {r['name']} */")
    for r in res["timer"]:
        rows["timer"].append(f"    {{ &{need(r['instance'], 'TIM')} }}, /* {r['name']} */")
    for r in res["adc"]:
        rows["adc"].append(f"    {{ &{need(r['instance'], 'ADC')}, ADC_CHANNEL_{r['channel']},\n"
                           f"      {{ {r.get('bits', 12)}u, {r.get('vref_mv', 3300)}u, {r.get('scale_num', 1)}u, {r.get('scale_den', 1)}u }} }}, /* {r['name']} */")
    c.append("/* CubeMX 在 main.c / tim.c / usart.c / adc.c 中定义的句柄 */")
    c += [f"extern {t}_HandleTypeDef {h};" for h, t in handles] + [""]
    c += bufs + [""]
    for key, typ, name in (("gpio", "cm_gpio_t", "g_cm_gpio"), ("pwm", "cm_pwm_t", "g_cm_pwm"),
                           ("encoder", "cm_enc_t", "g_cm_enc"), ("uart", "cm_uart_t", "g_cm_uart"),
                           ("timer", "cm_timer_t", "g_cm_timer"), ("adc", "cm_adc_t", "g_cm_adc")):
        c += _table(typ, name, rows[key])
    c.append("const char *const g_board_name = BOARD_NAME;\n")
    cs = board["config_source"]
    tb = cs.get("hal_timebase", "SysTick")
    defs = ""
    if tb != "SysTick":
        # HAL 时基 = TIMx（CubeMX 在 stm32xxxx_hal_timebase_tim.c 里定义该句柄）：pal_micros 改读它的计数
        h = _cube_handle(tb)
        c += ["/* HAL 时基定时器（config_source.hal_timebase） */", f"extern TIM_HandleTypeDef {h};",
              f"TIM_HandleTypeDef *const g_cm_timebase = &{h};", ""]
        defs += " -DDZ_CM_TIM_TIMEBASE"
    if cs.get("rtos"):
        defs += f" -DDZ_CM_RTOS_{cs['rtos'].upper()}"

    mcu = board["mcu"]
    core = mcu.get("core", "")
    if core not in CPU_FLAGS:
        raise SystemExit(f"✗ mcu.core={core!r} 未知，可选 {sorted(CPU_FLAGS)}")
    cube_dir = (pathlib.Path(src).parent / cs["file"]).parent.as_posix()
    family = mcu["family"]                        # stm32f4 -> 用 STM32Cube<F4> 的 HAL 源码
    mk = {
        "BOARD_PORT": board["port"],
        "BOARD_FAMILY": "stm32-cubemx",
        "BOARD_SERIES": family,
        "BOARD_CPU": CPU_FLAGS[core],
        "BOARD_DEFS": f"-D{cube_define(mcu['part'])} -DUSE_HAL_DRIVER{defs}",
        "BOARD_RTOS": cs.get("rtos", ""),
        "BOARD_FLASH_KB": str(mcu.get("flash_kb", 0)),
        "BOARD_PART": mcu["part"],
        "CUBE_DIR": cube_dir,
    }
    return "\n".join(c), mk


def gen_mspm0(board: dict, src: str, sha: str) -> tuple[str, dict]:
    """port: mspm0-driverlib —— 生成“逻辑 ID -> SysConfig 实例宏”表与中断入口；外设配置全在 ti_msp_dl_config.c。

    实例名约定（SysConfig 每个实例的 Name）：GPIO_<名>（组内引脚 PIN）、PWM_<定时器>、ENC_<名>（QEI，或 GPIO 组的 A/B 脚）、
    UART_<名>、TIMER_<名>。宏名按 SysConfig 的派生规则（<Name>_INST、<Name>_INST_IRQHandler…）。"""
    res = usable(board)
    c = [HEADER.format(src=src, sha=sha[:12]), '#include "port_mspm0.h"', '#include "board_gen.h"', ""]
    rows = {k: [] for k in ("gpio", "pwm", "encoder", "uart", "timer")}
    isr = []
    for r in res["gpio"]:
        n = f"GPIO_{r['name']}"
        rows["gpio"].append(f"    {{ {n}_PORT, {n}_PIN_PIN, {int(bool(r.get('active_low')))}u }}, /* {r['name']} {r['pin']} */")
    for r in res["pwm"]:
        n = f"PWM_{r['timer']}"
        rows["pwm"].append(f"    {{ {n}_INST, DL_TIMER_CC_{r['channel']}_INDEX, {n}_INST_CLK_FREQ }}, /* {r['name']} {r['pin']} */")
    gpio_enc = False
    for r in res["encoder"]:
        n = f"ENC_{r['name']}"
        inv = int(bool(r.get("invert")))
        if r.get("mode") == "gpio_isr":
            gpio_enc = True
            rows["encoder"].append(f"    {{ 0, {n}_PORT, {n}_A_PIN, {n}_B_PIN, {inv}u }}, /* {r['name']} GPIO 软件解码 */")
        else:
            rows["encoder"].append(f"    {{ {n}_INST, 0, 0u, 0u, {inv}u }}, /* {r['name']} QEI */")
    bufs = []
    for i, r in enumerate(res["uart"]):
        n = f"UART_{r['name']}"
        rx_n, tx_n = r.get("rx_buf", 512), r.get("tx_buf", 256)
        bufs.append(f"static uint8_t s_uart{i}_rx[{rx_n}];\nstatic uint8_t s_uart{i}_tx[{tx_n}];")
        rows["uart"].append(f"    {{ {n}_INST, {n}_INST_INT_IRQN, s_uart{i}_rx, {rx_n}u, s_uart{i}_tx, {tx_n}u }}, /* {r['name']} */")
        isr.append(f"void {n}_INST_IRQHandler(void) {{ dz_m0_uart_isr({i}u); }}")
    for i, r in enumerate(res["timer"]):
        n = f"TIMER_{r['name']}"
        wide = r["instance"] in ("TIMG12", "TIMG13")      # 32 位 TIMG；其余 16 位
        rows["timer"].append(f"    {{ {n}_INST, {n}_INST_INT_IRQN, {n}_INST_CLK_FREQ, {'0xFFFFFFFFu' if wide else '0xFFFFu'} }}, /* {r['name']} {r['instance']} */")
        isr.append(f"void {n}_INST_IRQHandler(void) {{ dz_m0_timer_isr({i}u); }}")
    if gpio_enc:
        isr.append("void GROUP1_IRQHandler(void) { dz_m0_gpio_enc_isr(); }   /* GPIOA/GPIOB 中断组 */")
    c += bufs + [""]
    for key, typ, name in (("gpio", "m0_gpio_t", "g_m0_gpio"), ("pwm", "m0_pwm_t", "g_m0_pwm"),
                           ("encoder", "m0_enc_t", "g_m0_enc"), ("uart", "m0_uart_t", "g_m0_uart"),
                           ("timer", "m0_timer_t", "g_m0_timer")):
        c += _table(typ, name, rows[key])
    c += ["/* 中断入口：向量名来自 SysConfig 的 <实例>_INST_IRQHandler 宏 */"] + isr + [""]
    c.append("const char *const g_board_name = BOARD_NAME;\n")
    mcu = board["mcu"]
    core = mcu.get("core", "")
    if core not in CPU_FLAGS:
        raise SystemExit(f"✗ mcu.core={core!r} 未知，可选 {sorted(CPU_FLAGS)}")
    part = mcu["part"].upper()
    mk = {
        "BOARD_PORT": board["port"],
        "BOARD_FAMILY": "mspm0-driverlib",
        "BOARD_CPU": CPU_FLAGS[core],
        "BOARD_DEFS": f"-D__{part}__",
        "BOARD_PART": part,
        "BOARD_PART_LC": part.lower(),
        "SYSCFG_DIR": (pathlib.Path(src).parent / "syscfg").as_posix(),
    }
    return "\n".join(c), mk


def _table(typ, name, rows):
    if not rows:
        return [f"const {typ} {name}[1];  /* 本板没有此类资源，占位避免零长度数组 */", ""]
    return [f"const {typ} {name}[] = {{"] + rows + ["};", ""]


PORT_GENERATORS = {"stm32-cubemx": gen_cubemx, "mspm0-driverlib": gen_mspm0}   # 按移植层生成（与芯片系列无关）
GENERATORS = {"stm32f4": gen_stm32f4, "host": gen_host, **PORT_GENERATORS}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board", type=pathlib.Path)
    ap.add_argument("-o", "--out", type=pathlib.Path, required=True)
    ap.add_argument("--app", type=pathlib.Path)
    ap.add_argument("--variant", help="选择 mcu.variants 里的芯片变体（如 VGT6），缺省用 default_variant")
    a = ap.parse_args()

    raw = a.board.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    board = boardlib.load_board(a.board, a.variant)
    rep = boardlib.check_board(board)
    if a.app and not rep.errors:
        boardlib.check_requires(board, yaml.safe_load(a.app.read_text(encoding="utf-8")), rep)
    if rep.errors:
        for e in rep.errors:
            print(f"错误  {e}", file=sys.stderr)
        print(f"✗ {a.board} 校验未通过，未生成任何文件", file=sys.stderr)
        return 1
    if board.get("kind") == "coprocessor":
        print(f"✗ {a.board}: 协处理板（kind: coprocessor）不运行本框架代码，不生成固件；它的通道描述供 gen_coproc.py 使用")
        return 1
    fam = board["mcu"]["family"]
    if board.get("port") in PORT_GENERATORS:
        fam = board["port"]
    if fam not in GENERATORS:
        print(f"✗ 还没有 {fam} 系列的代码生成器（见 docs/06-新增板卡.md）", file=sys.stderr)
        return 1
    src = a.board.as_posix()
    a.out.mkdir(parents=True, exist_ok=True)
    c_src, mk = GENERATORS[fam](board, src, sha)
    (a.out / "board_gen.h").write_text(gen_header(board, src, sha), encoding="utf-8")
    (a.out / "board_gen.c").write_text(c_src, encoding="utf-8")
    (a.out / "board_gen.mk").write_text("".join(f"{k} := {v}\n" for k, v in mk.items()), encoding="utf-8")
    for w in rep.warnings:
        print(f"警告  {w}")
    for t in rep.todos:
        print(f"TODO  {t}（应用未使用，不阻止生成）")
    print(f"✓ 已生成 {a.out}/board_gen.{{h,c,mk}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
