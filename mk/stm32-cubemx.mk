# mk/stm32-cubemx.mk —— BOARD_FAMILY=stm32-cubemx 的编译器、HAL/SDK、链接脚本（由顶层 Makefile include；2026-10-29 从 Makefile 原样拆出，行为不变）
# ------------------------------------------------------------------ stm32-cubemx（任意 STM32 系列，CubeMX 工程提供一切外设配置）
ifeq ($(BOARD_FAMILY),stm32-cubemx)
TC      ?= arm-none-eabi-
CC      := $(TC)gcc
SERIES  := $(subst stm32,,$(BOARD_SERIES))
SERIES_U := $(shell echo $(SERIES) | tr a-z A-Z)
# HAL 优先用 CubeMX 复制进工程的 Drivers/；没有则退回 third_party（tools/fetch_third_party.sh 备有 F1/F4）
CUBE_HAL ?= $(firstword $(wildcard $(CUBE_DIR)/Drivers/STM32$(SERIES_U)xx_HAL_Driver third_party/stm32$(SERIES)xx-hal-driver))
CUBE_DEV ?= $(firstword $(wildcard $(CUBE_DIR)/Drivers/CMSIS/Device/ST/STM32$(SERIES_U)xx third_party/cmsis-device-$(SERIES)))
CMSIS   ?= $(firstword $(wildcard $(CUBE_DIR)/Drivers/CMSIS/Include) third_party/CMSIS_5/CMSIS/Core/Include)
# vars / gen 不需要 HAL（keil_inject 只要模块清单；Keil 工程自带 HAL）：没 HAL 时只在真编译时报错
ifeq ($(CUBE_HAL)$(filter-out vars gen,$(or $(MAKECMDGOALS),all)),)
else ifeq ($(CUBE_HAL),)
$(error 找不到 STM32$(SERIES_U) HAL：在 CubeMX 里 Project Manager > Code Generator 选 "Copy all used libraries"，或设置 CUBE_HAL/CUBE_DEV)
endif
MCU     := $(BOARD_CPU)
CFLAGS  := -std=c11 -Os -g3 $(MCU) $(WARN) -ffunction-sections -fdata-sections $(BOARD_DEFS)
HAL_INC := $(CUBE_DIR)/Core/Inc $(CUBE_HAL)/Inc $(CUBE_DEV)/Include $(CMSIS)
CUBE_SYS := $(firstword $(wildcard $(CUBE_DIR)/Core/Src/system_stm32*.c) $(CUBE_DEV)/Source/Templates/system_stm32$(SERIES)xx.c)
# CubeMX 生成代码与 HAL 都按第三方代码编译（不套 -Werror，永远不手改）
HAL_SRC := $(filter-out %template.c,$(wildcard $(CUBE_HAL)/Src/*.c)) \
           $(filter-out $(wildcard $(CUBE_DIR)/Core/Src/system_stm32*.c),$(wildcard $(CUBE_DIR)/Core/Src/*.c)) $(CUBE_SYS)
DEV_LC  := $(shell echo $(BOARD_DEFS) | sed -E 's/.*-D(STM32[A-Z0-9]+x[A-Z0-9x]).*/\1/' | tr A-Z a-z)
STARTUP := $(firstword $(wildcard $(CUBE_DIR)/startup_*.s $(CUBE_DIR)/Core/Startup/startup_*.s) $(CUBE_DEV)/Source/Templates/gcc/startup_$(DEV_LC).s)
# FreeRTOS（config_source.rtos: freertos）：CubeMX 复制的 Middlewares/ 优先，否则 third_party/stm32-mw-freertos
ifeq ($(BOARD_RTOS),freertos)
RTOS_DIR ?= $(firstword $(wildcard $(CUBE_DIR)/Middlewares/Third_Party/FreeRTOS/Source third_party/stm32-mw-freertos/Source))
RTOS_PORT := $(if $(findstring cortex-m4,$(BOARD_CPU)),ARM_CM4F,$(if $(findstring cortex-m7,$(BOARD_CPU)),ARM_CM7/r0p1,$(if $(findstring cortex-m0,$(BOARD_CPU)),ARM_CM0,ARM_CM3)))
RTOS2_INC ?= $(firstword $(wildcard $(CUBE_DIR)/Drivers/CMSIS/RTOS2/Include third_party/CMSIS_5/CMSIS/RTOS2/Include))
HAL_INC += $(RTOS_DIR)/include $(RTOS_DIR)/CMSIS_RTOS_V2 $(RTOS_DIR)/portable/GCC/$(RTOS_PORT) $(RTOS2_INC)
HAL_SRC += $(wildcard $(RTOS_DIR)/*.c) $(RTOS_DIR)/CMSIS_RTOS_V2/cmsis_os2.c \
           $(RTOS_DIR)/portable/GCC/$(RTOS_PORT)/port.c $(RTOS_DIR)/portable/MemMang/heap_4.c
endif
LDSCRIPT = $(firstword $(wildcard $(CUBE_DIR)/*_FLASH.ld))
LDFLAGS  = $(MCU) -T$(LDSCRIPT) -Wl,--defsym=__flash_kb=$(BOARD_FLASH_KB) -Wl,--gc-sections \
           -Wl,-Map=$(OUT)/$(APP).map -Wl,--print-memory-usage -Wl,--no-warn-rwx-segments --specs=nano.specs --specs=nosys.specs -lm
PORT_SRC = $(PORT_DIR)/pal_cubemx.c $(if $(filter freertos,$(BOARD_RTOS)),$(PORT_DIR)/dz_freertos.c)
TARGET   = $(OUT)/$(APP).elf
endif
