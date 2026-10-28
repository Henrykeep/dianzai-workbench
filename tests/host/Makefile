# 主机单元测试：所有 firmware 模块 + host-sim 移植层，开 ASan/UBSan。
ROOT := ../..
GEN  := $(ROOT)/build/host-sim/gen
OUT  := $(ROOT)/build/tests
INC  := $(addprefix -I,$(ROOT)/firmware/common $(ROOT)/firmware/pal $(wildcard $(ROOT)/firmware/algo/*) \
        $(wildcard $(ROOT)/firmware/drivers/*) $(ROOT)/ports/host-sim $(GEN) $(ROOT)/apps/include \
        $(wildcard $(ROOT)/firmware/framework/*))
SRC  := $(wildcard *.c) $(wildcard $(ROOT)/firmware/algo/*/*.c $(ROOT)/firmware/drivers/*/*.c) \
        $(ROOT)/ports/host-sim/pal_host.c $(GEN)/board_gen.c \
        $(wildcard $(ROOT)/firmware/framework/*/*.c)
CFLAGS := -std=c11 -O1 -g -Wall -Wextra -Werror -Wshadow -Wno-unused-parameter -fsanitize=address,undefined -fno-omit-frame-pointer

.PHONY: run
run: $(OUT)/unit_tests
	$(OUT)/unit_tests
$(GEN)/board_gen.h: $(ROOT)/boards/host-sim/board.yaml
	python3 $(ROOT)/tools/gen_board.py $(ROOT)/boards/host-sim/board.yaml -o $(GEN)
$(OUT)/unit_tests: $(SRC) $(GEN)/board_gen.h $(wildcard *.h) $(wildcard $(ROOT)/firmware/*/*/*.h)
	@mkdir -p $(OUT)
	gcc $(CFLAGS) $(INC) $(SRC) -lm -o $@
