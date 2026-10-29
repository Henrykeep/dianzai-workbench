/**
 * @file keypad4x4.h
 * @brief 4×4 矩阵键盘：逐行扫描 + 每键独立消抖 + 按下/松开/保持位图 + 字符映射。
 *
 *   接线：4 行输出、4 列输入（上拉）。board.yaml 里行配 active_low（选中 = 拉低），列配 active_low（按下 = 读到低）。
 *   扫描时只有当前行有效、其余行无效（推挽高）。**多键同按时两行可能经按键短接**：
 *   行脚在 CubeMX/SysConfig 配成开漏输出 + 外部/内部上拉最稳（原版做法是非选中行切高阻，pal 没有这个接口）。
 *
 * Source: LP-MSPM0G3507_freertos_firework@ede35a2 modules/matrix_keypad/matrix_keypad.c
 *   （MIT，Copyright (c) 2026 阡陌）——每键独立消抖计时（原始变化清零、稳定且与当前态不同才累计、饱和加）、
 *   位图事件、键位表直接移植。改动：BSP GPIO → pal_gpio（行列逻辑 ID 由调用方给）；消抖拆成纯函数 kp_debounce 便于主机测试；
 *   消抖时间可配（原版固定 30 ms）；行切换后可选稳定延时。
 * 版本：KEYPAD4X4_VERSION
 */
#ifndef KEYPAD4X4_H
#define KEYPAD4X4_H

#include <stdbool.h>
#include <stdint.h>
#include "dz_err.h"
#include "pal.h"

#define KEYPAD4X4_VERSION "1.0.0"
#define KP_KEYS 16u
#define KP_NONE (-1)

typedef struct {
    pal_id_t row[4];
    pal_id_t col[4];
    uint16_t debounce_ms;  /**< 典型 30 */
    uint16_t settle_us;    /**< 选中一行后读列前等待，长排线/大电容时给 2..10 */
} kp_cfg_t;

typedef struct { uint16_t pressed, released, held; } kp_event_t;   /**< 位 i = 键 i（行×4+列） */

typedef struct {
    kp_cfg_t c;
    uint16_t last_raw, stable;
    uint16_t acc_ms[KP_KEYS];
} keypad_t;

dz_err_t kp_init(keypad_t *k, const kp_cfg_t *c);
/** 纯消抖：喂一帧原始位图。返回 DZ_EINVAL 表示参数错。 */
dz_err_t kp_debounce(keypad_t *k, uint16_t raw, uint32_t elapsed_ms, kp_event_t *ev);
/** 扫一遍物理矩阵（不消抖）。 */
dz_err_t kp_scan_raw(keypad_t *k, uint16_t *raw);
/** 扫描 + 消抖，推荐每 5..10 ms 调一次。 */
dz_err_t kp_process(keypad_t *k, uint32_t elapsed_ms, kp_event_t *ev);
/** 键号 → '1'..'9','0','A'..'D','*','#'；非法返回 '\0'。 */
char kp_char(int key);
/** 位图里编号最小的键，空返回 KP_NONE。 */
int  kp_first(uint16_t bits);

dz_err_t keypad4x4_selftest(void);

#endif /* KEYPAD4X4_H */
