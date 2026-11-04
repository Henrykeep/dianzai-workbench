/**
 * @file matrix_keypad.h
 * @brief 4×4 矩阵键盘扫描、防抖、键值映射和事件读取接口。
 */
#ifndef MATRIX_KEYPAD_H
#define MATRIX_KEYPAD_H

#include <stdbool.h>
#include <stdint.h>

#define MATRIX_KEYPAD_ROW_COUNT    (4U)
#define MATRIX_KEYPAD_COLUMN_COUNT (4U)
#define MATRIX_KEYPAD_KEY_COUNT    (16U)

/** 4x4 键盘的逻辑键，按常见面板从左到右、从上到下排列。 */
typedef enum {
    MATRIX_KEYPAD_KEY_1 = 0,
    MATRIX_KEYPAD_KEY_2,
    MATRIX_KEYPAD_KEY_3,
    MATRIX_KEYPAD_KEY_A,
    MATRIX_KEYPAD_KEY_4,
    MATRIX_KEYPAD_KEY_5,
    MATRIX_KEYPAD_KEY_6,
    MATRIX_KEYPAD_KEY_B,
    MATRIX_KEYPAD_KEY_7,
    MATRIX_KEYPAD_KEY_8,
    MATRIX_KEYPAD_KEY_9,
    MATRIX_KEYPAD_KEY_C,
    MATRIX_KEYPAD_KEY_STAR,
    MATRIX_KEYPAD_KEY_0,
    MATRIX_KEYPAD_KEY_HASH,
    MATRIX_KEYPAD_KEY_D,
    MATRIX_KEYPAD_KEY_NONE = 0xFF
} MatrixKeypadKey_e;

/** 一次防抖扫描产生的按下、释放和当前保持状态。 */
typedef struct {
    uint16_t pressed_keys;
    uint16_t released_keys;
    uint16_t held_keys;
} MatrixKeypadEvent;

/** Matrix Keypad 模块的不透明静态实例。 */
typedef struct MatrixKeypadInstance MatrixKeypadInstance;

/** 注册矩阵键盘并将所有行恢复到高电平；失败时返回 NULL。 */
MatrixKeypadInstance *MatrixKeypadRegister(void);

/**
 * @brief 立即扫描一次物理矩阵，返回未经软件防抖的按键位图。
 *
 * 位 0～15 分别对应 MatrixKeypadKey_e 的 0～15。
 */
bool MatrixKeypadReadRaw(
    MatrixKeypadInstance *instance, uint16_t *pressed_keys);

/**
 * @brief 扫描并独立防抖每个按键。
 *
 * @param elapsed_ms 距离上次调用经过的毫秒数，推荐每 5～10 ms 调用一次。
 * @param event 本次新产生的按下/释放事件及当前稳定按键状态。
 */
bool MatrixKeypadProcess(MatrixKeypadInstance *instance,
    uint32_t elapsed_ms, MatrixKeypadEvent *event);

/** 读取最近一次防抖扫描得到的稳定按键位图。 */
bool MatrixKeypadGetStableKeys(
    const MatrixKeypadInstance *instance, uint16_t *pressed_keys);

/** 返回指定逻辑键对应的单个位掩码；参数非法时返回 0。 */
uint16_t MatrixKeypadKeyMask(MatrixKeypadKey_e key);

/** 把逻辑键转换为 '0'～'9'、'A'～'D'、'*' 或 '#'。 */
char MatrixKeypadKeyToChar(MatrixKeypadKey_e key);

/** 找到位图中编号最小的键；位图为空时返回 MATRIX_KEYPAD_KEY_NONE。 */
MatrixKeypadKey_e MatrixKeypadFindFirstKey(uint16_t pressed_keys);

#endif
