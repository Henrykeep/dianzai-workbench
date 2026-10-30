#!/usr/bin/env python3
"""gen_core.py —— 没有 CubeMX 时的【合成 Core】：按 gen_ioc 同一份模型，仿 CubeMX 生成结构写 Core/（main.c 带 USER CODE 区、
*_hal_msp.c、*_it.c、hal_conf.h、main.h），让“从零新建”的工程在本机就能用 arm-none-eabi-gcc + third_party 的 STM32CubeF1/F4 HAL 编译。

  python3 tools/gen_core.py <board.yaml 草稿> <CubeMX 工程目录>     （目录里应已有 gen_ioc 写的 <名>.ioc）

结构照抄 boards/stm32f407-skystar-cubemx/cubemx/Core（仓库里的合成样例）；hal_conf 由 HAL 自带的 *_hal_conf_template.h 复制、只改 HSE_VALUE。
**不是 CubeMX 的输出**：每个文件头都标【合成】。用户有 CubeMX 时打开 .ioc 点 GENERATE CODE 覆盖即可（工作台只用 USER CODE 区）。
目前覆盖：GPIO、PWM（含 TIM1/TIM8 MOE）、编码器、节拍定时器 CTRL、USART + DMA（RX Circular / TX Normal）、I2C。ADC/DAC/SPI 不合成（报错，走 CubeMX）。
F1 只支持默认引脚组（不写 AFIO 重映射）；用到重映射组就报错。
"""
import argparse
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import gen_ioc  # noqa: E402

HDR = "/* 【合成】tools/gen_core.py 仿 STM32CubeMX 生成结构写出，非 CubeMX 真实输出、未上板。用 CubeMX 打开同目录 .ioc → GENERATE CODE 可覆盖。 */\n"


def pn(p):  # "PB13" -> ("GPIOB", 13)
    m = re.match(r"P([A-K])(\d+)$", p); return f"GPIO{m[1]}", int(m[2])


def group(pins):
    g = {}
    for p in pins:
        port, n = pn(p); g.setdefault(port, []).append(f"GPIO_PIN_{n}")
    return g


def build(b: dict, name: str) -> dict[str, str]:
    _, _, m = gen_ioc.build(b, name)
    f4 = m["fam"] == "stm32f4"; s = "f4" if f4 else "f1"; F = gen_ioc.family_mod(m["fam"])
    R = b.get("resources") or {}
    for k in ("adc", "dac", "spi"):
        if R.get(k):
            raise SystemExit(f"✗ 合成 Core 不含 {k}：用 CubeMX 打开 .ioc 点 GENERATE CODE")
    if not f4:
        def chk(inst, pins, remap):
            if remap.get(inst) and not any(set(pins) <= set(g.values() if isinstance(g, dict) else g) for g in remap[inst][:1]):
                raise SystemExit(f"✗ {inst} 用了 F1 重映射引脚 {pins}：合成 Core 不写 AFIO 重映射，用 CubeMX 生成")
        for t, d in m["tims"].items(): chk(t, d["pins"], F.TIMER_REMAP)
        for e in m["enc"]: chk(e["t"], e["pins"], F.TIMER_REMAP)
        for u in m["uarts"]: chk(u["i"], [u["tx"], u["rx"]], F.UART_REMAP)
        for q in m["i2c"]: chk(q["i"], [q["scl"], q["sda"]], F.I2C_REMAP)
    hdl = lambda t: "h" + t.lower()
    uh = lambda i: "huart" + re.sub(r"\D", "", i)
    tims = sorted(set(m["tims"]) | {e["t"] for e in m["enc"]} | ({m["ctrl"]["t"]} if m["ctrl"] else set()), key=lambda t: int(t[3:]))
    decl = [f"TIM_HandleTypeDef {hdl(t)};" for t in tims] + [f"UART_HandleTypeDef {uh(u['i'])};" for u in m["uarts"]] + \
           [f"I2C_HandleTypeDef h{q['i'].lower()};" for q in m["i2c"]]
    dmas = [(u, d) for u in m["uarts"] for d in u["dma"]]
    dn = lambda u, d: f"hdma_{u['i'].lower()}_{d['dir'].lower()}"
    decl += [f"DMA_HandleTypeDef {dn(u, d)};" for u, d in dmas]
    inits, fns = ["MX_GPIO_Init"] + (["MX_DMA_Init"] if dmas else []), []
    # 时钟（数值同 gen_ioc 的 CLOCK，来自用户真实工程）
    if f4:
        clk = """  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);
  o.OscillatorType = RCC_OSCILLATORTYPE_HSE; o.HSEState = RCC_HSE_ON;
  o.PLL.PLLState = RCC_PLL_ON; o.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  o.PLL.PLLM = 4; o.PLL.PLLN = 168; o.PLL.PLLP = RCC_PLLP_DIV2; o.PLL.PLLQ = 4;
  if (HAL_RCC_OscConfig(&o) != HAL_OK) Error_Handler();
  c.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK|RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  c.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK; c.AHBCLKDivider = RCC_SYSCLK_DIV1;
  c.APB1CLKDivider = RCC_HCLK_DIV4; c.APB2CLKDivider = RCC_HCLK_DIV2;
  if (HAL_RCC_ClockConfig(&c, FLASH_LATENCY_5) != HAL_OK) Error_Handler();"""
    else:
        clk = """  o.OscillatorType = RCC_OSCILLATORTYPE_HSE; o.HSEState = RCC_HSE_ON; o.HSEPredivValue = RCC_HSE_PREDIV_DIV1;
  o.HSIState = RCC_HSI_ON; o.PLL.PLLState = RCC_PLL_ON; o.PLL.PLLSource = RCC_PLLSOURCE_HSE; o.PLL.PLLMUL = RCC_PLL_MUL9;
  if (HAL_RCC_OscConfig(&o) != HAL_OK) Error_Handler();
  c.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK|RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  c.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK; c.AHBCLKDivider = RCC_SYSCLK_DIV1;
  c.APB1CLKDivider = RCC_HCLK_DIV2; c.APB2CLKDivider = RCC_HCLK_DIV1;
  if (HAL_RCC_ClockConfig(&c, FLASH_LATENCY_2) != HAL_OK) Error_Handler();"""
    fns.append("void SystemClock_Config(void)\n{\n  RCC_OscInitTypeDef o = {0};\n  RCC_ClkInitTypeDef c = {0};\n" + clk + "\n}")
    # GPIO
    g = ["  GPIO_InitTypeDef g = {0};"] + [f"  __HAL_RCC_GPIO{x}_CLK_ENABLE();" for x in "ABCDE" if f4 or x in "ABCD"]
    outs = [x for x in m["gpio"] if x.get("dir") == "out"]
    for port, pins in group([x["pin"] for x in outs]).items():
        g += [f"  HAL_GPIO_WritePin({port}, {'|'.join(pins)}, GPIO_PIN_RESET);",
              f"  g.Pin = {'|'.join(pins)}; g.Mode = GPIO_MODE_OUTPUT_PP; g.Pull = GPIO_NOPULL; g.Speed = GPIO_SPEED_FREQ_LOW;", f"  HAL_GPIO_Init({port}, &g);"]
    for x in m["gpio"]:
        if x.get("dir") != "out":
            port, n = pn(x["pin"]); pull = {"up": "GPIO_PULLUP", "down": "GPIO_PULLDOWN"}.get(x.get("pull"), "GPIO_NOPULL")
            g += [f"  g.Pin = GPIO_PIN_{n}; g.Mode = GPIO_MODE_INPUT; g.Pull = {pull};", f"  HAL_GPIO_Init({port}, &g);"]
    fns.append("static void MX_GPIO_Init(void)\n{\n" + "\n".join(g) + "\n}")
    if dmas:
        ctrls = sorted({d["inst"].split("_")[0] for _, d in dmas})
        fns.append("static void MX_DMA_Init(void)\n{\n" + "\n".join(f"  __HAL_RCC_{c}_CLK_ENABLE();" for c in ctrls) + "\n" +
                   "\n".join(f"  HAL_NVIC_SetPriority({d['inst']}_IRQn, 5, 0); HAL_NVIC_EnableIRQ({d['inst']}_IRQn);" for _, d in dmas) + "\n}")
    adv = ("TIM1", "TIM8")
    for t in tims:
        h = hdl(t); body = [f"  {h}.Instance = {t};", f"  {h}.Init.CounterMode = TIM_COUNTERMODE_UP;", f"  {h}.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;"]
        if t in m["tims"]:
            d = m["tims"][t]
            body += [f"  {h}.Init.Prescaler = {d['psc']};", f"  {h}.Init.Period = {d['arr']};", f"  {h}.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;",
                     f"  if (HAL_TIM_PWM_Init(&{h}) != HAL_OK) Error_Handler();", "  TIM_OC_InitTypeDef oc = {0};",
                     "  oc.OCMode = TIM_OCMODE_PWM1; oc.Pulse = 0; oc.OCPolarity = TIM_OCPOLARITY_HIGH; oc.OCFastMode = TIM_OCFAST_DISABLE;"]
            body += [f"  if (HAL_TIM_PWM_ConfigChannel(&{h}, &oc, TIM_CHANNEL_{c}) != HAL_OK) Error_Handler();" for c in d["ch"]]
            if t in adv:
                body += ["  TIM_BreakDeadTimeConfigTypeDef bdt = {0};", "  bdt.OffStateRunMode = TIM_OSSR_DISABLE; bdt.OffStateIDLEMode = TIM_OSSI_DISABLE; bdt.LockLevel = TIM_LOCKLEVEL_OFF;",
                         "  bdt.BreakState = TIM_BREAK_DISABLE; bdt.BreakPolarity = TIM_BREAKPOLARITY_HIGH; bdt.AutomaticOutput = TIM_AUTOMATICOUTPUT_DISABLE;",
                         f"  if (HAL_TIMEx_ConfigBreakDeadTime(&{h}, &bdt) != HAL_OK) Error_Handler();"]
            body.append(f"  HAL_TIM_MspPostInit(&{h});")
        elif any(e["t"] == t for e in m["enc"]):
            body += [f"  {h}.Init.Prescaler = 0;", f"  {h}.Init.Period = 65535;", "  TIM_Encoder_InitTypeDef e = {0};", "  e.EncoderMode = TIM_ENCODERMODE_TI12;",
                     "  e.IC1Polarity = TIM_ICPOLARITY_RISING; e.IC1Selection = TIM_ICSELECTION_DIRECTTI; e.IC1Prescaler = TIM_ICPSC_DIV1; e.IC1Filter = 6;",
                     "  e.IC2Polarity = TIM_ICPOLARITY_RISING; e.IC2Selection = TIM_ICSELECTION_DIRECTTI; e.IC2Prescaler = TIM_ICPSC_DIV1; e.IC2Filter = 6;",
                     f"  if (HAL_TIM_Encoder_Init(&{h}, &e) != HAL_OK) Error_Handler();"]
        else:
            c = m["ctrl"]; body += [f"  {h}.Init.Prescaler = {c['psc']};", f"  {h}.Init.Period = {c['arr']};", f"  if (HAL_TIM_Base_Init(&{h}) != HAL_OK) Error_Handler();"]
        inits.append(f"MX_{t}_Init"); fns.append(f"static void MX_{t}_Init(void)\n{{\n" + "\n".join(body) + "\n}")
    for u in m["uarts"]:
        h = uh(u["i"]); n = "MX_" + u["i"] + "_UART_Init"; inits.append(n)
        fns.append(f"static void {n}(void)\n{{\n  {h}.Instance = {u['i']};\n  {h}.Init.BaudRate = {u['baud']};\n  {h}.Init.WordLength = UART_WORDLENGTH_8B;\n"
                   f"  {h}.Init.StopBits = UART_STOPBITS_1;\n  {h}.Init.Parity = UART_PARITY_NONE;\n  {h}.Init.Mode = UART_MODE_TX_RX;\n"
                   f"  {h}.Init.HwFlowCtl = UART_HWCONTROL_NONE;\n  {h}.Init.OverSampling = UART_OVERSAMPLING_16;\n  if (HAL_UART_Init(&{h}) != HAL_OK) Error_Handler();\n}}")
    for q in m["i2c"]:
        h = "h" + q["i"].lower(); n = f"MX_{q['i']}_Init"; inits.append(n)
        fns.append(f"static void {n}(void)\n{{\n  {h}.Instance = {q['i']};\n  {h}.Init.ClockSpeed = {q['speed']};\n  {h}.Init.DutyCycle = I2C_DUTYCYCLE_2;\n"
                   f"  {h}.Init.OwnAddress1 = 0;\n  {h}.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;\n  {h}.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;\n"
                   f"  {h}.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;\n  {h}.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;\n  if (HAL_I2C_Init(&{h}) != HAL_OK) Error_Handler();\n}}")
    proto = ["void SystemClock_Config(void);"] + [f"static void {n}(void);" for n in inits] + ["void HAL_TIM_MspPostInit(TIM_HandleTypeDef *htim);"]
    main = (HDR.replace("/* ", "/* USER CODE BEGIN Header */\n/* ", 1) + "/* USER CODE END Header */\n#include \"main.h\"\n\n/* USER CODE BEGIN Includes */\n#include \"dz_cubemx.h\"\n/* USER CODE END Includes */\n\n"
            + "\n".join(decl) + "\n\n" + "\n".join(proto) + "\n\nint main(void)\n{\n  HAL_Init();\n  SystemClock_Config();\n" + "".join(f"  {n}();\n" for n in inits)
            + "  /* USER CODE BEGIN 2 */\n  dz_cubemx_start();\n  /* USER CODE END 2 */\n  /* USER CODE BEGIN WHILE */\n  while (1)\n  {\n    /* USER CODE END WHILE */\n\n"
            "    /* USER CODE BEGIN 3 */\n    dz_cubemx_loop();\n  }\n  /* USER CODE END 3 */\n}\n\n" + "\n\n".join(fns)
            + "\n\nvoid Error_Handler(void)\n{\n  __disable_irq();\n  while (1) { }\n}\n")
    # MSP
    af = lambda inst, kind: None if not f4 else (f"GPIO_AF{F.TIMER_AF[inst]}_{inst}" if kind == "tim" else f"GPIO_AF{F.UARTS[inst][0]}_{inst}" if kind == "uart" else f"GPIO_AF4_{inst}")
    def pins_init(pins, mode, pull, alt):
        o = []
        for port, ps in group(pins).items():
            o.append(f"    g.Pin = {'|'.join(ps)}; g.Mode = {mode}; g.Pull = {pull}; g.Speed = GPIO_SPEED_FREQ_{'VERY_HIGH' if f4 else 'HIGH'};" + (f" g.Alternate = {alt};" if f4 and alt else ""))
            o.append(f"    HAL_GPIO_Init({port}, &g);")
        return o
    msp = [HDR + '#include "main.h"', "\n".join(f"extern DMA_HandleTypeDef {dn(u, d)};" for u, d in dmas),
           "void HAL_MspInit(void)\n{\n" + ("  __HAL_RCC_SYSCFG_CLK_ENABLE();\n  __HAL_RCC_PWR_CLK_ENABLE();\n" if f4 else "  __HAL_RCC_AFIO_CLK_ENABLE();\n  __HAL_RCC_PWR_CLK_ENABLE();\n  __HAL_AFIO_REMAP_SWJ_NOJTAG();\n")
           + "  HAL_NVIC_SetPriorityGrouping(NVIC_PRIORITYGROUP_4);\n}"]
    pw = [t for t in tims if t in m["tims"]]; en = [e for e in m["enc"]]; ct = m["ctrl"]
    if pw:
        msp.append("void HAL_TIM_PWM_MspInit(TIM_HandleTypeDef *h)\n{\n" + "\n".join(f"  if (h->Instance == {t}) __HAL_RCC_{t}_CLK_ENABLE();" for t in pw) + "\n}")
        msp.append("void HAL_TIM_MspPostInit(TIM_HandleTypeDef *h)\n{\n  GPIO_InitTypeDef g = {0};\n" + "\n".join(
            f"  if (h->Instance == {t}) {{\n" + "\n".join(pins_init(m["tims"][t]["pins"], "GPIO_MODE_AF_PP", "GPIO_NOPULL", af(t, "tim"))) + "\n  }" for t in pw) + "\n}")
    else:
        msp.append("void HAL_TIM_MspPostInit(TIM_HandleTypeDef *h) { (void)h; }")
    if en:
        msp.append("void HAL_TIM_Encoder_MspInit(TIM_HandleTypeDef *h)\n{\n  GPIO_InitTypeDef g = {0};\n" + "\n".join(
            f"  if (h->Instance == {e['t']}) {{\n    __HAL_RCC_{e['t']}_CLK_ENABLE();\n" + "\n".join(pins_init(e["pins"], "GPIO_MODE_AF_PP" if f4 else "GPIO_MODE_INPUT", "GPIO_PULLUP", af(e["t"], "tim"))) + "\n  }" for e in en) + "\n}")
    if ct:
        msp.append(f"void HAL_TIM_Base_MspInit(TIM_HandleTypeDef *h)\n{{\n  if (h->Instance == {ct['t']}) {{\n    __HAL_RCC_{ct['t']}_CLK_ENABLE();\n"
                   f"    HAL_NVIC_SetPriority({ct['irq']}, 1, 0);\n    HAL_NVIC_EnableIRQ({ct['irq']});\n  }}\n}}")
    if m["uarts"]:
        U = []
        for u in m["uarts"]:
            x = [f"  if (h->Instance == {u['i']}) {{", f"    __HAL_RCC_{u['i']}_CLK_ENABLE();"]
            if f4:
                x += pins_init([u["tx"], u["rx"]], "GPIO_MODE_AF_PP", "GPIO_PULLUP", af(u["i"], "uart"))
            else:
                x += pins_init([u["tx"]], "GPIO_MODE_AF_PP", "GPIO_NOPULL", None) + pins_init([u["rx"]], "GPIO_MODE_INPUT", "GPIO_PULLUP", None)
            for d in u["dma"]:
                v = dn(u, d)
                x += [f"    {v}.Instance = {d['inst']};"] + ([f"    {v}.Init.Channel = DMA_CHANNEL_{d['ch']};", f"    {v}.Init.FIFOMode = DMA_FIFOMODE_DISABLE;"] if f4 else []) + [
                    f"    {v}.Init.Direction = {'DMA_PERIPH_TO_MEMORY' if d['dir'] == 'RX' else 'DMA_MEMORY_TO_PERIPH'};", f"    {v}.Init.PeriphInc = DMA_PINC_DISABLE;",
                    f"    {v}.Init.MemInc = DMA_MINC_ENABLE;", f"    {v}.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;", f"    {v}.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;",
                    f"    {v}.Init.Mode = {d['mode']};", f"    {v}.Init.Priority = DMA_PRIORITY_LOW;", f"    if (HAL_DMA_Init(&{v}) != HAL_OK) Error_Handler();",
                    f"    __HAL_LINKDMA(h, hdma{d['dir'].lower()}, {v});"]
            x += [f"    HAL_NVIC_SetPriority({u['irq']}, 5, 0); HAL_NVIC_EnableIRQ({u['irq']});", "  }"]
            U += x
        msp.append("void HAL_UART_MspInit(UART_HandleTypeDef *h)\n{\n  GPIO_InitTypeDef g = {0};\n" + "\n".join(U) + "\n}")
    if m["i2c"]:
        msp.append("void HAL_I2C_MspInit(I2C_HandleTypeDef *h)\n{\n  GPIO_InitTypeDef g = {0};\n" + "\n".join(
            f"  if (h->Instance == {q['i']}) {{\n" + "\n".join(pins_init([q["scl"], q["sda"]], "GPIO_MODE_AF_OD", "GPIO_PULLUP", af(q["i"], "i2c"))) + f"\n    __HAL_RCC_{q['i']}_CLK_ENABLE();\n  }}" for q in m["i2c"]) + "\n}")
    it = [HDR + f'#include "main.h"\n#include "stm32{s}xx_it.h"'] + [f"extern DMA_HandleTypeDef {dn(u, d)};" for u, d in dmas] + \
         [f"extern UART_HandleTypeDef {uh(u['i'])};" for u in m["uarts"]] + ([f"extern TIM_HandleTypeDef {hdl(ct['t'])};"] if ct else []) + [
         "void NMI_Handler(void) { while (1) { } }", "void HardFault_Handler(void) { while (1) { } }", "void SysTick_Handler(void) { HAL_IncTick(); }"] + \
         [f"void {d['inst']}_IRQHandler(void) {{ HAL_DMA_IRQHandler(&{dn(u, d)}); }}" for u, d in dmas] + \
         [f"void {u['irq'][:-1]}Handler(void) {{ HAL_UART_IRQHandler(&{uh(u['i'])}); }}" for u in m["uarts"]] + \
         ([f"void {ct['irq'][:-1]}Handler(void) {{ HAL_TIM_IRQHandler(&{hdl(ct['t'])}); }}"] if ct else [])
    mh = [HDR, "#ifndef __MAIN_H", "#define __MAIN_H", f'#include "stm32{s}xx_hal.h"', "/* USER CODE BEGIN Includes */", "/* USER CODE END Includes */", "void Error_Handler(void);"]
    for x in m["gpio"]:
        port, n = pn(x["pin"]); mh += [f"#define GPIO_{x['name']}_Pin GPIO_PIN_{n}", f"#define GPIO_{x['name']}_GPIO_Port {port}"]
    mh += ["/* USER CODE BEGIN Private defines */", "/* USER CODE END Private defines */", "#endif", ""]
    tp = ROOT / f"third_party/vendored/st_hal_conf/stm32{s}xx_hal_conf_template.h"     # 随仓库带的 ST 模板（BSD-3），见该目录 SOURCE.md
    if not tp.exists():
        tp = ROOT / f"third_party/stm32{s}xx-hal-driver/Inc/stm32{s}xx_hal_conf_template.h"
    if not tp.exists():
        sys.exit(f"✗ 缺 stm32{s}xx_hal_conf_template.h（STM32 HAL 未拉取）：在仓库根目录运行 make fetch")
    tpl = re.sub(r"\A/\* Source: .*?\*/\n", "", tp.read_text(encoding="utf-8"))
    keep = {"", "GPIO", "RCC", "FLASH", "PWR", "CORTEX", "DMA", "EXTI", "TIM", "UART"} | ({"I2C"} if m["i2c"] else set())
    tpl = re.sub(r"^#define HAL_(\w*?)_?MODULE_ENABLED\b", lambda x: x[0] if x[1] in keep else "/* " + x[0] + " */", tpl, flags=re.M)  # 同 CubeMX：只开用到的模块
    conf = HDR + re.sub(r"(#define HSE_VALUE\s+)\(?\s*\d+U?\s*\)?", r"\g<1>8000000U", tpl, count=1)
    return {"Core/Src/main.c": main, f"Core/Src/stm32{s}xx_hal_msp.c": "\n\n".join(x for x in msp if x) + "\n",
            f"Core/Src/stm32{s}xx_it.c": "\n".join(it) + "\n", f"Core/Inc/stm32{s}xx_it.h": HDR + "#pragma once\n",
            "Core/Inc/main.h": "\n".join(mh), f"Core/Inc/stm32{s}xx_hal_conf.h": conf,
            "Core/Src/syscalls.c": (ROOT / "boards/stm32f407-skystar-cubemx/cubemx/Core/Src/syscalls.c").read_text(encoding="utf-8")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board"); ap.add_argument("dir"); ap.add_argument("--name")
    a = ap.parse_args(argv)
    b = yaml.safe_load(pathlib.Path(a.board).read_text(encoding="utf-8")); d = pathlib.Path(a.dir)
    for rel, text in build(b, a.name or d.name).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True); (d / rel).write_text(text, encoding="utf-8")
    print(f"✓ 合成 Core 写入 {d}/Core（非 CubeMX 输出；有 CubeMX 时打开 .ioc 点 GENERATE CODE 覆盖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
