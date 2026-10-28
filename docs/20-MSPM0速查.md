# 20 · MSPM0 速查（写给 AI 和赶时间的人）

只列最常踩的坑。芯片事实以 SDK 头文件 `source/ti/devices/msp/m0p/mspm0g350x.h` 和 TRM 为准。

- **配置唯一来源是 `.syscfg`**：改引脚要改 `boards/<板>/ccs/*.syscfg` 和 board.yaml，然后跑 `tools/syscfg_gen.sh <板> --write`。不要手改 `syscfg/ti_msp_dl_config.*`，CI 会和生成结果比对。
- **宏名是 SysConfig 派生的**：`GPIO_<名>_PORT`、`GPIO_<名>_<名>_PIN`（引脚 `$name` 取逻辑名，组内不能重名）、`PWM_<定时器>_INST`、`ENC_<名>_INST`、`TIMER_<名>_INST`、`UART_<名>_INST`。
- **定时器计数时钟**：SysConfig 不导出 `TIMER_*_CLK_FREQ`，要在 board.yaml 的 timer 条目里写 `clk_hz`（分频后的值）。
- **只有 TIMG8 带 QEI**（G3507）：第二路编码器用 GPIO 双边沿中断（`mode: gpio_isr`）。QEI 计数器是 16 位，差分一律用 `dz_wrap16_delta`（`firmware/common/dz_wrap.h`）。
- **低 PPR 测速**：设 `encoder_cfg_t.window_n`（滑动窗口）。真 M/T 法要边沿捕获，目前没实现。
- **DriverLib 名字要在 SDK 头里真实存在**：check_deps 的 D1 规则会扫描。TIMA 实例不能传给 `DL_TimerG_*`。
- **编译器只选一种**：仓库 Makefile 用 arm-none-eabi-gcc；CCS 默认用 tiarmclang。两者的 .o/.a 不能混用（docs/16）。
- **版本锁**：SDK 2.11.00.07 + SysConfig 1.28.0.4712。
- **PA0 是开漏**（LP 板 LED1）：不能当推挽输出用。
- **板子**：`mspm0g3507-tianmengxing`（引脚还没对照原理图）、`mspm0g3507-launchpad`（LED/KEY/UART 引脚对照过 SDK 例程）。两块都**没上板**。
- **调试**：LP 板用板载 XDS110（CCS 或 OpenOCD）；第三方板用 DAPLink + pyOCD。SWD 在 PA19/PA20。
