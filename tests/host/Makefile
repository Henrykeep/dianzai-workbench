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
run: $(OUT)/unit_tests
	$(OUT)/unit_tests
$(GEN)/board_gen.h: $(ROOT)/boards/host-sim/board.yaml
	python3 $(ROOT)/tools/gen_board.py $(ROOT)/boards/host-sim/board.yaml -o $(GEN)
$(OUT)/unit_tests: $(SRC) $(GEN)/board_gen.h $(wildcard *.h) $(wildcard $(ROOT)/firmware/*/*/*.h)
	@mkdir -p $(OUT)
	@echo "  CC+LD  $@"
	@gcc $(CFLAGS) $(INC) $(SRC) -lm -o $@

# C↔Python 互通：用 host/python/dzlink 现场编码一帧，把它算出的 CRC 传给 C 测试
PYFRAME := $(shell cd $(ROOT)/host/python && python3 -c "from dzlink.protocol import encode; print(encode(0, 5, 9, bytes.fromhex('01020304')).hex())")
CFLAGS += -DPY_CRC_L=0x$(shell echo $(PYFRAME) | cut -c23-24) -DPY_CRC_H=0x$(shell echo $(PYFRAME) | cut -c25-26)
