# 主机单元测试：所有 firmware 模块 + host-sim 移植层，开 ASan/UBSan。
ROOT := ../..
GEN  := $(ROOT)/build/host-sim/gen
OUT  := $(ROOT)/build/tests
INC  := $(addprefix -I,$(ROOT)/firmware/common $(ROOT)/firmware/pal $(wildcard $(ROOT)/firmware/algo/*) \
        $(wildcard $(ROOT)/firmware/drivers/*) $(ROOT)/ports/host-sim $(GEN) $(ROOT)/apps/include \
        $(wildcard $(ROOT)/firmware/framework/*) $(wildcard $(ROOT)/firmware/proto/*))
SRC  := $(wildcard *.c) $(wildcard $(ROOT)/firmware/algo/*/*.c $(ROOT)/firmware/drivers/*/*.c) \
        $(ROOT)/ports/host-sim/pal_host.c $(GEN)/board_gen.c \
        $(wildcard $(ROOT)/firmware/framework/*/*.c) $(wildcard $(ROOT)/firmware/proto/*/*.c)
CFLAGS := -std=c11 -O1 -g -Wall -Wextra -Werror -Wshadow -Wno-unused-parameter -fsanitize=address,undefined -fno-omit-frame-pointer

.PHONY: run
run: $(OUT)/unit_tests $(OUT)/car_2wd_test
	$(OUT)/unit_tests
	$(OUT)/car_2wd_test
$(GEN)/board_gen.h: $(ROOT)/boards/host-sim/board.yaml
	python3 $(ROOT)/tools/gen_board.py $(ROOT)/boards/host-sim/board.yaml -o $(GEN)
$(OUT)/unit_tests: $(SRC) $(GEN)/board_gen.h $(wildcard *.h) $(wildcard $(ROOT)/firmware/*/*/*.h)
	@mkdir -p $(OUT)
	@echo "  CC+LD  $@"
	@gcc $(CFLAGS) $(INC) $(SRC) -lm -o $@

# C↔Python 互通：用 host/python/dzlink 现场编码一帧，把它算出的 CRC 传给 C 测试
PYFRAME := $(shell cd $(ROOT)/host/python && python3 -c "from dzlink.protocol import encode; print(encode(0, 5, 9, bytes.fromhex('01020304')).hex())")
CFLAGS += -DPY_CRC_L=0x$(shell echo $(PYFRAME) | cut -c23-24) -DPY_CRC_H=0x$(shell echo $(PYFRAME) | cut -c25-26)

# 应用级闭环测试：car_2wd（多板验收用例）的真实 app 代码 + host-sim 电机模型
CAR := $(ROOT)/apps/car_2wd
CAR_SRC := $(CAR)/tests/test_car.c $(CAR)/app_main.c $(CAR)/drive_plan.c $(CAR)/sim_setup.c \
           $(filter-out $(wildcard $(ROOT)/firmware/*/*/*selftest*.c),$(wildcard $(ROOT)/firmware/algo/*/*.c $(ROOT)/firmware/drivers/*/*.c)) \
           $(ROOT)/ports/host-sim/pal_host.c $(GEN)/board_gen.c $(OUT)/car_link/link_gen.c \
           $(wildcard $(ROOT)/firmware/framework/*/*.c) $(wildcard $(ROOT)/firmware/proto/*/*.c)
$(OUT)/car_link/link_gen.c: $(CAR)/app.yaml $(ROOT)/tools/gen_link.py
	python3 $(ROOT)/tools/gen_link.py $< -o $(OUT)/car_link
$(OUT)/car_2wd_test: $(CAR_SRC) $(GEN)/board_gen.h $(wildcard $(CAR)/*.h)
	@mkdir -p $(OUT)
	@echo "  CC+LD  $@"
	@gcc $(CFLAGS) $(INC) -I$(CAR) -I$(OUT)/car_link $(CAR_SRC) -lm -o $@
