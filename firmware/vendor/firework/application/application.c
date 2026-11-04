/*
 * Application 总装配入口：在 FreeRTOS 调度器启动前按依赖顺序初始化各模块，
 * 并在任一环节失败时记录阶段、关闭可能已经打开的输出。
 */
#include "application/application.h"

#include <stddef.h>
#include <stdint.h>

#include "FreeRTOS.h"
#include "task.h"

#include "application/app_config.h"
#if APP_ENABLE_OLED_MENU != 0U
#include "application/menu/oled_menu/oled_menu.h"
#elif APP_ENABLE_TFT_MENU != 0U
#include "application/menu/tft_menu/tft_menu.h"
#endif
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
#include "modules/pwm/pwm_output.h"
#endif
#if APP_ENABLE_SERVO_CONTROL != 0U
#include "application/control/servo_control/servo_control.h"
#endif
#if APP_ENABLE_TB6612_CONTROL != 0U
#include "application/control/motor_control/motor_control.h"
#endif
#if APP_ENABLE_MATRIX_KEYPAD != 0U
#include "application/input/matrix_keypad_input/matrix_keypad_input.h"
#endif
#if APP_ENABLE_MPU6050_INPUT != 0U
#include "application/input/mpu6050_input/mpu6050_input.h"
#endif
#include "application/communication/serial_communication/serial_communication.h"
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
#include "application/communication/serial_communication/adc_justfloat.h"
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
#include "application/waveform/waveform_measurement/waveform_measurement.h"
#endif
#if APP_ENABLE_WAVEFORM_MAPPING != 0U
#include "application/waveform/waveform_mapping/waveform_mapping.h"
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT != 0U
#include "application/waveform/waveform_output/waveform_output.h"
#endif
#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U
#include "application/waveform/arbitrary_waveform/arbitrary_waveform.h"
#endif
#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
#include "application/waveform/pa27_threshold_trigger/pa27_threshold_trigger.h"
#endif
#include "bsp/bsp.h"

static void ApplicationDebugSend(const uint8_t *data, size_t size);

/* 总装配只允许从未初始化进入一次初始化流程，失败后不得局部重复启动。 */
typedef enum {
    APPLICATION_INIT_STATE_UNINITIALIZED = 0,
    APPLICATION_INIT_STATE_INITIALIZING,
    APPLICATION_INIT_STATE_READY,
    APPLICATION_INIT_STATE_FAILED
} ApplicationInitState_e;

/* 最近失败阶段与整体状态在调度器启动前写入，运行期仅供诊断读取。 */
static ApplicationInitState_e application_init_state;
static ApplicationStage_e application_last_error_stage =
    APPLICATION_STAGE_NONE;

Framework_Status_e ApplicationInit(void)
{
    static const uint8_t init_message[] = "APPLICATION INIT\r\n";
    static const uint8_t serial_error_message[] =
        "APPLICATION SERIAL ERROR\r\n";
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
    static const uint8_t adc_justfloat_error_message[] =
        "APPLICATION ADC JUSTFLOAT ERROR\r\n";
    static const uint8_t adc_justfloat_ready_message[] =
        "ADC UART2 JUSTFLOAT READY\r\n";
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    static const uint8_t waveform_measurement_error_message[] =
        "APPLICATION WAVEFORM MEASUREMENT ERROR\r\n";
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT != 0U
    static const uint8_t waveform_output_error_message[] =
        "APPLICATION WAVEFORM OUTPUT ERROR\r\n";
#endif
#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U
    static const uint8_t arbitrary_waveform_error_message[] =
        "APPLICATION ARBITRARY WAVEFORM ERROR\r\n";
#endif
#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
    static const uint8_t pa27_trigger_error_message[] =
        "APPLICATION PA27 TRIGGER ERROR\r\n";
#endif
#if APP_ENABLE_WAVEFORM_MAPPING != 0U
    static const uint8_t waveform_mapping_error_message[] =
        "APPLICATION WAVEFORM MAPPING ERROR\r\n";
#endif
#if APP_ENABLE_SERVO_CONTROL != 0U
    static const uint8_t servo_control_error_message[] =
        "APPLICATION SERVO CONTROL ERROR\r\n";
#endif
#if APP_ENABLE_TB6612_CONTROL != 0U
    static const uint8_t tb6612_control_error_message[] =
        "APPLICATION TB6612 CONTROL ERROR\r\n";
#endif
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    static const uint8_t matrix_keypad_error_message[] =
        "APPLICATION MATRIX KEYPAD ERROR\r\n";
#endif
#if APP_ENABLE_MPU6050_INPUT != 0U
    static const uint8_t mpu6050_input_error_message[] =
        "APPLICATION MPU6050 INPUT ERROR\r\n";
#endif
#if (APP_ENABLE_OLED_MENU != 0U) || (APP_ENABLE_TFT_MENU != 0U)
    static const uint8_t menu_error_message[] =
        "APPLICATION DISPLAY MENU ERROR\r\n";
#endif
    static const uint8_t ready_message[] = "APPLICATION READY\r\n";

    if (application_init_state == APPLICATION_INIT_STATE_READY) {
        return FRAMEWORK_STATUS_OK;
    }
    if (application_init_state != APPLICATION_INIT_STATE_UNINITIALIZED) {
        return FRAMEWORK_STATUS_ERROR;
    }
    application_init_state = APPLICATION_INIT_STATE_INITIALIZING;
    application_last_error_stage = APPLICATION_STAGE_BSP;

    /* BSP 必须最先初始化，后续模块会依赖已配置好的时钟和外设。 */
    if (!BSPInit()) {
        goto initialization_failed;
    }

    /* 先完成各串口注册并创建独立接收任务。 */
    application_last_error_stage = APPLICATION_STAGE_SERIAL;
    if (!SerialCommunicationInit()) {
        ApplicationDebugSend(
            serial_error_message, sizeof(serial_error_message) - 1U);
        goto initialization_failed;
    }
    ApplicationDebugSend(init_message, sizeof(init_message) - 1U);

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    /* 准备 ADC、FFT、COMP 和任务；PA27/PB19 由菜单按次启动。 */
    application_last_error_stage =
        APPLICATION_STAGE_WAVEFORM_MEASUREMENT;
    if (!WaveformMeasurementInit()) {
        ApplicationDebugSend(waveform_measurement_error_message,
            sizeof(waveform_measurement_error_message) - 1U);
        goto initialization_failed;
    }
#endif
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
    /* 订阅完整测量结果，并创建 UART2 最后 128 点 JustFloat 发送任务。 */
    application_last_error_stage = APPLICATION_STAGE_ADC_JUSTFLOAT;
    if (!ADCJustFloatInit()) {
        ApplicationDebugSend(adc_justfloat_error_message,
            sizeof(adc_justfloat_error_message) - 1U);
        goto initialization_failed;
    }
    ApplicationDebugSend(adc_justfloat_ready_message,
        sizeof(adc_justfloat_ready_message) - 1U);
#endif

#if APP_ENABLE_WAVEFORM_OUTPUT != 0U
    /* 统一初始化当前工程启用的 DAC 和 DDS 输出后端。 */
    application_last_error_stage = APPLICATION_STAGE_WAVEFORM_OUTPUT;
    if (!WaveformOutputInit()) {
        ApplicationDebugSend(waveform_output_error_message,
            sizeof(waveform_output_error_message) - 1U);
        goto initialization_failed;
    }
#endif

#if APP_ENABLE_ARBITRARY_WAVEFORM != 0U
    /* 扫描 Flash 波形槽位；播放时由 DAC 固定速率双缓冲流式输出。 */
    application_last_error_stage = APPLICATION_STAGE_ARBITRARY_WAVEFORM;
    if (!ArbitraryWaveformInit()) {
        ApplicationDebugSend(arbitrary_waveform_error_message,
            sizeof(arbitrary_waveform_error_message) - 1U);
        goto initialization_failed;
    }
#endif

#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
    /* 创建 PA27 阈值触发任务；默认等待显式 Arm，不自动占用 ADC。 */
    application_last_error_stage =
        APPLICATION_STAGE_PA27_THRESHOLD_TRIGGER;
    if (!PA27ThresholdTriggerInit()) {
        ApplicationDebugSend(pa27_trigger_error_message,
            sizeof(pa27_trigger_error_message) - 1U);
        goto initialization_failed;
    }
#endif

#if APP_ENABLE_WAVEFORM_MAPPING != 0U
    /* 订阅 PA27 单次测量结果，并映射到编译配置选择的输出后端。 */
    application_last_error_stage = APPLICATION_STAGE_WAVEFORM_MAPPING;
    if (!WaveformMappingInit()) {
        ApplicationDebugSend(waveform_mapping_error_message,
            sizeof(waveform_mapping_error_message) - 1U);
        goto initialization_failed;
    }
#endif

#if APP_ENABLE_SERVO_CONTROL != 0U
    /* 注册 PA23/PA24 双路舵机并创建任务，初始状态由启动标志控制。 */
    application_last_error_stage = APPLICATION_STAGE_SERVO_CONTROL;
    if (!ServoControlInit()) {
        ApplicationDebugSend(servo_control_error_message,
            sizeof(servo_control_error_message) - 1U);
        goto initialization_failed;
    }
#endif

#if APP_ENABLE_TB6612_CONTROL != 0U
    /* 注册独立 TIMA1 双路 PWM 和方向引脚；上电保持 STBY 低电平。 */
    application_last_error_stage = APPLICATION_STAGE_TB6612_CONTROL;
    if (!TB6612ControlInit()) {
        ApplicationDebugSend(tb6612_control_error_message,
            sizeof(tb6612_control_error_message) - 1U);
        goto initialization_failed;
    }
#endif

#if APP_ENABLE_MATRIX_KEYPAD != 0U
    /* 注册 4×4 矩阵键盘，并创建固定周期扫描和事件发布任务。 */
    application_last_error_stage = APPLICATION_STAGE_MATRIX_KEYPAD;
    if (!MatrixKeypadInputInit()) {
        ApplicationDebugSend(matrix_keypad_error_message,
            sizeof(matrix_keypad_error_message) - 1U);
        goto initialization_failed;
    }
#endif

#if APP_ENABLE_MPU6050_INPUT != 0U
    /* 注册并创建读取任务；传感器探测失败由任务后台重试，不阻塞系统启动。 */
    application_last_error_stage = APPLICATION_STAGE_MPU6050_INPUT;
    if (!MPU6050InputInit()) {
        ApplicationDebugSend(mpu6050_input_error_message,
            sizeof(mpu6050_input_error_message) - 1U);
        goto initialization_failed;
    }
#endif

#if APP_ENABLE_OLED_MENU != 0U
    /* 初始化 OLED 显示后端，并启动共用的菜单和按键任务。 */
    application_last_error_stage = APPLICATION_STAGE_DISPLAY_MENU;
    if (!OLEDMenuInit()) {
        ApplicationDebugSend(
            menu_error_message, sizeof(menu_error_message) - 1U);
        goto initialization_failed;
    }
#elif APP_ENABLE_TFT_MENU != 0U
    /* 初始化 ST7735S TFT 后端，复用 OLED 的页面和按键操作。 */
    application_last_error_stage = APPLICATION_STAGE_DISPLAY_MENU;
    if (!TFTMenuInit()) {
        ApplicationDebugSend(
            menu_error_message, sizeof(menu_error_message) - 1U);
        goto initialization_failed;
    }
#endif

    application_init_state = APPLICATION_INIT_STATE_READY;
    application_last_error_stage = APPLICATION_STAGE_NONE;
    ApplicationDebugSend(ready_message, sizeof(ready_message) - 1U);
    return FRAMEWORK_STATUS_OK;

initialization_failed:
    ApplicationEnterSafeState();
    application_init_state = APPLICATION_INIT_STATE_FAILED;
    return FRAMEWORK_STATUS_ERROR;
}

void ApplicationStart(void)
{
    static const uint8_t start_message[] = "APPLICATION START\r\n";

    ApplicationDebugSend(start_message, sizeof(start_message) - 1U);

    /* 所有任务创建完成后统一启动调度器。 */
    vTaskStartScheduler();

    application_last_error_stage = APPLICATION_STAGE_SCHEDULER;
    application_init_state = APPLICATION_INIT_STATE_FAILED;
    ApplicationEnterSafeState();
}

ApplicationStage_e ApplicationGetLastErrorStage(void)
{
    return application_last_error_stage;
}

bool ApplicationIsReady(void)
{
    return application_init_state == APPLICATION_INIT_STATE_READY;
}

/* 根据框架调试开关决定是否通过 UART0 输出提示信息。 */
static void ApplicationDebugSend(const uint8_t *data, size_t size)
{
    if (APP_ENABLE_UART0_DEBUG != 0U) {
        (void)SerialCommunicationUART0Send(data, size);
    }
}

void ApplicationEnterSafeState(void)
{
    /* 先关闭各 Application 输出，最后由 BSP 把剩余外设恢复到安全电平。 */
#if APP_ENABLE_WAVEFORM_OUTPUT != 0U
    (void)WaveformOutputStopAll();
#endif
#if APP_ENABLE_SERVO_CONTROL != 0U
    ServoControlEnterSafeState();
#endif
#if APP_ENABLE_TB6612_CONTROL != 0U
    TB6612ControlEnterSafeState();
#endif
#if APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U
    (void)PWMOutputStop();
#endif
    BSPEnterSafeState();
}
