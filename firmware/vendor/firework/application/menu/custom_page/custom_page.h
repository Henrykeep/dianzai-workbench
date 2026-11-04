/**
 * @file custom_page.h
 * @brief 面向电赛题目的可替换自定义显示页面接口。
 *
 * 自定义页负责题目业务展示和按键动作，通用菜单负责页面路由与任务调度。
 */
#ifndef CUSTOM_PAGE_H
#define CUSTOM_PAGE_H

#include <stdbool.h>
#include <stdint.h>

#include "modules/button/button.h"
#include "modules/display/display.h"

/** 示例状态；做赛题时可按题目含义增删。 */
typedef enum {
    CUSTOM_PAGE_STATUS_READY = 0,
    CUSTOM_PAGE_STATUS_RUNNING,
    CUSTOM_PAGE_STATUS_FINISHED,
    CUSTOM_PAGE_STATUS_ERROR
} CustomPageStatus_e;

/** 页面处理结果，由 DisplayMenu 决定是否重绘或返回主菜单。 */
typedef enum {
    CUSTOM_PAGE_UPDATE_NONE = 0,
    CUSTOM_PAGE_UPDATE_REDRAW,
    CUSTOM_PAGE_UPDATE_EXIT_TO_MENU
} CustomPageUpdate_e;

/** 绑定当前 OLED/TFT 通用显示实例，不创建新的 RTOS 任务。 */
bool CustomPageInit(DisplayInstance *display);

/** 进入页面并立即绘制；上电初始页和菜单入口共用此接口。 */
bool CustomPageEnter(void);

/** 从其他功能页返回，保留比赛状态、清除旧矩阵按键并重新绘制。 */
bool CustomPageResume(void);

/**
 * 处理一次 10 ms 页面节拍、两个独立按键以及矩阵键盘事件。
 * left_event  = 左键 S1 / PA18。
 * right_event = 右键 S2 / PB21。
 * 默认长按右键返回主菜单；矩阵键盘只更新页面显示的最近键值。
 */
CustomPageUpdate_e CustomPageProcess(
    Button_Event_e left_event,
    Button_Event_e right_event,
    uint32_t elapsed_ms);

/** 绘制比赛界面；这是赛前最常修改的函数。 */
bool CustomPageRender(void);

/** 其他题目任务可以调用它更新示例状态并请求下一周期重绘。 */
bool CustomPageSetStatus(CustomPageStatus_e status);

/** 外部数据变化后请求显示任务重绘；不要在中断中直接刷屏。 */
void CustomPageRequestRefresh(void);

#endif
