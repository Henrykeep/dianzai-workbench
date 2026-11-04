# dz_store 主机测试：FlashDB + FAL + EasyLogger 原样源码 + 芯台 pal 移植，gcc + ASan/UBSan
ROOT := ../..
V := $(ROOT)/firmware/vendor
CC ?= gcc
SRC := test_store.c $(V)/port_pal/dz_store.c $(V)/port_pal/elog_port.c \
  $(wildcard $(V)/flashdb/src/*.c) $(wildcard $(V)/flashdb/port/fal/src/*.c) \
  $(V)/easylogger/src/elog.c $(V)/easylogger/src/elog_utils.c
INC := -I$(V)/port_pal -I$(V)/flashdb/inc -I$(V)/flashdb/port/fal/inc -I$(V)/easylogger/inc -I$(ROOT)/firmware/pal -I$(ROOT)/firmware/common
CFLAGS ?= -std=c99 -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer
OUT ?= /tmp/dz_test_store
all: run
$(OUT): $(SRC)
	$(CC) $(CFLAGS) $(INC) $(SRC) -o $@
run: $(OUT)
	$(OUT) 1 && $(OUT) 42 && $(OUT) $$$$
.PHONY: all run
