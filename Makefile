# 电赛工作台 —— 顶层构建
#
#   make                      # = make BOARD=host-sim APP=motor_speed_demo，在电脑上编译
#   make run                  # 编译并运行仿真（仅 host-sim）
#   make BOARD=stm32f407-skystar APP=motor_speed_demo   # 交叉编译到天空星（默认 VET6）
#   make BOARD=stm32f407-skystar VARIANT=VGT6           # 同一块板的 1MB 高配版
#   make test                 # 主机单元测试 + 仿真闭环测试
#   make check                # 板卡校验 + 依赖规则 + 接口哈希
#   make selftest BOARD=...   # 编译移植层自检固件（boards/<板>/selftest）
#
# 换板子只改 BOARD=，应用代码与本文件都不用改。

BOARD ?= host-sim
APP   ?= motor_speed_demo
VARIANT ?=
PY    ?= python3

# V=1 显示完整编译命令
Q := $(if $(filter 1,$(V)),,@)
.DEFAULT_GOAL := all
ROOT      := $(CURDIR)
BOARD_YML := boards/$(BOARD)/board.yaml
APP_DIR   ?= $(firstword $(wildcard apps/$(APP) examples/$(APP)))
BDIR      := build/$(BOARD)$(if $(VARIANT),-$(VARIANT))
OUT       := $(BDIR)/$(APP)
GEN       := $(BDIR)/gen

ifeq ($(APP_DIR),)
$(error 找不到应用 $(APP)（apps/ 或 examples/ 下）)
endif
ifeq ($(wildcard $(BOARD_YML)),)
$(error 找不到 $(BOARD_YML)。可用板卡：$(notdir $(wildcard boards/*)))
endif

# 由 board.yaml 生成 board_gen.{h,c,mk}；board.yaml 或 app.yaml 变了自动重新生成
$(GEN)/board_gen.mk: $(BOARD_YML) $(wildcard $(APP_DIR)/app.yaml) tools/gen_board.py tools/boardlib.py $(wildcard tools/families/*.py)
	$(PY) tools/gen_board.py $(BOARD_YML) -o $(GEN) $(if $(VARIANT),--variant $(VARIANT)) $(if $(wildcard $(APP_DIR)/app.yaml),--app $(APP_DIR)/app.yaml)
$(GEN)/board_gen.h $(GEN)/board_gen.c: $(GEN)/board_gen.mk
-include $(GEN)/board_gen.mk

# 题目工程（有 project.yaml）：生成共享状态/子系统表
PROJECT_YML := $(wildcard $(APP_DIR)/project.yaml)
PROJ_GEN    := $(OUT)/projgen
ifneq ($(PROJECT_YML),)
$(PROJ_GEN)/project_gen.mk: $(PROJECT_YML) tools/gen_project.py tools/gen_coproc.py $(wildcard boards/*/board.yaml)
	$(PY) tools/gen_project.py $(PROJECT_YML) -o $(PROJ_GEN) --role $(or $(ROLE),main)
$(PROJ_GEN)/project_gen.h $(PROJ_GEN)/project_gen.c: $(PROJ_GEN)/project_gen.mk
-include $(PROJ_GEN)/project_gen.mk
PROJ_INC := $(PROJ_GEN) $(wildcard $(APP_DIR)/lib) $(APP_DIR)/io
endif

FW_INC := firmware/common firmware/pal $(wildcard firmware/algo/*) $(wildcard firmware/framework/*) $(wildcard firmware/proto/*) $(wildcard firmware/drivers/*) apps/include
LIB_SRC := $(wildcard firmware/algo/*/*.c firmware/framework/*/*.c firmware/proto/*/*.c firmware/drivers/*/*.c)
APP_ALL := $(shell find $(APP_DIR) -name '*.c' -not -path '*/tests/*')
SIM_SETUP := $(filter %/sim_setup.c,$(APP_ALL))
APP_SRC  = $(filter-out $(SIM_SETUP),$(APP_ALL)) $(PROJ_SRC)
PORT_DIR = ports/$(BOARD_PORT)
WARN := -Wall -Wextra -Werror -Wshadow -Wdouble-promotion -Wno-unused-parameter

# ------------------------------------------------------------------ host
ifeq ($(BOARD_FAMILY),host)
CC      := gcc
CFLAGS  := -std=c11 -O2 -g $(WARN) -Wno-double-promotion -fsanitize=address,undefined -fno-omit-frame-pointer
LDFLAGS := -fsanitize=address,undefined -lm
PORT_SRC = $(PORT_DIR)/pal_host.c $(PORT_DIR)/main_host.c $(SIM_SETUP)
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

# ------------------------------------------------------------------ stm32-cubemx（任意 STM32 系列，CubeMX 工程提供一切外设配置）
ifeq ($(BOARD_FAMILY),stm32-cubemx)
TC      ?= arm-none-eabi-
CC      := $(TC)gcc
SERIES  := $(subst stm32,,$(BOARD_SERIES))
SERIES_U := $(shell echo $(SERIES) | tr a-z A-Z)
# HAL 优先用 CubeMX 复制进工程的 Drivers/；没有则退回 third_party（目前只备有 F4）
CUBE_HAL ?= $(firstword $(wildcard $(CUBE_DIR)/Drivers/STM32$(SERIES_U)xx_HAL_Driver) $(if $(filter f4,$(SERIES)),third_party/stm32f4xx-hal-driver))
CUBE_DEV ?= $(firstword $(wildcard $(CUBE_DIR)/Drivers/CMSIS/Device/ST/STM32$(SERIES_U)xx) $(if $(filter f4,$(SERIES)),third_party/cmsis-device-f4))
CMSIS   ?= $(firstword $(wildcard $(CUBE_DIR)/Drivers/CMSIS/Include) third_party/CMSIS_5/CMSIS/Core/Include)
ifeq ($(CUBE_HAL),)
$(error 找不到 STM32$(SERIES_U) HAL：在 CubeMX 里 Project Manager > Code Generator 选 "Copy all used libraries"，或设置 CUBE_HAL/CUBE_DEV)
endif
MCU     := $(BOARD_CPU)
CFLAGS  := -std=c11 -Os -g3 $(MCU) $(WARN) -ffunction-sections -fdata-sections $(BOARD_DEFS)
HAL_INC := $(CUBE_DIR)/Core/Inc $(CUBE_HAL)/Inc $(CUBE_DEV)/Include $(CMSIS)
CUBE_SYS := $(firstword $(wildcard $(CUBE_DIR)/Core/Src/system_stm32*.c) $(CUBE_DEV)/Source/Templates/system_stm32$(SERIES)xx.c)
# CubeMX 生成代码与 HAL 都按第三方代码编译（不套 -Werror，永远不手改）
HAL_SRC := $(filter-out %template.c,$(wildcard $(CUBE_HAL)/Src/*.c)) \
           $(filter-out $(wildcard $(CUBE_DIR)/Core/Src/system_stm32*.c),$(wildcard $(CUBE_DIR)/Core/Src/*.c)) $(CUBE_SYS)
DEV_LC  := $(shell echo $(BOARD_DEFS) | sed -E 's/.*-D(STM32[A-Z0-9]+xx).*/\1/' | tr A-Z a-z)
STARTUP := $(firstword $(wildcard $(CUBE_DIR)/startup_*.s $(CUBE_DIR)/Core/Startup/startup_*.s) $(CUBE_DEV)/Source/Templates/gcc/startup_$(DEV_LC).s)
LDSCRIPT = $(firstword $(wildcard $(CUBE_DIR)/*_FLASH.ld))
LDFLAGS  = $(MCU) -T$(LDSCRIPT) -Wl,--defsym=__flash_kb=$(BOARD_FLASH_KB) -Wl,--gc-sections \
           -Wl,-Map=$(OUT)/$(APP).map -Wl,--print-memory-usage -Wl,--no-warn-rwx-segments --specs=nano.specs --specs=nosys.specs -lm
PORT_SRC = $(PORT_DIR)/pal_cubemx.c
TARGET   = $(OUT)/$(APP).elf
endif

INC  = $(addprefix -I,$(FW_INC) $(PROJ_INC) $(PORT_DIR) $(GEN) $(HAL_INC))
SRCS = $(LIB_SRC) $(APP_SRC) $(PORT_SRC) $(GEN)/board_gen.c
OBJS = $(patsubst %,$(OUT)/obj/%.o,$(SRCS))
# 第三方代码不套 -Werror（不是我们能改的），单独编译
HAL_OBJS = $(patsubst %,$(OUT)/hal/%.o,$(HAL_SRC) $(STARTUP))

.PHONY: all run test check selftest clean fetch ioc-check
all: $(TARGET)

$(OUT)/obj/%.c.o: %.c $(GEN)/board_gen.h $(if $(PROJECT_YML),$(PROJ_GEN)/project_gen.h)
	@mkdir -p $(dir $@)
	@echo "  CC  $<"
	$(Q)$(CC) $(CFLAGS) $(INC) -MMD -c $< -o $@
$(OUT)/hal/%.c.o: %.c $(GEN)/board_gen.h
	@mkdir -p $(dir $@)
	@echo "  CC  $< (第三方，关闭警告)"
	$(Q)$(CC) $(filter-out -Werror -Wshadow -Wdouble-promotion -Wextra,$(CFLAGS)) $(INC) -w -c $< -o $@
$(OUT)/hal/%.s.o: %.s
	@mkdir -p $(dir $@)
	@echo "  AS  $<"
	$(Q)$(CC) $(MCU) -c $< -o $@

$(TARGET): $(OBJS) $(HAL_OBJS)
	@echo "  LD  $@"
	$(Q)$(CC) $^ $(LDFLAGS) -o $@
ifneq ($(filter stm32f4 stm32-cubemx,$(BOARD_FAMILY)),)
	$(TC)objcopy -O binary $@ $(OUT)/$(APP).bin
	$(TC)objcopy -O ihex $@ $(OUT)/$(APP).hex
	$(TC)size $@
endif
	@echo "✓ $(BOARD)/$(APP) -> $@"

run: $(TARGET)
ifneq ($(BOARD_FAMILY),host)
	$(error make run 只支持 BOARD=host-sim；真板请用 make flash（见 docs/06-新增板卡.md）)
endif
	./$(TARGET) $(ARGS)

# 所有 port: stm32-cubemx 的板卡：.ioc 与 board.yaml 一致、CubeMX 配置满足移植层前提、main.c 钩子齐全
ioc-check:
	@for b in $$(grep -l "^port: stm32-cubemx" boards/*/board.yaml); do d=$$(dirname $$b); \
	  ioc=$$d/$$(sed -nE 's/^  file: (.*)/\1/p' $$b | head -1); \
	  $(PY) tools/ioc_import.py $$ioc --check $$b --project $$(dirname $$ioc) || exit 1; done

selftest:
	$(MAKE) APP=port_selftest BOARD=$(BOARD)

test:
	$(MAKE) -C tests/host

check:
	$(PY) tools/validate_board.py boards/*/board.yaml
	for p in examples/*/project.yaml; do $(PY) tools/gen_project.py $$p --check || exit 1; done
	$(PY) tools/check_deps.py
	$(PY) tools/check_deps.py --selftest
	$(PY) tools/iface_hash.py --check
	$(PY) tools/iface_hash.py --selftest
	$(PY) tools/ioc_import.py --selftest
	$(PY) tools/test_ioc_import.py
	$(PY) tools/syscfg_import.py --selftest
	$(PY) tools/audit_port.py --selftest
	$(MAKE) ioc-check
	$(MAKE) -C examples/2026H_ball/tests
	cd host/python && $(PY) -m dzlink.test_dzlink

fetch:
	tools/fetch_stm32f4.sh

clean:
	rm -rf build

-include $(OBJS:.o=.d)
