#!/usr/bin/env python3
"""gen_ioc.py —— 从零新建：把 tools/alloc.py 的 board.yaml 草稿写成 CubeMX 能打开的 .ioc（STM32F1 / F4）。

  python3 tools/gen_ioc.py alloc/board.yaml -o boards/<板>/cubemx/<板>.ioc [--name <工程名>]

用户习惯是“先 CubeMX”：这里只写 .ioc（引脚 + User Label 按 docs/05 标签约定、定时器 PSC/ARR、编码器模式、
串口 + RX Circular DMA / TX Normal DMA、NVIC 分组 4、SysTick 时基、节拍定时器 CTRL、SWD、时钟树），
工程目标 MDK-ARM（Keil）。CubeMX 的代码生成在本机跑不了：人用 CubeMX 打开它点一次 GENERATE CODE，
然后项目页第 ③ 步“导入已有工程”指向生成出来的目录（ioc_import / import_project 接手）。

格式依据：用户两份真实 .ioc（F407 Bldc、F103 USART）和 boards/stm32f407-skystar-cubemx 的合成样例；
F1 的 RCC / DMA / NVIC 键另外对照了参考仓库 refs/ext/nuedc2026-ball-balance/firmware/stm32_hal/stm32f103c8t6_uart.ioc
和 refs/ext/ti-contest/2023-E/2023-e-Code/stm32f1hal/stm32f1hal.ioc（逐键一致）；时钟树照抄那两份真实工程（F4 HSE 8 MHz→168 MHz，F1 HSE 8 MHz→72 MHz）。【未验证】CubeMX 实际打开（本机无 CubeMX）。
自检：生成后用 tools/ioc_import.py 反导，资源（逻辑名 / 引脚 / 定时器通道 / 串口实例）必须和草稿一致。
"""
import argparse
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

MCU_NAME = {  # CubeMX 的 Mcu.Name 把同封装不同 Flash 的型号并成一组
    "STM32F407VETx": "STM32F407V(E-G)Tx", "STM32F407VGTx": "STM32F407V(E-G)Tx",
    "STM32F103C8Tx": "STM32F103C(8-B)Tx", "STM32F103CBTx": "STM32F103C(8-B)Tx",
}
CLOCK = {
    "stm32f4": {"fam": "STM32F4", "fw": "STM32Cube FW_F4 V1.28.3", "tim": {"APB1": 84_000_000, "APB2": 168_000_000}, "rcc": {
        "HSE_VALUE": 8000000, "PLLSourceVirtual": "RCC_PLLSOURCE_HSE", "PLLM": 4, "PLLN": 168, "SYSCLKSource": "RCC_SYSCLKSOURCE_PLLCLK",
        "SYSCLKFreq_VALUE": 168000000, "HCLKFreq_Value": 168000000, "AHBFreq_Value": 168000000, "APB1CLKDivider": "RCC_HCLK_DIV4",
        "APB1Freq_Value": 42000000, "APB1TimFreq_Value": 84000000, "APB2CLKDivider": "RCC_HCLK_DIV2", "APB2Freq_Value": 84000000,
        "APB2TimFreq_Value": 168000000, "FamilyName": "M"}},
    "stm32f1": {"fam": "STM32F1", "fw": "STM32Cube FW_F1 V1.8.7", "tim": {"APB1": 72_000_000, "APB2": 72_000_000}, "rcc": {
        "PLLSourceVirtual": "RCC_PLLSOURCE_HSE", "PLLMUL": "RCC_PLL_MUL9", "SYSCLKSource": "RCC_SYSCLKSOURCE_PLLCLK",
        "SYSCLKFreq_VALUE": 72000000, "HCLKFreq_Value": 72000000, "AHBFreq_Value": 72000000, "APB1CLKDivider": "RCC_HCLK_DIV2",
        "APB1Freq_Value": 36000000, "APB1TimFreq_Value": 72000000, "APB2Freq_Value": 72000000, "APB2TimFreq_Value": 72000000, "FamilyName": "M"}},
}
NV = "true\\:{p}\\:0\\:false\\:false\\:true\\:{h}\\:true\\:true"


def family_mod(fam: str):
    import importlib
    return importlib.import_module(f"families.{fam}")


def psc_arr(clk: int, hz: float) -> tuple[int, int]:
    """PWM：优先 ARR+1 = 1000 级分辨率；分不出整数就放宽。"""
    for steps in (1000, 2000, 500, 100):
        psc = clk / (hz * steps)
        if psc >= 1 and abs(psc - round(psc)) < 1e-9 and round(psc) <= 65536:
            return round(psc) - 1, steps - 1
    psc = max(1, round(clk / (hz * 1000)))
    return psc - 1, round(clk / (psc * hz)) - 1


def build(b: dict, name: str) -> tuple[str, str]:
    fam = b["mcu"]["family"]
    if fam not in CLOCK:
        raise SystemExit(f"✗ {fam}：gen_ioc 只支持 stm32f1 / stm32f4（MSPM0 走 SysConfig，见 docs/05）")
    F, C = family_mod(fam), CLOCK[fam]
    part = b["mcu"]["part"]
    if part[-1].isdigit():                       # STM32F103C8T6 → CubeMX 用 STM32F103C8Tx
        part = part[:-1] + "x"
    R = b.get("resources") or {}
    todo = [f"{k}.{e.get('name')}" for k, v in R.items() if isinstance(v, list) for e in v if "TODO" in str(e)]
    if todo:   # alloc 没分到的（芯片资源用完）：不写半截 .ioc
        raise SystemExit("✗ 这些资源 alloc 没分到，换更大的芯片或减需求：" + "、".join(todo))
    kv: dict[str, object] = {}
    pins: list[str] = []
    ips: set[str] = {"NVIC", "RCC", "SYS"}
    model: dict = {"fam": fam, "part": part, "tims": {}, "enc": [], "ctrl": None, "uarts": [], "i2c": [], "gpio": list(R.get("gpio") or []), "adc": list(R.get("adc") or [])}
    nvic: dict[str, str] = {"SysTick_IRQn": NV.format(p=0, h="false").replace("true\\:true", "true\\:false", 0)}

    def pin(p, signal, label=None, mode=None):
        pins.append(p); kv[f"{p}.Signal"] = signal
        if mode:
            kv[f"{p}.Mode"] = mode
        if label:
            kv[f"{p}.GPIOParameters"] = "GPIO_Label"; kv[f"{p}.GPIO_Label"] = label
        kv[f"{p}.Locked"] = "true"
    pin("PA13", "SYS_JTMS-SWDIO", mode="Serial_Wire"); pin("PA14", "SYS_JTCK-SWCLK", mode="Serial_Wire")
    for g in R.get("gpio") or []:
        pin(g["pin"], "GPIO_Output" if g.get("dir") == "out" else "GPIO_Input", f"GPIO_{g['name']}")
        if g.get("pull"):
            kv[f"{g['pin']}.GPIO_PuPd"] = {"up": "GPIO_PULLUP", "down": "GPIO_PULLDOWN"}.get(g["pull"], "GPIO_NOPULL")
            kv[f"{g['pin']}.GPIOParameters"] = "GPIO_PuPd,GPIO_Label"
    tims: dict[str, dict] = {}
    for p in R.get("pwm") or []:
        t = tims.setdefault(p["timer"], {"ch": [], "hz": p.get("freq_hz") or 1000})
        t["ch"].append(p["channel"]); pin(p["pin"], f"S_{p['timer']}_CH{p['channel']}", f"PWM_{p['name']}")
    for t, d in tims.items():
        ips.add(t); psc, arr = psc_arr(C["tim"][F.TIMERS[t][0]], d["hz"])
        prm = []
        for ch in sorted(d["ch"]):
            k = f"Channel-PWM\\ Generation{ch}\\ CH{ch}"; kv[f"{t}.{k}"] = f"TIM_CHANNEL_{ch}"; prm.append(f"Channel-PWM Generation{ch} CH{ch}")
        kv[f"{t}.Prescaler"] = psc; kv[f"{t}.Period"] = arr; kv[f"{t}.IPParameters"] = ",".join(prm + ["Prescaler", "Period"])
        model["tims"][t] = {"ch": sorted(d["ch"]), "psc": psc, "arr": arr, "pins": [p["pin"] for p in R["pwm"] if p["timer"] == t]}
    for e in R.get("encoder") or []:
        t = e["timer"]; ips.add(t)
        for ab, ch, p in (("A", 1, e["pin_a"]), ("B", 2, e["pin_b"])):
            pin(p, f"S_{t}_CH{ch}", f"ENC_{e['name']}_{ab}"); kv[f"SH.S_{t}_CH{ch}.0"] = f"{t}_CH{ch},Encoder_Interface"; kv[f"SH.S_{t}_CH{ch}.ConfNb"] = 1
        model["enc"].append({"t": t, "pins": [e["pin_a"], e["pin_b"]]}); kv[f"{t}.EncoderMode"] = "TIM_ENCODERMODE_TI12"; kv[f"{t}.Period"] = 65535; kv[f"{t}.IPParameters"] = "EncoderMode,Period"
    used_t = {t for t in kv and [k.split(".")[0] for k in kv] if t.startswith("TIM")} | set(tims)
    ctrl = next((t for t in ("TIM6", "TIM7") if t in F.TIMERS and t not in used_t), None) \
        or next((t for t in reversed(list(F.TIMERS)) if t not in used_t), None)
    if ctrl:   # 节拍定时器 CTRL：1 kHz 更新中断，无引脚
        ips.add(ctrl); clk = C["tim"][F.TIMERS[ctrl][0]]
        kv[f"{ctrl}.Prescaler"] = clk // 1_000_000 - 1; kv[f"{ctrl}.Period"] = 999; kv[f"{ctrl}.IPParameters"] = "Prescaler,Period"
        kv[f"VP_{ctrl}_VS_ClockSourceINT.Mode"] = "Internal" if ctrl not in ("TIM6", "TIM7") else "Enable_Timer"
        kv[f"VP_{ctrl}_VS_ClockSourceINT.Signal"] = f"{ctrl}_VS_ClockSourceINT"
        nvic[F.TIMERS[ctrl][4] + "n"] = NV.format(p=1, h="true")
        model["ctrl"] = {"t": ctrl, "psc": clk // 1_000_000 - 1, "arr": 999, "irq": F.TIMERS[ctrl][4] + "n"}
    dma_req, dma_used = [], set()

    def dma_inst(tab, inst):
        for c in tab.get(inst, []):
            if c[:2] not in dma_used:
                dma_used.add(c[:2])
                return (f"DMA{c[0]}_Stream{c[1]}" if fam == "stm32f4" else f"DMA{c[0]}_Channel{c[1]}"), c
        return None, None
    for u in R.get("uart") or []:
        i = u["instance"]; ips.add(i)
        pin(u["tx"], f"{i}_TX", f"UART_{u['name']}_TX", "Asynchronous"); pin(u["rx"], f"{i}_RX", f"UART_{u['name']}_RX", "Asynchronous")
        kv[f"{i}.BaudRate"] = u.get("baud", 115200); kv[f"{i}.VirtualMode"] = "VM_ASYNC"; kv[f"{i}.IPParameters"] = "BaudRate,VirtualMode"
        irq = F.UARTS[i][4]
        nvic[irq + "n"] = NV.format(p=5, h="true")
        mu = {"i": i, "tx": u["tx"], "rx": u["rx"], "baud": u.get("baud", 115200), "irq": irq + "n", "dma": []}; model["uarts"].append(mu)
        if u.get("dma", True) is not False:
            for d, tab, mode in (("RX", F.UART_DMA_RX, "DMA_CIRCULAR"), ("TX", F.UART_DMA_TX, "DMA_NORMAL")):
                inst, c = dma_inst(tab, i)
                if inst:
                    ips.add("DMA"); n = len(dma_req); dma_req.append(f"{i}_{d}"); pre = f"Dma.{i}_{d}.{n}"
                    kv[f"{pre}.Instance"] = inst; kv[f"{pre}.Direction"] = "DMA_PERIPH_TO_MEMORY" if d == "RX" else "DMA_MEMORY_TO_PERIPH"
                    kv[f"{pre}.Mode"] = mode; kv[f"{pre}.PeriphInc"] = "DMA_PINC_DISABLE"; kv[f"{pre}.MemInc"] = "DMA_MINC_ENABLE"
                    kv[f"{pre}.PeriphDataAlignment"] = "DMA_PDATAALIGN_BYTE"; kv[f"{pre}.MemDataAlignment"] = "DMA_MDATAALIGN_BYTE"
                    kv[f"{pre}.Priority"] = "DMA_PRIORITY_LOW"
                    if fam == "stm32f4":
                        kv[f"{pre}.Channel"] = f"DMA_CHANNEL_{c[2]}"; kv[f"{pre}.FIFOMode"] = "DMA_FIFOMODE_DISABLE"
                    kv[f"{pre}.RequestParameters"] = "Instance,Direction,PeriphInc,MemInc,PeriphDataAlignment,MemDataAlignment,Mode,Priority" + (",Channel,FIFOMode" if fam == "stm32f4" else "")
                    nvic[f"{inst}_IRQn"] = NV.format(p=5, h="false")
                    mu["dma"].append({"dir": d, "inst": inst, "ch": c[2], "mode": mode})
    for q in R.get("i2c") or []:
        i = q["instance"]; ips.add(i)
        pin(q["scl"], f"{i}_SCL", f"I2C_{q['name']}_SCL", "I2C"); pin(q["sda"], f"{i}_SDA", f"I2C_{q['name']}_SDA", "I2C")
        kv[f"{i}.ClockSpeed"] = q.get("speed_hz", 100000); kv[f"{i}.I2C_Mode"] = "I2C_Fast" if q.get("speed_hz", 0) > 100000 else "I2C_Standard"
        kv[f"{i}.IPParameters"] = "ClockSpeed,I2C_Mode"
        model["i2c"].append({"i": i, "scl": q["scl"], "sda": q["sda"], "speed": q.get("speed_hz", 100000)})
    for a in R.get("adc") or []:
        inst = a.get("instance", "ADC1"); ips.add(inst); ch = a.get("channel")
        pin(a["pin"], f"ADCx_IN{ch}" if fam == "stm32f4" else f"{inst}_IN{ch}", f"ADC_{a['name']}")
        if fam == "stm32f4":
            kv[f"SH.ADCx_IN{ch}.0"] = f"{inst}_IN{ch},IN{ch}"; kv[f"SH.ADCx_IN{ch}.ConfNb"] = 1
    kv["VP_SYS_VS_Systick.Mode"] = "SysTick"; kv["VP_SYS_VS_Systick.Signal"] = "SYS_VS_Systick"
    nvic_lines = {"NVIC.PriorityGroup": "NVIC_PRIORITYGROUP_4", **{f"NVIC.{k}": v for k, v in nvic.items()}}
    head = {"File.Version": 6, "KeepUserPlacement": "false", "Mcu.Family": C["fam"], "Mcu.Name": MCU_NAME.get(part, part), "Mcu.UserName": part,
            "Mcu.CPN": part[:-1] + "6" if part.endswith("x") else part, "Mcu.Package": F.PACKAGE if hasattr(F, "PACKAGE") else "LQFP100",
            "Mcu.ThirdPartyNb": 0, "Mcu.ContextNb": 1, "board": "custom"}
    for n, ip in enumerate(sorted(ips)):
        head[f"Mcu.IP{n}"] = ip
    head["Mcu.IPNb"] = len(ips)
    vps = [k.rsplit(".", 1)[0] for k in kv if k.startswith("VP_") and k.endswith(".Mode")]
    allp = list(dict.fromkeys(pins)) + vps
    for n, p in enumerate(allp):
        head[f"Mcu.Pin{n}"] = p
    head["Mcu.PinsNb"] = len(allp)
    if dma_req:
        for n, r in enumerate(dma_req):
            head[f"Dma.Request{n}"] = r
        head["Dma.RequestsNb"] = len(dma_req)
    rcc = {f"RCC.{k}": v for k, v in C["rcc"].items()}; rcc["RCC.IPParameters"] = ",".join(C["rcc"])
    pm = {"ProjectManager.ProjectName": name, "ProjectManager.ProjectFileName": f"{name}.ioc", "ProjectManager.TargetToolchain": "MDK-ARM V5.32",
          "ProjectManager.FirmwarePackage": C["fw"], "ProjectManager.KeepUserCode": "true", "ProjectManager.CoupleFile": "true",
          "ProjectManager.MainLocation": "Core/Src", "ProjectManager.DeviceId": part, "ProjectManager.HeapSize": "0x200", "ProjectManager.StackSize": "0x400",
          "ProjectManager.DefaultFWLocation": "true", "ProjectManager.LastFirmware": "true", "ProjectManager.NoMain": "false"}
    allkv = {**head, **nvic_lines, **rcc, **pm, **kv}
    body = "\n".join(f"{k}={v}" for k, v in sorted(allkv.items(), key=lambda x: x[0]))
    return ("#MicroXplorer Configuration settings - do not modify\n"
            f"# 由 tools/gen_ioc.py 从 board.yaml 草稿生成（{b.get('name', '')}）。用 CubeMX 打开 → 核对 → GENERATE CODE（工具链 MDK-ARM）。\n" + body + "\n"), (ctrl or ""), model


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board"); ap.add_argument("-o", required=True); ap.add_argument("--name")
    a = ap.parse_args(argv)
    b = yaml.safe_load(pathlib.Path(a.board).read_text(encoding="utf-8"))
    out = pathlib.Path(a.o); name = a.name or out.stem
    text, ctrl, _ = build(b, name)
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(text, encoding="utf-8")
    print(f"✓ 写入 {out}（{b['mcu']['part']}，节拍定时器 CTRL={ctrl or '无空闲定时器'}）")
    print(f"下一步（人做一次）：CubeMX 打开 {out.name} → GENERATE CODE；然后项目页第 ③ 步“导入已有工程”选 {out.parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
