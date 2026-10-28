# 电赛工作台 —— 顶层构建
#
#   make                      # = make BOARD=host-sim APP=motor_speed_demo，在电脑上编译
#   make run                  # 编译并运行仿真（仅 host-sim）
#   make BOARD=stm32f407-skystar APP=motor_speed_demo   # 交叉编译到天空星
#   make test                 # 主机单元测试 + 仿真闭环测试
#   make check                # 板卡校验 + 依赖规则 + 接口哈希
#   make selftest BOARD=...   # 编译移植层自检固件（boards/<板>/selftest）
#
# 换板子只改 BOARD=，应用代码与本文件都不用改。

BOARD ?= host-sim
APP   ?= motor_speed_demo
PY    ?= python3

.DEFAULT_GOAL := all
ROOT      := $(CURDIR)
BOARD_YML := boards/$(BOARD)/board.yaml
APP_DIR   := apps/$(APP)
OUT       := build/$(BOARD)/$(APP)
GEN       := build/$(BOARD)/gen

ifeq ($(wildcard $(BOARD_YML)),)
$(error 找不到 $(BOARD_YML)。可用板卡：$(notdir $(wildcard boards/*)))
endif

# 由 board.yaml 生成 board_gen.{h,c,mk}；board.yaml 或 app.yaml 变了自动重新生成
$(GEN)/board_gen.mk: $(BOARD_YML) $(wildcard $(APP_DIR)/app.yaml) tools/gen_board.py tools/boardlib.py $(wildcard tools/families/*.py)
	$(PY) tools/gen_board.py $(BOARD_YML) -o $(GEN) $(if $(wildcard $(APP_DIR)/app.yaml),--app $(APP_DIR)/app.yaml)
$(GEN)/board_gen.h $(GEN)/board_gen.c: $(GEN)/board_gen.mk
-include $(GEN)/board_gen.mk

FW_INC := firmware/common firmware/pal $(wildcard firmware/algo/*) $(wildcard firmware/drivers/*) apps/include
LIB_SRC := $(wildcard firmware/algo/*/*.c firmware/drivers/*/*.c)
APP_SRC  = $(filter-out $(APP_DIR)/sim_setup.c,$(wildcard $(APP_DIR)/*.c))
PORT_DIR = ports/$(BOARD_PORT)
WARN := -Wall -Wextra -Werror -Wshadow -Wdouble-promotion -Wno-unused-parameter

# ------------------------------------------------------------------ host
ifeq ($(BOARD_FAMILY),host)
CC      := gcc
CFLAGS  := -std=c11 -O2 -g $(WARN) -Wno-double-promotion -fsanitize=address,undefined -fno-omit-frame-pointer
LDFLAGS := -fsanitize=address,undefined -lm
PORT_SRC = $(PORT_DIR)/pal_host.c $(PORT_DIR)/main_host.c $(wildcard $(APP_DIR)/sim_setup.c)
TARGET   = $(OUT)/$(APP).elf
endif

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
            hal_uart hal_adc hal_adc_ex hal_pwr hal_pwr_ex hal_flash hal_flash_ex hal_exti
HAL_SRC := $(patsubst %,$(F4_HAL)/Src/stm32f4xx_%.c,$(HAL_MODS)) $(F4_DEV)/Source/Templates/system_stm32f4xx.c
STARTUP := $(F4_DEV)/Source/Templates/gcc/startup_stm32f407xx.s
LDSCRIPT = $(PORT_DIR)/stm32f407_flash.ld
LDFLAGS  = $(MCU) -T$(LDSCRIPT) -Wl,--defsym=__flash_kb=$(BOARD_FLASH_KB) -Wl,--gc-sections \
           -Wl,-Map=$(OUT)/$(APP).map -Wl,--print-memory-usage -Wl,--no-warn-rwx-segments --specs=nano.specs --specs=nosys.specs -lm
PORT_SRC = $(PORT_DIR)/pal_stm32f4.c $(PORT_DIR)/main_stm32f4.c $(PORT_DIR)/syscalls.c
TARGET   = $(OUT)/$(APP).elf
endif

INC  = $(addprefix -I,$(FW_INC) $(PORT_DIR) $(GEN) $(HAL_INC))
SRCS = $(LIB_SRC) $(APP_SRC) $(PORT_SRC) $(GEN)/board_gen.c
OBJS = $(patsubst %,$(OUT)/obj/%.o,$(SRCS))
# 第三方代码不套 -Werror（不是我们能改的），单独编译
HAL_OBJS = $(patsubst %,$(OUT)/hal/%.o,$(HAL_SRC) $(STARTUP))

.PHONY: all run test check selftest clean fetch
all: $(TARGET)

$(OUT)/obj/%.c.o: %.c $(GEN)/board_gen.h
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) $(INC) -MMD -c $< -o $@
$(OUT)/hal/%.c.o: %.c $(GEN)/board_gen.h
	@mkdir -p $(dir $@)
	$(CC) $(filter-out -Werror -Wshadow -Wdouble-promotion -Wextra,$(CFLAGS)) $(INC) -w -c $< -o $@
$(OUT)/hal/%.s.o: %.s
	@mkdir -p $(dir $@)
	$(CC) $(MCU) -c $< -o $@

$(TARGET): $(OBJS) $(HAL_OBJS)
	$(CC) $^ $(LDFLAGS) -o $@
ifeq ($(BOARD_FAMILY),stm32f4)
	$(TC)objcopy -O binary $@ $(OUT)/$(APP).bin
	$(TC)objcopy -O ihex $@ $(OUT)/$(APP).hex
	$(TC)size $@
endif
	@echo "✓ $(BOARD)/$(APP) -> $@"

run: $(TARGET)
ifneq ($(BOARD_FAMILY),host)
	$(error make run 只支持 BOARD=host-sim；真板请用 make flash（见 docs/06-add-board.md）)
endif
	./$(TARGET) $(ARGS)

selftest:
	$(MAKE) APP=port_selftest_$(BOARD_FAMILY) BOARD=$(BOARD)

test:
	$(MAKE) -C tests/host

check:
	$(PY) tools/validate_board.py boards/*/board.yaml
	$(PY) tools/check_deps.py
	$(PY) tools/iface_hash.py --check

fetch:
	tools/fetch_stm32f4.sh

clean:
	rm -rf build

-include $(OBJS:.o=.d)
