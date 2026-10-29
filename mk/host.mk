# mk/host.mk —— BOARD_FAMILY=host 的编译器、HAL/SDK、链接脚本（由顶层 Makefile include；2026-10-29 从 Makefile 原样拆出，行为不变）
# ------------------------------------------------------------------ host
ifeq ($(BOARD_FAMILY),host)
CC      := gcc
# mingw 没有 libasan/libubsan：Windows 上默认不开 sanitizer（SAN= 可手动覆盖）。Windows 能否完整跑仿真板 [未测]
ifeq ($(OS),Windows_NT)
SAN     ?=
else
SAN     ?= -fsanitize=address,undefined
endif
CFLAGS  := -std=c11 -O2 -g $(WARN) -Wno-double-promotion $(SAN) -fno-omit-frame-pointer
LDFLAGS := $(SAN) -lm
PORT_SRC = $(PORT_DIR)/pal_host.c $(PORT_DIR)/main_host.c $(SIM_SETUP)
TARGET   = $(OUT)/$(APP).elf
endif
