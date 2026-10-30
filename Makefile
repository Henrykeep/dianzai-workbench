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
# Windows 控制台默认 cp1252/GBK：工具输出 ✓/中文会 UnicodeEncodeError
export PYTHONUTF8 := 1

# V=1 显示完整编译命令
Q := $(if $(filter 1,$(V)),,@)
.DEFAULT_GOAL := all
ROOT      := $(CURDIR)
BOARD_YML := boards/$(BOARD)/board.yaml
APP_DIR   ?= $(firstword $(wildcard apps/$(APP) examples/$(APP)))
# LINK=rtt：LINK 走调试探针 RTT（firmware/proto/dzrtt），不占串口；默认 uart。换输出目录免得混用目标文件
LINK      ?= uart
BDIR      := build/$(BOARD)$(if $(VARIANT),-$(VARIANT))$(if $(filter rtt,$(LINK)),-rtt)
OUT       := $(BDIR)/$(APP)
GEN       := $(BDIR)/gen

ifneq ($(PROJECT),)
$(error 没有 PROJECT= 这个变量：题目工程也用 APP=<目录名>，例如 make BOARD=$(BOARD) APP=$(notdir $(patsubst %/,%,$(PROJECT)))（apps/ 与 examples/ 下都会找）)
endif
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
# gen/ 按板共享，换 APP 时 board_gen.mk 不一定重新生成 → requires 检查会被跳过、变成编译期 "RES_xxx undeclared"。
# 每个 板×应用 单独打一个检查戳，缺资源时给出 [缺资源] 而不是编译错误。
REQ_OK := $(OUT)/.requires_ok
$(REQ_OK): $(BOARD_YML) $(wildcard $(APP_DIR)/app.yaml) tools/boardlib.py
	@mkdir -p $(dir $@)
	$(Q)$(if $(wildcard $(APP_DIR)/app.yaml),$(PY) tools/validate_board.py $(BOARD_YML) --app $(APP_DIR)/app.yaml -q >$@.log || { cat $@.log; echo "✗ 板卡 $(BOARD) 不满足应用 $(APP) 的 requires（见上面的 [缺资源]）"; exit 1; })
	@touch $@
# 构建目标必须 include（生成失败要报错，-include 会把失败吞掉，曾导致 CI 里“成功”但没有 elf）
NO_GEN_GOALS := clean check test compat selftest fetch ioc-check
ifeq ($(if $(MAKECMDGOALS),$(filter-out $(NO_GEN_GOALS),$(MAKECMDGOALS)),all),)
-include $(GEN)/board_gen.mk
else
include $(GEN)/board_gen.mk
endif

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

# 上位机链路（yaml 有 link: 段）：遥测打包 + 参数表 + link_schema.json（tools/gen_link.py）
LINK_YML := $(firstword $(shell grep -l '^link:' $(PROJECT_YML) $(APP_DIR)/app.yaml 2>/dev/null))
LINK_GEN := $(OUT)/linkgen
ifneq ($(LINK_YML),)
$(LINK_GEN)/link_gen.c $(LINK_GEN)/link_gen.h $(LINK_GEN)/link_schema.json &: $(LINK_YML) tools/gen_link.py
	$(PY) tools/gen_link.py $(LINK_YML) -o $(LINK_GEN)
LINK_SRC := $(LINK_GEN)/link_gen.c
PROJ_INC += $(LINK_GEN)
endif

FW_INC := firmware/common firmware/pal $(wildcard firmware/algo/*) $(wildcard firmware/framework/*) $(wildcard firmware/proto/*) $(wildcard firmware/drivers/*) apps/include
LIB_SRC := $(wildcard firmware/algo/*/*.c firmware/framework/*/*.c firmware/proto/*/*.c firmware/drivers/*/*.c)
# 纯 make 递归通配（不调 find：Windows 上 find.exe 是另一个程序，会报 "File not found - *.c"）
rwildcard = $(foreach d,$(wildcard $(1:=/*)),$(call rwildcard,$d,$2) $(filter $(subst *,%,$2),$d))
APP_ALL := $(sort $(foreach f,$(call rwildcard,$(APP_DIR),*.c),$(if $(findstring /tests/,$f),,$f)))
SIM_SETUP := $(filter %/sim_setup.c,$(APP_ALL))
APP_SRC  = $(filter-out $(SIM_SETUP),$(APP_ALL)) $(PROJ_SRC) $(LINK_SRC)
PORT_DIR = ports/$(BOARD_PORT)
WARN := -Wall -Wextra -Werror -Wshadow -Wdouble-promotion -Wno-unused-parameter

# ------------------------------------------------------------------ 各芯片系列（mk/<BOARD_FAMILY>.mk）
# 每个系列一个文件：加新系列只新建 mk/<系列>.mk，不改本文件（docs/notes/implemented/2026-10-29-split-makefile.md）
include $(wildcard mk/$(BOARD_FAMILY).mk)

CFLAGS += $(if $(filter rtt,$(LINK)),-DDZ_LINK_RTT=1)
# 固件版本进心跳（dzctl_fw_rev）：git 短哈希 + bit31=工作区有改动。只加给 dzctl.c，换提交不会让全工程重编
FW_REV := $(shell h=$$(git rev-parse --short=7 HEAD 2>/dev/null) && { git diff --quiet HEAD 2>/dev/null && echo 0x$$h || printf '0x%x' $$((0x$$h | 0x80000000)); } || echo 0)
$(OUT)/obj/firmware/proto/dzctl/dzctl.c.o: CFLAGS += -DDZ_FW_REV=$(FW_REV)u
$(OUT)/obj/firmware/proto/dzctl/dzctl.c.o: $(OUT)/fw_rev
$(OUT)/fw_rev: FORCE
	@mkdir -p $(@D); echo $(FW_REV) | cmp -s - $@ || echo $(FW_REV) > $@
.PHONY: FORCE
FORCE:
INC  = $(addprefix -I,$(FW_INC) $(PROJ_INC) $(PORT_DIR) $(GEN) $(HAL_INC))
SRCS = $(LIB_SRC) $(APP_SRC) $(PORT_SRC) $(GEN)/board_gen.c
OBJS = $(patsubst %,$(OUT)/obj/%.o,$(SRCS))
# 第三方代码不套 -Werror（不是我们能改的），单独编译
HAL_OBJS = $(patsubst %,$(OUT)/hal/%.o,$(HAL_SRC) $(STARTUP))

.PHONY: all run test check selftest clean fetch ioc-check compat gen vars compdb cross agent-eval ui-preview preflight
# 可移植性：固件模块按严格 C99（无 GNU 扩展）编译，近似 Keil AC5/AC6、tiarmclang 的要求（真实编译器未在本机测试）
COMPAT_SRC := $(wildcard firmware/*/*/*.c)
compat:
	@for f in $(COMPAT_SRC); do gcc -std=c99 -pedantic-errors -Wall -Wextra -Werror -Wno-unused-parameter \
	  $(addprefix -I,$(FW_INC)) -fsyntax-only $$f || exit 1; done; echo "✓ compat: $(words $(COMPAT_SRC)) 个模块源文件按 C99 -pedantic-errors 通过"
all: $(TARGET)

# 交叉编译矩阵：每个 板×应用 组合都编一遍（需要 arm-none-eabi-gcc 和 third_party/）。CI firmware-cross 跑它。
CROSS := stm32f407-skystar:car_2wd stm32f407-skystar-cubemx:motor_speed_demo stm32f103c8t6-car-cubemx:car_2wd \
         stm32f407-bldc-freertos-cubemx:2026H_ball mspm0g3507-tianmengxing:car_2wd mspm0g3507-launchpad:car_2wd \
         host-sim:car_2wd host-sim:2026H_ball dji-rm-c:imu_module host-sim:imu_module \
         mspm0g3507-tianmengxing:imu_module host-sim:motor_pos host-sim:pendulum_rot host-sim:pan_tilt host-sim:line_car host-sim:2026X_follow \
         stm32f407-skystar:motor_pos mspm0g3507-tianmengxing:pendulum_rot stm32f407-skystar:pan_tilt \
         stm32f103c8t6-car-cubemx:port_selftest stm32f103c8t6-car-cubemx:motor_speed_demo stm32f407-skystar-cubemx:port_selftest \
         mspm0g3507-tianmengxing:port_selftest mspm0g3507-launchpad:port_selftest mspm0g3507-launchpad:motor_speed_demo \
         stm32f407-skystar:port_selftest stm32f407-skystar:motor_speed_demo dji-rm-c:port_selftest
cross:
	@for c in $(CROSS); do b=$${c%%:*}; a=$${c##*:}; $(MAKE) -s BOARD=$$b APP=$$a >/dev/null 2>&1 || { $(MAKE) -s BOARD=$$b APP=$$a; echo "✗ cross $$b/$$a"; exit 1; }; echo "✓ $$b/$$a"; done
	@$(MAKE) -s BOARD=mspm0g3507-launchpad APP=car_2wd LINK=rtt >/dev/null 2>&1 || { echo "✗ cross LINK=rtt mspm0g3507-launchpad/car_2wd"; exit 1; }; echo "✓ mspm0g3507-launchpad/car_2wd LINK=rtt"

# VS Code / clangd：写 build/compile_commands.json（当前 BOARD+APP 的真实编译参数；切换板子后重跑）
compdb: $(GEN)/board_gen.h $(if $(PROJECT_YML),$(PROJ_GEN)/project_gen.h) $(if $(LINK_YML),$(LINK_GEN)/link_gen.h)
	@$(PY) -c 'import json,os,sys; d=os.getcwd(); a=sys.argv[1:]; i=a.index("--"); fl,src=a[:i],a[i+1:]; json.dump([{"directory":d,"file":f,"arguments":["$(CC)"]+fl+["-c",f]} for f in src],open("build/compile_commands.json","w"),indent=1); print("✓ build/compile_commands.json:",len(src),"个文件")' \
	  $(CFLAGS) $(INC) -- $(SRCS)

$(OUT)/obj/%.c.o: %.c $(REQ_OK) $(GEN)/board_gen.h $(if $(PROJECT_YML),$(PROJ_GEN)/project_gen.h) $(if $(LINK_YML),$(LINK_GEN)/link_gen.h)
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

$(TARGET): $(OBJS) $(HAL_OBJS) $(LDSCRIPT)
	@echo "  LD  $@"
	$(Q)$(CC) $(filter-out $(LDSCRIPT),$^) $(LDFLAGS) -o $@
ifneq ($(filter stm32f4 stm32-cubemx mspm0-driverlib,$(BOARD_FAMILY)),)
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

# 打印本次构建的源文件/头文件路径/宏（给 tools/gen_ccs_projectspec.py 等 IDE 生成器用）
vars: $(GEN)/board_gen.mk
	@echo "SRCS=$(SRCS)"
	@echo "INC=$(FW_INC) $(PROJ_INC) $(PORT_DIR) $(GEN)"
	@echo "DEFS=$(BOARD_DEFS)"
	@echo "GEN=$(GEN)"
	@echo "FW_REV=$(FW_REV)"

# 只生成 board_gen.{h,c,mk}（给 Keil / CCS 工程用）
gen: $(GEN)/board_gen.mk $(if $(LINK_YML),$(LINK_GEN)/link_gen.c)
	@echo "✓ $(GEN)/board_gen.{h,c}"

# 浏览器预览桌面工作台：构建 app/ui、起侧车，打印带 ?ws= 的完整地址（mk/ui-preview.sh）
ui-preview:
	PY=$(PY) sh mk/ui-preview.sh

agent-eval:
	cd app/sidecar && $(PY) -m dzbench.agent.evalrun --repeat 3 $(ARGS)

selftest:
	$(MAKE) APP=port_selftest BOARD=$(BOARD)

test:
	$(MAKE) -C tests/host
	@# 桌面工作台侧车：缺 pytest/pyserial/websockets 时跳过（不阻塞固件测试），见 app/README.md
	@if $(PY) -c "import pytest, websockets" 2>/dev/null; then \
	  $(PY) -m pytest -q -rs -W error::pytest.PytestUnhandledThreadExceptionWarning app/sidecar/tests; else echo "skip app/sidecar tests (pip install -r app/sidecar/requirements.txt)"; fi

# 推送前：干净克隆 + 空 HOME + 无器件包里跑 CI 同款步骤（tools/preflight.sh）
preflight:
	tools/preflight.sh

check:
	$(PY) tools/validate_board.py boards/*/board.yaml
	$(PY) tools/test_port_policy.py
	for p in examples/*/project.yaml; do $(PY) tools/gen_project.py $$p --check || exit 1; done
	$(PY) tools/check_entrypoints.py --selftest
	$(PY) tools/check_entrypoints.py
	$(PY) tools/check_ui_layout.py --selftest
	$(PY) tools/check_ui_layout.py
	$(PY) tools/check_deps.py
	$(PY) tools/check_deps.py --selftest
	$(PY) tools/iface_hash.py --check
	$(PY) tools/iface_hash.py --selftest
	$(PY) tools/ioc_import.py --selftest
	$(PY) tools/test_ioc_import.py
	$(PY) tools/test_import_project.py
	$(PY) tools/keil_inject.py --selftest
	$(PY) tools/test_ide_nvm.py
	$(PY) tools/test_k230_vision.py
	CUBE_HAL= $(PY) tools/test_keil_inject.py   # 故意不给 HAL：CI 上没有 third_party，本地也按同样条件测
	$(PY) tools/test_module_ide.py
	$(PY) tools/test_mspm0_board.py
	$(PY) tools/test_dac_caps.py
	$(PY) tools/test_pwm3_caps.py
	$(PY) tools/test_adc_block_caps.py
	$(PY) tools/test_new_subsys.py
	$(PY) tools/test_subsys_kit.py
	$(PY) tools/test_report.py
	$(PY) tools/test_req.py
	$(PY) tools/test_params_diff.py
	$(PY) tools/test_scheme.py
	$(PY) tools/test_alloc.py
	$(PY) mechanical/calc/test_mech.py
	$(PY) mechanical/parts/test_parts.py
	for r in examples/*/requirements.yaml; do $(PY) tools/req.py check $$r >/dev/null || { $(PY) tools/req.py check $$r; exit 1; }; done
	for s in examples/*/scheme.yaml; do $(PY) tools/scheme.py $$(dirname $$s)/requirements.yaml --scheme $$s >/dev/null || { $(PY) tools/scheme.py $$(dirname $$s)/requirements.yaml --scheme $$s; exit 1; }; done
	for s in examples/*/scheme.yaml; do d=$$(dirname $$s); $(PY) tools/alloc.py $$s -o $$d/alloc --app $$d/app.yaml >/dev/null && git diff --quiet --exit-code -- $$d/alloc 2>/dev/null || { echo "$$d/alloc 与 alloc.py 输出不一致（或分配失败）：重跑 python3 tools/alloc.py $$s -o $$d/alloc --app $$d/app.yaml"; exit 1; }; done
	$(PY) tools/syscfg_import.py --selftest
	$(PY) tools/gen_link.py --selftest
	$(PY) tools/syscfg_import.py boards/mspm0g3507-tianmengxing/ccs/tianmengxing.syscfg --check boards/mspm0g3507-tianmengxing/board.yaml
	$(PY) tools/syscfg_import.py boards/mspm0g3507-launchpad/ccs/launchpad.syscfg --check boards/mspm0g3507-launchpad/board.yaml
	$(PY) tools/gen_ccs_projectspec.py --board mspm0g3507-tianmengxing --app car_2wd --check
	$(PY) tools/gen_ccs_projectspec.py --board mspm0g3507-launchpad --app car_2wd --check
	@$(MAKE) -s BOARD=mspm0g3507-tianmengxing APP=car_2wd M0_SDK=/nonexistent gen >/dev/null || { echo "✗ make gen 不应要求 MSPM0 SDK（CCS 导入前置步骤）"; exit 1; }
	$(PY) tools/audit_port.py --selftest
	$(PY) tools/check_ai_docs.py --selftest
	$(PY) tools/check_ai_docs.py --check
	$(PY) tools/check_vendored.py
	$(PY) tools/check_version.py
	$(MAKE) ioc-check
	$(PY) tools/check_gen_consistency.py --selftest
	$(PY) tools/check_gen_consistency.py
	$(MAKE) -C examples/2026H_ball/tests
	cd host/python && $(PY) -m dzlink.test_dzlink
	$(PY) host/maixcam/test_ball_sender.py
	$(PY) host/maixcam/test_ball_tracker.py
	cd host/python && $(PY) -m dzlink.test_latency
	cd host/python && $(PY) -m dzlink.test_sender
	cd host/python && $(PY) -m dzlink.test_dzsend_k230
	@if [ -x app/ui/node_modules/.bin/esbuild ]; then cd app/ui && for t in tests/*.test.ts; do node_modules/.bin/esbuild $$t --bundle --platform=node --log-level=error | node || exit 1; done; else echo "跳过 UI 单测（app/ui 未 npm install）"; fi

fetch:
	tools/fetch_stm32f4.sh

clean:
	rm -rf build

-include $(OBJS:.o=.d)
