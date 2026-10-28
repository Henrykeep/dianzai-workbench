# 本题的模拟数据测试：make -C examples/2026H_ball/tests
ROOT := ../../..
EX   := ..
OUT  := $(ROOT)/build/examples/2026H_ball
INC  := $(addprefix -I,$(ROOT)/tests/host $(ROOT)/firmware/common $(wildcard $(ROOT)/firmware/algo/*) \
        $(wildcard $(ROOT)/firmware/framework/*) $(EX)/lib $(OUT))
SRC  := test_example.c $(wildcard $(EX)/subsys/*/*.c) $(EX)/lib/vision_link.c $(OUT)/project_gen.c \
        $(wildcard $(ROOT)/firmware/algo/*/*.c $(ROOT)/firmware/framework/*/*.c)
CFLAGS := -std=c11 -O1 -g -Wall -Wextra -Werror -Wshadow -Wno-unused-parameter -fsanitize=address,undefined

.PHONY: run
run: $(OUT)/tests
	$(OUT)/tests
$(OUT)/project_gen.c: $(EX)/project.yaml $(ROOT)/tools/gen_project.py
	python3 $(ROOT)/tools/gen_project.py $< -o $(OUT)
$(OUT)/tests: $(SRC)
	gcc $(CFLAGS) $(INC) $(SRC) -lm -o $@
