# 16 · VS Code 工作流（最低优先级）

> 【未验证】`.vscode/` 下的配置没有在 VS Code 里实测，也没连板调试过；JSON 语法已校验。

## 推荐扩展（`.vscode/extensions.json`）
- **Cortex-Debug**（marus25.cortex-debug）：调试，配 OpenOCD 或 pyOCD。
- **EIDE**（cl.eide）：可选，想要 Keil 式图形工程时用。
- C/C++（ms-vscode.cpptools）。

## 构建
`Ctrl+Shift+B` → `dz: build`，选 BOARD、填 APP，等同 `make BOARD= APP=`。不另造一套构建，和 `make check` 结果一致。

## 调试（`.vscode/launch.json`）
| 配置 | 探针 | 说明 |
|---|---|---|
| F407 skystar · OpenOCD | ST-Link | `interface/stlink.cfg` + `target/stm32f4x.cfg` |
| F407 bldc · pyOCD | ST-Link/DAPLink | `targetId: stm32f407vgtx`，需 `pyocd pack install stm32f407vg` |
| F103C8 · OpenOCD | ST-Link | 国产 CKS32/GD32 克隆片可能要改 `set CPUTAPID 0` |
| MSPM0G3507 · pyOCD | XDS110/DAPLink | 需 `pyocd pack install mspm0g3507`；也可用 CCS 调试（docs/15） |

SVD 不入库（版权归厂商）：从 ST 的 STM32F4/F1 SVD 包、TI MSPM0 SDK 或 CMSIS pack 里取，放 `third_party/svd/STM32F407.svd`、`STM32F103.svd`、`MSPM0G350X.svd`。

## EIDE（可选）
- 已有 Keil 工程：EIDE → 导入 → MDK 工程（.uvprojx），先用 `tools/keil_inject.py` 把工作台模块注入（docs/14），EIDE 会跟着带进来。
- 纯 Makefile 板（skystar/mspm0）：不建议再建 EIDE 工程，直接用上面的 tasks + Cortex-Debug，避免两份源文件列表。

## IntelliSense 模板（`.vscode/c_cpp_properties.json`）
| 配置 | 什么时候用 |
|---|---|
| **dz (compile_commands)**（首选） | 跑任务 `dz: compdb`（= `make BOARD= APP= compdb`），生成 `build/compile_commands.json`，参数和真实编译完全一样；换板子后重跑一次 |
| MSPM0G3507 · GCC | 不想跑 make 时的静态路径：工作台 + `build/<板>/gen` + `boards/<板>/syscfg` + SDK `source` + SDK 自带 CMSIS |
| MSPM0G3507 · CCS (TI ArmClang) | 用 CCS 工程编译、VS Code 只看代码。**必须加 `<工程>/Debug/`**：CCS 把 SysConfig 生成的 `ti_msp_dl_config.h` 放这里，漏了 DL_ 宏会全红 |
| STM32F407 · GCC | CubeMX 板，`Core/Inc` + HAL + CMSIS |

常见红线：`ti_msp_dl_config.h` 找不到 → 少了 Debug/ 或 syscfg/；`__MSPM0G3507__` 没定义 → 器件头选不到寄存器；`board_gen.h` 找不到 → 先 `make` 一次生成 `build/<板>/gen`。

## TI ArmClang 和 GCC 怎么选
| | arm-none-eabi-gcc（本仓库 Makefile） | TI ArmClang（tiarmclang，CCS 自带） |
|---|---|---|
| 用法 | `make BOARD=mspm0g3507-tianmengxing APP=car_2wd`，CI 会编译 | CCS 工程（docs/15），TI 例程默认用它 |
| SDK 文件 | `source/ti/devices/msp/m0p/startup_system_files/gcc`、`linker_files/gcc` | 对应目录里的 `ticlang` 文件 |
| 库 | 工作台源码直接编译，不需要预编译库 | `driverlib.a` 有 ticlang 预编译版 |
| 建议 | 比赛现场统一用一种，**不要混用两种编译器产出的 .o/.a** | — |

## SDK 版本锁
MSPM0 SDK **2.11.00.07** + SysConfig **1.28.0.4712**（docs/10）。不同版本的 SDK 生成的 `ti_msp_dl_config` 可能不一样。CCS 里改 SDK 版本后，要用 `tools/syscfg_gen.sh` 重新生成并检查 diff。

## 探针：XDS110 vs DAPLink
| 探针 | 来源 | VS Code 调试 | 备注 |
|---|---|---|---|
| XDS110 | LP-MSPM0G3507 板载 | Cortex-Debug + OpenOCD（`interface/xds110.cfg`，需要较新的 OpenOCD，且要有 MSPM0 target 脚本）【未验证】；或者直接用 CCS 调试 | 固件跟着 CCS 更新；还带 UART 虚拟串口 |
| DAPLink / CMSIS-DAP | 天猛星等第三方板常配 | Cortex-Debug + pyOCD（`pyocd pack install mspm0g3507`，`launch.json` 已配置） | MSPM0 的 SWD 默认在 PA19/PA20 |

两种探针都可以在 Cortex-Debug 里通过 `svdFile` 加载 `third_party/svd/MSPM0G350X.svd`，在调试时看外设寄存器。
