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
