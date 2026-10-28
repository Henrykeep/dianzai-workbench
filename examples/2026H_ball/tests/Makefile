# 本题的模拟数据测试：make -C examples/2026H_ball/tests
ROOT := ../../..
EX   := ..
OUT  := $(ROOT)/build/examples/2026H_ball
INC  := $(addprefix -I,$(ROOT)/tests/host $(ROOT)/firmware/common $(wildcard $(ROOT)/firmware/algo/*) \
        $(wildcard $(ROOT)/firmware/framework/*) $(ROOT)/firmware/proto/dzframe $(OUT))
SRC  := test_example.c $(wildcard $(EX)/subsys/*/*.c) $(OUT)/project_gen.c $(OUT)/cp_vision_cpu.c \
        $(wildcard $(ROOT)/firmware/algo/*/*.c $(ROOT)/firmware/framework/*/*.c $(ROOT)/firmware/proto/*/*.c)
# C↔Python 互通：用 host/maixcam/ball_sender.py 现场编一帧，C 端解码核对
PYBALL := $(shell cd $(ROOT)/host/maixcam && python3 -c "from ball_sender import BallSender; print(','.join('0x%02x' % b for b in BallSender(None).frame(-123, 4000000000)))")
CFLAGS := -DPY_BALL_FRAME='{$(PYBALL)}' -std=c11 -O1 -g -Wall -Wextra -Werror -Wshadow -Wno-unused-parameter -fsanitize=address,undefined

.PHONY: run
run: $(OUT)/tests
	$(OUT)/tests
$(OUT)/project_gen.c $(OUT)/cp_vision_cpu.c &: $(EX)/project.yaml $(ROOT)/tools/gen_project.py $(ROOT)/tools/gen_coproc.py $(ROOT)/boards/maixcam2-vision/board.yaml
	python3 $(ROOT)/tools/gen_project.py $< -o $(OUT)
$(OUT)/tests: $(SRC)
	@echo "  CC+LD  $@"
	@gcc $(CFLAGS) $(INC) $(SRC) -lm -o $@
