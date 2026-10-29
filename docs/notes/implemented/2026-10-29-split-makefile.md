# 顶层 Makefile 按芯片系列拆成 mk/<BOARD_FAMILY>.mk

- **决定**：host / stm32f4 / stm32-cubemx / mspm0-driverlib 四段 `ifeq ($(BOARD_FAMILY),…)` 原样搬到 `mk/<系列>.mk`，顶层只 `include $(wildcard mk/$(BOARD_FAMILY).mk)`。
- **为什么**：Makefile 47 次修改 / 327 行，四套芯片规则揉在一起，改 MSPM0 容易碰坏 STM32（docs/27 G3）。拆开后加新系列 = 新建一个文件。
- **证据（行为不变）**：拆分前后清空 build/ 各编一次 11 个 板×应用（含 LINK=rtt），`.bin`（host 为 elf）与 `make vars` 输出 md5 **全部相同**（2026-10-29 本机）。
- **守护**：`make cross`（CI firmware）。
- **否决过**：把通用规则（编译/链接模式规则）也拆走——那部分各系列共用，拆了反而要在四个文件里同步。
