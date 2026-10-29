/**
 * @file menu.h
 * @brief 板上菜单：静态页面树、选中项、滚动窗口、进入子页/执行动作、返回、按页面跳转、数值编辑项。
 *        与显示无关——画什么交给 menu_view_t 的回调（OLED ssd1306 / TFT st77xx / 串口都行）。
 *
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/menu/menu.c
 *   （MIT，Copyright (c) 2026 阡陌）——页面栈 + 每层选中/首行、循环上下移、滚动窗口同步、
 *   递归找页面路径（限深防环）直接移植。改动：单例 → 调用方持有句柄；绘制改为回调（行数/列数可配）；
 *   新增数值编辑项（float 指针 + 步长 + 上下限，按“选中”进入编辑，上下改值，再按退出）和输入事件入口。
 * 版本：MENU_VERSION
 */
#ifndef MENU_H
#define MENU_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"

#define MENU_VERSION   "1.0.0"
#define MENU_MAX_DEPTH 6u
#define MENU_MAX_COLS  31u

typedef struct menu_page menu_page_t;

typedef struct {
    const char *label;
    const menu_page_t *sub;          /**< 非 NULL：进入子页 */
    void (*action)(void *ctx);       /**< 非 NULL：执行动作 */
    void *ctx;
    float *value;                    /**< 非 NULL：数值编辑项（sub/action 都为 NULL 时生效） */
    float step, min, max;
} menu_item_t;

struct menu_page { const char *title; const menu_item_t *items; uint8_t n; };

typedef struct {
    uint8_t rows;                    /**< 屏幕总行数（含标题行），≥ 2 */
    uint8_t cols;                    /**< 每行字符数，≤ MENU_MAX_COLS */
    void (*clear)(void *ctx);
    void (*line)(void *ctx, uint8_t row, const char *text, bool selected);   /**< row 0 = 标题 */
    void (*flush)(void *ctx);
    void *ctx;
} menu_view_t;

typedef enum { MENU_IN_UP = 0, MENU_IN_DOWN, MENU_IN_OK, MENU_IN_BACK } menu_in_t;

typedef struct {
    const menu_page_t *stack[MENU_MAX_DEPTH];
    uint8_t sel[MENU_MAX_DEPTH], first[MENU_MAX_DEPTH], depth;
    bool editing;
    const menu_view_t *view;
} menu_t;

dz_err_t menu_init(menu_t *m, const menu_page_t *root, const menu_view_t *view);
bool menu_next(menu_t *m);
bool menu_prev(menu_t *m);
bool menu_select(menu_t *m);     /**< 进子页 / 执行动作 / 进出编辑 */
bool menu_back(menu_t *m);       /**< 编辑中先退出编辑；根页返回 false */
bool menu_goto(menu_t *m, const menu_page_t *target);
/** 统一输入入口：编辑中 UP/DOWN 改值，否则移动。返回 true 表示需要重画。 */
bool menu_input(menu_t *m, menu_in_t in);
uint8_t menu_depth(const menu_t *m);
const menu_item_t *menu_current(const menu_t *m);
const menu_page_t *menu_page(const menu_t *m);
dz_err_t menu_render(const menu_t *m);

dz_err_t menu_selftest(void);

#endif /* MENU_H */
