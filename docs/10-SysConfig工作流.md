# 10 TI MSPM0 + SysConfig 工作流

> 标注约定：**【已实测】** = 本仓库在 PC 上用测试/编译实际跑过（2026-10-28，Asia/Shanghai）；**【未验证】** = 设计意图或推断，尚未在真实硬件上做实验。实验是检验真理的唯一标准——【未验证】的内容上板前不要当结论。

与 CubeMX 对称：`.syscfg` 是唯一配置源，生成 `ti_msp_dl_config.{h,c}`，移植层 `ports/mspm0-driverlib`（**预留，未实现**）只调用 DriverLib（`DL_*`，check_deps P2）。

1. SysConfig 中按 05 的标签约定命名（GPIO_/PWM_/UART_…）。
2. `python3 tools/syscfg_import.py <工程>.syscfg -o boards/<板>/board.yaml` 提取 GPIO/PWM/UART；ENC/ADC/TIMER 目前输出 TODO 待手填。
3. 板卡：`boards/mspm0g3507-tianmengxing`（立创·天猛星 MSPM0G3507）——引脚与 .syscfg 均 TODO，resources 为空，只通过 schema 校验。

- 【已实测】syscfg_import 自检（合成 .syscfg 样例 tools/fixtures/syscfg/synthetic.syscfg）。
- 【未验证】合成样例未经真实 SysConfig 打开；移植层未实现；天猛星未上板。

## 参考来源
- TI SysConfig（https://www.ti.com/tool/SYSCONFIG）、MSPM0-SDK（https://www.ti.com/tool/MSPM0-SDK）。
