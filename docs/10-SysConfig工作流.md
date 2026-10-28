# 10 TI MSPM0 + SysConfig 工作流

> 标注约定：**【已实测】** = 本仓库在 PC 上用测试/编译实际跑过（2026-10-28，Asia/Shanghai）；**【未验证】** = 设计意图或推断，尚未在真实硬件上做实验。实验是检验真理的唯一标准——【未验证】的内容上板前不要当结论。

与 CubeMX 对称：`.syscfg` 是唯一配置源，生成 `ti_msp_dl_config.{h,c}`，移植层 `ports/mspm0-driverlib`只调用 DriverLib（`DL_*`，check_deps P2）。

1. SysConfig 中按 05 的标签约定命名（GPIO_/PWM_/UART_…）。
2. `python3 tools/syscfg_import.py <工程>.syscfg` 打印 GPIO/PWM/UART/ENC/TIMER（ADC 仍报 TODO）；`--check boards/<板>/board.yaml` 比对。命名：`GPIO_<名>`+引脚名 `PIN`、`PWM_<定时器>`（如 PWM_TIMG0，逻辑名在 board.yaml 起）、`ENC_<名>`（QEI 模块或 GPIO 组，引脚名以 A/B 结尾）、`TIMER_<名>`、`UART_<名>`；TI 例程风格 `QEI_0`/`assignedPort+assignedPin` 也认。
3. 板卡：`boards/mspm0g3507-tianmengxing`（立创·天猛星 MSPM0G3507）——引脚与 .syscfg 均 TODO，resources 为空，只通过 schema 校验。

- 【已实测】syscfg_import 自检：合成样例 + 3 个 TI SDK 2.11 官方例程 .syscfg（真实导出格式）；`ccs/tianmengxing.syscfg` 与 board.yaml 一致（make check）。
- 【未验证】合成样例未经真实 SysConfig 打开；移植层未实现；天猛星未上板。

## 参考来源
- TI SysConfig（https://www.ti.com/tool/SYSCONFIG）、MSPM0-SDK（https://www.ti.com/tool/MSPM0-SDK）。

## 移植层 ports/mspm0-driverlib（0.1.0）
- 实例名约定与实现见 `ports/mspm0-driverlib/README.md`：GPIO_<名>（组内引脚 PIN）、PWM_<定时器>、ENC_<名>、UART_<名>、TIMER_<名>。
- 第二路编码器：G3507 只有 TIMG8 有 QEI，另一路用 board.yaml `encoder.mode: gpio_isr`（两脚双边沿中断、软件 4 倍频）。
- 【已实测（仅编译）】`make BOARD=mspm0g3507-tianmengxing APP=car_2wd`（FLASH 约 15 KB / RAM 约 2.2 KB）。
- 【未验证】上板行为；`boards/mspm0g3507-tianmengxing/syscfg/ti_msp_dl_config.{c,h}` 是按 TI 命名手写的合成样例，引脚未对照天猛星原理图。

## SysConfig CLI（2026-10 起入 CI）
- `tools/syscfg_gen.sh`：调用 `sysconfig_cli.sh --product <SDK>/.metadata/product.json --device MSPM0G350X --package "LQFP-64(PM)"` 重新生成，与入库文件 diff；`--write` 覆盖。CI：`.github/workflows/mspm0-syscfg.yml`（缓存安装包，生成 → 比对 → 交叉编译）。
- 版本锁：SysConfig **1.28.0.4712** + MSPM0 SDK **2.11.00.07**。升级任一个都要 `--write` 后审 diff 再提交。
- 【已实测】首次用真 CLI 跑出了两个合成样例的错误，已改：
  1. 每个 GPIO 组的引脚 `$name` 不能都叫 `PIN`（SysConfig 报 Duplicate name）。约定改为 **引脚名 = 逻辑名**，宏为 `GPIO_<名>_<名>_PIN`，gen_board 已跟随。
  2. `Basic_Periodic` 定时器不导出 `*_INST_CLK_FREQ`（只有 `LOAD_VALUE`）。在 board.yaml 的 timer 条目写 `clk_hz`（分频后计数时钟），gen_board 在头里补定义。
- 本地：从 https://www.ti.com/tool/SYSCONFIG 装 Linux/Windows 版；Windows 下脚本需 Git Bash，`SYSCFG_CLI=/c/ti/sysconfig_1.28.0/sysconfig_cli.bat` 【未验证】。
