# mk/mspm0-driverlib.mk —— BOARD_FAMILY=mspm0-driverlib 的编译器、HAL/SDK、链接脚本（由顶层 Makefile include；2026-10-29 从 Makefile 原样拆出，行为不变）
# ------------------------------------------------------------------ mspm0-driverlib（SysConfig 生成 ti_msp_dl_config，DriverLib）
ifeq ($(BOARD_FAMILY),mspm0-driverlib)
TC      ?= arm-none-eabi-
CC      := $(TC)gcc
M0_SDK  ?= third_party/mspm0-sdk/source
# make gen / vars 不要 SDK：CCS 用户的 SDK 装在 CCS 里，导入 projectspec 前只需要生成 board_gen / link_gen
ifeq ($(wildcard $(M0_SDK)/ti/driverlib/driverlib.h),)
ifneq ($(filter-out vars gen,$(or $(MAKECMDGOALS),all)),)
$(error 找不到 MSPM0 SDK（$(M0_SDK)）：运行 tools/fetch_third_party.sh 或设置 M0_SDK)
endif
endif
M0_DEV  := $(M0_SDK)/ti/devices/msp/m0p
MCU     := $(BOARD_CPU)
CFLAGS  := -std=c11 -Os -g3 $(MCU) $(WARN) -ffunction-sections -fdata-sections $(BOARD_DEFS) $(BOARD_NVM_DEFS)
HAL_INC := $(SYSCFG_DIR) $(M0_SDK) $(firstword $(wildcard $(M0_SDK)/third_party/CMSIS/Core/Include) third_party/CMSIS_5/CMSIS/Core/Include)
# DriverLib 只编用到的源文件（其余外设在部分型号上不存在）；系统控制按器件族选
HAL_SRC := $(addprefix $(M0_SDK)/ti/driverlib/,dl_common.c dl_timer.c dl_uart.c dl_i2c.c dl_spi.c dl_adc12.c dl_flashctl.c m0p/dl_interrupt.c \
           m0p/sysctl/dl_sysctl_mspm0g1x0x_g3x0x.c) $(SYSCFG_DIR)/ti_msp_dl_config.c \
           $(M0_DEV)/startup_system_files/gcc/startup_$(patsubst %07,%0x,$(BOARD_PART_LC))_gcc.c
LDSCRIPT = $(M0_DEV)/linker_files/gcc/$(BOARD_PART_LC).lds
LDFLAGS  = $(MCU) -T$(LDSCRIPT) $(PORT_DIR)/nvm_guard.ld -Wl,--defsym=__nvm_kb=$(or $(BOARD_NVM_KB),0) -Wl,--defsym=__flash_kb=$(or $(BOARD_FLASH_KB),128) -Wl,--gc-sections -Wl,-Map=$(OUT)/$(APP).map -Wl,--print-memory-usage \
           -Wl,--no-warn-rwx-segments --specs=nano.specs --specs=nosys.specs -lm
PORT_SRC = $(PORT_DIR)/pal_mspm0.c $(PORT_DIR)/main_mspm0.c
TARGET   = $(OUT)/$(APP).elf
endif
