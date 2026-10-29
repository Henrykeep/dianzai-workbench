# mk/stm32f4.mk —— BOARD_FAMILY=stm32f4 的编译器、HAL/SDK、链接脚本（由顶层 Makefile include；2026-10-29 从 Makefile 原样拆出，行为不变）
# ------------------------------------------------------------------ stm32f4
ifeq ($(BOARD_FAMILY),stm32f4)
TC      ?= arm-none-eabi-
CC      := $(TC)gcc
F4_HAL  ?= third_party/stm32f4xx-hal-driver
F4_DEV  ?= third_party/cmsis-device-f4
CMSIS   ?= third_party/CMSIS_5/CMSIS/Core/Include
ifeq ($(wildcard $(F4_HAL)/Inc/stm32f4xx_hal.h),)
$(error 缺少 STM32CubeF4 HAL。先运行 tools/fetch_stm32f4.sh（或设置 F4_HAL/F4_DEV/CMSIS 路径）)
endif
MCU     := -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard
CFLAGS  := -std=c11 -Os -g3 $(MCU) $(WARN) -ffunction-sections -fdata-sections $(BOARD_DEFS)
HAL_INC := $(F4_HAL)/Inc $(F4_DEV)/Include $(CMSIS)
HAL_MODS := hal hal_cortex hal_rcc hal_rcc_ex hal_gpio hal_dma hal_dma_ex hal_tim hal_tim_ex \
            hal_uart hal_adc hal_adc_ex hal_pwr hal_pwr_ex hal_flash hal_flash_ex hal_exti hal_i2c hal_spi
HAL_SRC := $(patsubst %,$(F4_HAL)/Src/stm32f4xx_%.c,$(HAL_MODS)) $(F4_DEV)/Source/Templates/system_stm32f4xx.c
STARTUP := $(F4_DEV)/Source/Templates/gcc/startup_stm32f407xx.s
LDSCRIPT = $(PORT_DIR)/stm32f407_flash.ld
LDFLAGS  = $(MCU) -T$(LDSCRIPT) -Wl,--defsym=__flash_kb=$(BOARD_FLASH_KB) -Wl,--gc-sections \
           -Wl,-Map=$(OUT)/$(APP).map -Wl,--print-memory-usage -Wl,--no-warn-rwx-segments --specs=nano.specs --specs=nosys.specs -lm
PORT_SRC = $(PORT_DIR)/pal_stm32f4.c $(PORT_DIR)/main_stm32f4.c $(PORT_DIR)/syscalls.c
TARGET   = $(OUT)/$(APP).elf
endif
