/*
 * 矩阵键盘输入层负责固定周期扫描、消抖和事件排队。
 * 菜单任务只读取 MatrixKeypadEvent，不直接操作行列 GPIO，便于替换输入设备。
 */
#include "application/input/matrix_keypad_input/matrix_keypad_input.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"

#include "application/app_config.h"
#if APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT != 0U
#include "application/communication/serial_communication/serial_communication.h"
#endif
#include "application/task/task_manager.h"

#define MATRIX_KEYPAD_INPUT_EVENT_QUEUE_LENGTH (8U)

#if APP_ENABLE_MATRIX_KEYPAD != 0U
/* 扫描任务通过静态队列向页面发布状态变化，不依赖 FreeRTOS 动态堆。 */
static MatrixKeypadInstance *matrix_keypad_input_device;
static QueueHandle_t matrix_keypad_input_event_queue;
static StaticQueue_t matrix_keypad_input_event_queue_control;
static uint8_t matrix_keypad_input_event_queue_storage[
    MATRIX_KEYPAD_INPUT_EVENT_QUEUE_LENGTH * sizeof(MatrixKeypadEvent)];

/* 状态接口在临界区内复制这些由扫描任务更新的统计与稳定键位。 */
static volatile uint16_t matrix_keypad_input_stable_keys;
static volatile uint32_t matrix_keypad_input_scan_count;
static volatile uint32_t matrix_keypad_input_scan_error_count;
static volatile uint32_t matrix_keypad_input_dropped_event_count;
static bool matrix_keypad_input_task_created;
static bool matrix_keypad_input_ready;

static void MatrixKeypadInputTask(void *argument);
static void MatrixKeypadInputPublishEvent(
    const MatrixKeypadEvent *event);
#if APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT != 0U
static void MatrixKeypadInputSendPressedKeysUART3(uint16_t pressed_keys);
#endif
#endif

bool MatrixKeypadInputInit(void)
{
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    if (matrix_keypad_input_ready) {
        return true;
    }

    matrix_keypad_input_device = MatrixKeypadRegister();
    if (matrix_keypad_input_device == NULL) {
        return false;
    }

    if (matrix_keypad_input_event_queue == NULL) {
        matrix_keypad_input_event_queue = xQueueCreateStatic(
            MATRIX_KEYPAD_INPUT_EVENT_QUEUE_LENGTH,
            sizeof(MatrixKeypadEvent),
            matrix_keypad_input_event_queue_storage,
            &matrix_keypad_input_event_queue_control);
        if (matrix_keypad_input_event_queue == NULL) {
            return false;
        }
    }

    matrix_keypad_input_stable_keys        = 0U;
    matrix_keypad_input_scan_count         = 0U;
    matrix_keypad_input_scan_error_count   = 0U;
    matrix_keypad_input_dropped_event_count = 0U;

    if (!matrix_keypad_input_task_created &&
        (ApplicationTaskCreate(APPLICATION_TASK_MATRIX_KEYPAD,
             MatrixKeypadInputTask, NULL) == NULL)) {
        return false;
    }

    matrix_keypad_input_task_created = true;
    matrix_keypad_input_ready        = true;
    return true;
#else
    return false;
#endif
}

bool MatrixKeypadInputGetEvent(MatrixKeypadEvent *event)
{
    return MatrixKeypadInputWaitEvent(event, 0U);
}

bool MatrixKeypadInputWaitEvent(
    MatrixKeypadEvent *event, uint32_t timeout_ms)
{
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    TickType_t timeout_ticks;

    if (!matrix_keypad_input_ready ||
        (matrix_keypad_input_event_queue == NULL) || (event == NULL)) {
        return false;
    }

    if (timeout_ms == UINT32_MAX) {
        timeout_ticks = portMAX_DELAY;
    } else {
        timeout_ticks = pdMS_TO_TICKS(timeout_ms);
        if ((timeout_ms > 0U) && (timeout_ticks == 0U)) {
            timeout_ticks = 1U;
        }
    }

    return xQueueReceive(matrix_keypad_input_event_queue,
               event, timeout_ticks) == pdPASS;
#else
    (void)event;
    (void)timeout_ms;
    return false;
#endif
}

bool MatrixKeypadInputClearEvents(void)
{
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    if (!matrix_keypad_input_ready ||
        (matrix_keypad_input_event_queue == NULL)) {
        return false;
    }

    return xQueueReset(matrix_keypad_input_event_queue) == pdPASS;
#else
    return false;
#endif
}

bool MatrixKeypadInputGetStatus(MatrixKeypadInputStatus *status)
{
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    if (status == NULL) {
        return false;
    }

    taskENTER_CRITICAL();
    status->stable_keys        = matrix_keypad_input_stable_keys;
    status->scan_count         = matrix_keypad_input_scan_count;
    status->scan_error_count   = matrix_keypad_input_scan_error_count;
    status->dropped_event_count =
        matrix_keypad_input_dropped_event_count;
    status->ready = matrix_keypad_input_ready;
    taskEXIT_CRITICAL();
    return status->ready;
#else
    (void)status;
    return false;
#endif
}

bool MatrixKeypadInputIsReady(void)
{
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    return matrix_keypad_input_ready &&
           matrix_keypad_input_task_created &&
           (matrix_keypad_input_device != NULL) &&
           (matrix_keypad_input_event_queue != NULL);
#else
    return false;
#endif
}

uint32_t MatrixKeypadInputGetMinimumFreeStackWords(void)
{
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    return ApplicationTaskGetMinimumFreeStackWords(
        APPLICATION_TASK_MATRIX_KEYPAD);
#else
    return 0U;
#endif
}

#if APP_ENABLE_MATRIX_KEYPAD != 0U
/* 每个周期完成一次完整 4×4 扫描，Module 内部负责各键独立防抖。 */
static void MatrixKeypadInputTask(void *argument)
{
    TickType_t next_wake_time = xTaskGetTickCount();
    TickType_t period_ticks =
        pdMS_TO_TICKS(APP_MATRIX_KEYPAD_SCAN_PERIOD_MS);

    (void)argument;
    if (period_ticks == 0U) {
        /* Tick 周期过小时至少休眠一个 Tick，避免任务持续占用 CPU。 */
        period_ticks = 1U;
    }

    for (;;) {
        MatrixKeypadEvent event;

        /* Module 完成行列扫描和防抖；只有状态变化才发布事件。 */
        if (MatrixKeypadProcess(matrix_keypad_input_device,
                APP_MATRIX_KEYPAD_SCAN_PERIOD_MS, &event)) {
            matrix_keypad_input_stable_keys = event.held_keys;
            ++matrix_keypad_input_scan_count;

            if ((event.pressed_keys != 0U) ||
                (event.released_keys != 0U)) {
                /* 非阻塞写入队列，保证下一次扫描不会被慢速消费者拖住。 */
                MatrixKeypadInputPublishEvent(&event);
#if APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT != 0U
                if (event.pressed_keys != 0U) {
                    MatrixKeypadInputSendPressedKeysUART3(
                        event.pressed_keys);
                }
#endif
            }
        } else {
            ++matrix_keypad_input_scan_error_count;
        }

        /* 按绝对时间唤醒，长时间运行时仍保持稳定的扫描频率。 */
        vTaskDelayUntil(&next_wake_time, period_ticks);
    }
}

/* 队列满时丢弃最旧事件并保存最新状态，避免消费者长期落后。 */
static void MatrixKeypadInputPublishEvent(
    const MatrixKeypadEvent *event)
{
    MatrixKeypadEvent discarded_event;

    if ((event == NULL) || (matrix_keypad_input_event_queue == NULL)) {
        return;
    }

    if (xQueueSend(matrix_keypad_input_event_queue, event, 0U) == pdPASS) {
        return;
    }

    if (xQueueReceive(matrix_keypad_input_event_queue,
            &discarded_event, 0U) == pdPASS) {
        ++matrix_keypad_input_dropped_event_count;
    }
    if (xQueueSend(matrix_keypad_input_event_queue, event, 0U) != pdPASS) {
        ++matrix_keypad_input_dropped_event_count;
    }
}

#if APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT != 0U
/* 每个新按下键独立发送一个两字节 NUL 结尾字符串。 */
static void MatrixKeypadInputSendPressedKeysUART3(uint16_t pressed_keys)
{
    uint32_t key_index;

    for (key_index = 0U; key_index < MATRIX_KEYPAD_KEY_COUNT;
         ++key_index) {
        uint16_t key_mask = (uint16_t)(1UL << key_index);
        char key_character;
        uint8_t message[2];

        if ((pressed_keys & key_mask) == 0U) {
            continue;
        }
        key_character = MatrixKeypadKeyToChar(
            (MatrixKeypadKey_e)key_index);
        if (key_character == '\0') {
            continue;
        }
        message[0] = (uint8_t)key_character;
        message[1] = 0U;
        (void)SerialCommunicationUART3Send(message, sizeof(message));
    }
}
#endif
#endif
