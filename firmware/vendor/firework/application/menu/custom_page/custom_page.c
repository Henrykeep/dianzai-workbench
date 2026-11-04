/*
 * 这里是面向具体赛题的页面示例：显示业务状态、读取按键并给通用菜单返回动作。
 * 如果更换题目，通常优先修改本文件，而不是修改通用显示驱动。
 */
#include "application/menu/custom_page/custom_page.h"

#include <stddef.h>

#include "application/app_config.h"
#if APP_ENABLE_MATRIX_KEYPAD != 0U
#include "application/input/matrix_keypad_input/matrix_keypad_input.h"
#endif
#include "application/menu/display_menu/display_menu.h"

/*
 * 电赛自定义页面
 * --------------------------------------------------------------------------
 * 通常只需要修改下面四个位置：
 * 1. CustomPageRender()：按题目要求画标题、测量值和运行状态；
 * 2. CustomPageProcess()：定义左键 S1 和右键 S2 的短按、长按动作；
 * 3. CustomPageProcessMatrixKeypad()：读取并显示 4×4 矩阵键盘键值；
 * 4. CustomPageStatus_e 或本文件静态变量：保存题目界面需要的数据。
 *
 * 页面共用现有 DisplayMenu 任务，不要在这里创建死循环或调用长时间阻塞函数。
 * 其他任务更新数据后调用 CustomPageRequestRefresh()，由显示任务统一刷屏。
 */

/* 显示任务读取页面状态；其他任务通过公开接口更新状态并请求下一轮重绘。 */
static DisplayInstance *custom_page_display;
static CustomPageStatus_e custom_page_status = CUSTOM_PAGE_STATUS_READY;
static volatile bool custom_page_refresh_requested;
#if APP_ENABLE_MATRIX_KEYPAD != 0U
static char custom_page_last_matrix_key = '-';
#endif

static const char *CustomPageGetStatusLabel(void);
#if APP_ENABLE_MATRIX_KEYPAD != 0U
static CustomPageUpdate_e CustomPageProcessMatrixKeypad(void);
#endif

bool CustomPageInit(DisplayInstance *display)
{
    if (display == NULL) {
        return false;
    }
    if (custom_page_display != NULL) {
        return custom_page_display == display;
    }

    custom_page_display = display;
    custom_page_status = CUSTOM_PAGE_STATUS_READY;
    custom_page_refresh_requested = false;
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    custom_page_last_matrix_key = '-';
#endif
    return true;
}

bool CustomPageEnter(void)
{
    if (custom_page_display == NULL) {
        return false;
    }

    /* 每次进入都恢复到明确的初始状态，避免沿用上一次比赛流程。 */
    custom_page_status = CUSTOM_PAGE_STATUS_READY;
    custom_page_refresh_requested = false;
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    custom_page_last_matrix_key = '-';
    (void)MatrixKeypadInputClearEvents();
#endif
    return CustomPageRender();
}

bool CustomPageResume(void)
{
    if (custom_page_display == NULL) {
        return false;
    }

    /* 返回时不重置题目状态，只清除离开本页期间积累的旧按键事件。 */
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    (void)MatrixKeypadInputClearEvents();
#endif
    return CustomPageRender();
}

CustomPageUpdate_e CustomPageProcess(
    Button_Event_e left_event,
    Button_Event_e right_event,
    uint32_t elapsed_ms)
{
    (void)elapsed_ms;

    /* 右键 S2 长按始终保留为返回主菜单，现场调试时不会被困在自定义页。 */
    if (right_event == BUTTON_EVENT_LONG_PRESS) {
        return CUSTOM_PAGE_UPDATE_EXIT_TO_MENU;
    }

    /* 左键短按示范统一导航接口：进入 PA27 波形页，退出后回到本页。 */
    if (left_event == BUTTON_EVENT_SHORT_PRESS) {
        if (DisplayMenuOpenFromCustom(
                DISPLAY_MENU_ROUTE_WAVEFORM_PA27)) {
            return CUSTOM_PAGE_UPDATE_NONE;
        }
        custom_page_status = CUSTOM_PAGE_STATUS_ERROR;
        return CUSTOM_PAGE_UPDATE_REDRAW;
    }

    /* 左键长按：直接进入 PA27 FFT 主显示页；页面内左键短按可切换来源。 */
    if (left_event == BUTTON_EVENT_LONG_PRESS) {
        if (DisplayMenuOpenFromCustom(
                DISPLAY_MENU_ROUTE_FFT_PA27)) {
            return CUSTOM_PAGE_UPDATE_NONE;
        }
        custom_page_status = CUSTOM_PAGE_STATUS_ERROR;
        return CUSTOM_PAGE_UPDATE_REDRAW;
    }

    /* 右键短按：进入 DAC 输出菜单。 */
    if (right_event == BUTTON_EVENT_SHORT_PRESS) {
        if (DisplayMenuOpenFromCustom(
                DISPLAY_MENU_ROUTE_DAC_OUTPUT_MENU)) {
            return CUSTOM_PAGE_UPDATE_NONE;
        }
        custom_page_status = CUSTOM_PAGE_STATUS_ERROR;
        return CUSTOM_PAGE_UPDATE_REDRAW;
    }

#if APP_ENABLE_MATRIX_KEYPAD != 0U
    {
        CustomPageUpdate_e matrix_update =
            CustomPageProcessMatrixKeypad();

        if (matrix_update != CUSTOM_PAGE_UPDATE_NONE) {
            return matrix_update;
        }
    }
#endif

    if (custom_page_refresh_requested) {
        custom_page_refresh_requested = false;
        return CUSTOM_PAGE_UPDATE_REDRAW;
    }
    return CUSTOM_PAGE_UPDATE_NONE;
}

bool CustomPageRender(void)
{
    uint8_t x;
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    char matrix_key_label[] = "KEY:-";

    matrix_key_label[4] = custom_page_last_matrix_key;
#endif

    if ((custom_page_display == NULL) ||
        !DisplayClear(custom_page_display, false) ||
        !DisplayDrawString(custom_page_display, 0U, 0U, "CONTEST PAGE")) {
        return false;
    }

    for (x = 0U; x < DISPLAY_WIDTH; ++x) {
        (void)DisplaySetPixel(custom_page_display, x, 9U, true);
    }

    /*
     * ===== 电赛界面主要修改区 =====
     * 逻辑画布固定为 128×64；字符约 6×8 像素，每行最多建议 20 个 ASCII 字符。
     * 动态数据可先写入本文件静态变量，再在这里格式化并绘制。
     */
    return DisplayDrawString(custom_page_display, 0U, 16U, "STATUS:") &&
           DisplayDrawString(custom_page_display, 48U, 16U,
               CustomPageGetStatusLabel()) &&
#if APP_ENABLE_MATRIX_KEYPAD != 0U
           DisplayDrawString(custom_page_display, 0U, 28U,
               "MATRIX") &&
           DisplayDrawString(custom_page_display, 42U, 28U,
               matrix_key_label) &&
           DisplayDrawString(custom_page_display, 0U, 36U,
               "EDIT custom_page.c") &&
           DisplayDrawString(custom_page_display, 0U, 48U,
               "S1 WAVE/HOLD FFT") &&
           DisplayDrawString(custom_page_display, 0U, 56U,
               "S2 DAC/HOLD MENU") &&
#else
           DisplayDrawString(custom_page_display, 0U, 28U,
               "EDIT custom_page.c") &&
           DisplayDrawString(custom_page_display, 0U, 36U,
               "FOR CONTEST UI") &&
           DisplayDrawString(custom_page_display, 0U, 48U,
               "S1 WAVE/HOLD FFT") &&
           DisplayDrawString(custom_page_display, 0U, 56U,
               "S2 DAC/HOLD MENU") &&
#endif
           DisplayUpdate(custom_page_display);
}

#if APP_ENABLE_MATRIX_KEYPAD != 0U
/*
 * 矩阵键盘当前只显示最近一次按下的键，不执行页面跳转或控制动作。
 * 每次只处理一个新按下的键；释放事件不会改变页面显示。
 */

 
static CustomPageUpdate_e CustomPageProcessMatrixKeypad(void)
{
    MatrixKeypadEvent event;
    MatrixKeypadKey_e key;

    /* 跳过纯释放事件，直到队列为空或取得一个新按下事件。 */
    do {
        if (!MatrixKeypadInputGetEvent(&event)) {
            return CUSTOM_PAGE_UPDATE_NONE;
        }
        key = MatrixKeypadFindFirstKey(event.pressed_keys);
    } while (key == MATRIX_KEYPAD_KEY_NONE);

    custom_page_last_matrix_key = MatrixKeypadKeyToChar(key);
    return CUSTOM_PAGE_UPDATE_REDRAW;
}
#endif

bool CustomPageSetStatus(CustomPageStatus_e status)
{
    if ((status < CUSTOM_PAGE_STATUS_READY) ||
        (status > CUSTOM_PAGE_STATUS_ERROR)) {
        return false;
    }

    custom_page_status = status;
    CustomPageRequestRefresh();
    return true;
}

void CustomPageRequestRefresh(void)
{
    custom_page_refresh_requested = true;
}

static const char *CustomPageGetStatusLabel(void)
{
    switch (custom_page_status) {
        case CUSTOM_PAGE_STATUS_READY:
            return "READY";
        case CUSTOM_PAGE_STATUS_RUNNING:
            return "RUNNING";
        case CUSTOM_PAGE_STATUS_FINISHED:
            return "FINISHED";
        case CUSTOM_PAGE_STATUS_ERROR:
            return "ERROR";
        default:
            return "UNKNOWN";
    }
}
