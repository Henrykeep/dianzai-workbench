/**
 * @file matrix_keypad_input.h
 * @brief 矩阵键盘扫描任务和按键事件队列的对外接口。
 *
 * 页面层通过队列消费稳定按键事件，不需要直接了解行列扫描细节。
 */
#ifndef APPLICATION_INPUT_MATRIX_KEYPAD_INPUT_H
#define APPLICATION_INPUT_MATRIX_KEYPAD_INPUT_H

#include <stdbool.h>
#include <stdint.h>

#include "modules/matrix_keypad/matrix_keypad.h"

/** 矩阵键盘扫描任务的运行统计和当前稳定状态。 */
typedef struct {
    uint16_t stable_keys;
    uint32_t scan_count;
    uint32_t scan_error_count;
    uint32_t dropped_event_count;
    bool ready;
} MatrixKeypadInputStatus;

/** 注册矩阵键盘、创建静态事件队列和 MatrixKeypad 扫描任务。 */
bool MatrixKeypadInputInit(void);

/** 非阻塞读取一个按键事件；当前没有事件时返回 false。 */
bool MatrixKeypadInputGetEvent(MatrixKeypadEvent *event);

/** 等待一个按键事件，timeout_ms=0U 时等同于非阻塞读取。 */
bool MatrixKeypadInputWaitEvent(
    MatrixKeypadEvent *event, uint32_t timeout_ms);

/** 清空尚未消费的按键事件；切换页面时可用它避免执行旧按键。 */
bool MatrixKeypadInputClearEvents(void);

/** 读取扫描任务状态、当前稳定键值和事件队列溢出统计。 */
bool MatrixKeypadInputGetStatus(MatrixKeypadInputStatus *status);

/** 返回 Application 是否已经完成初始化和任务创建。 */
bool MatrixKeypadInputIsReady(void);

/** 返回矩阵键盘任务启动以来的最小空闲栈，单位为 words。 */
uint32_t MatrixKeypadInputGetMinimumFreeStackWords(void);

#endif
