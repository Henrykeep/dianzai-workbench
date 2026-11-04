/**
 * @file blinky.h
 * @brief 板载 LED 轮转示例任务的初始化接口。
 */
#ifndef BLINKY_H
#define BLINKY_H

#include <stdbool.h>

/** 注册四路板载 LED，并创建红灯与 RGB 三色轮转模块任务。 */
bool BlinkyInit(void);

#endif
