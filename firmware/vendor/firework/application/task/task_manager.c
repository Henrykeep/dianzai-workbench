/*
 * Task Manager 集中保存 Application 任务的静态 TCB、栈和创建状态。
 * 这样可以在不依赖堆的情况下统一控制资源占用，也能集中查看栈余量。
 */
#include "application/task/task_manager.h"

#include <stddef.h>
#include <stdint.h>

#include "application/app_config.h"

/*
 * Application 任务的优先级和栈深度统一在此处调整。
 * 优先级以空闲任务优先级为基准；栈深度单位是 StackType_t 元素而不是字节。
 * 当前 Cortex-M0+ 端口中 StackType_t 为 uint32_t，即每个元素占 4 字节。
 */
#define APPLICATION_TASK_SERIAL_RX_PRIORITY \
    (tskIDLE_PRIORITY + 2U)
#define APPLICATION_TASK_SERIAL_RX_STACK_SIZE \
    (configMINIMAL_STACK_SIZE)

#define APPLICATION_TASK_ADC_JUSTFLOAT_PRIORITY \
    (tskIDLE_PRIORITY + 1U)
#define APPLICATION_TASK_ADC_JUSTFLOAT_STACK_SIZE \
    (configMINIMAL_STACK_SIZE + 64U)

#define APPLICATION_TASK_SERVO_CONTROL_PRIORITY \
    (tskIDLE_PRIORITY + 2U)
#define APPLICATION_TASK_SERVO_CONTROL_STACK_SIZE \
    (configMINIMAL_STACK_SIZE + 64U)

#define APPLICATION_TASK_TB6612_CONTROL_PRIORITY \
    (tskIDLE_PRIORITY + 2U)
#define APPLICATION_TASK_TB6612_CONTROL_STACK_SIZE \
    (configMINIMAL_STACK_SIZE + 64U)

#define APPLICATION_TASK_MATRIX_KEYPAD_PRIORITY \
    (tskIDLE_PRIORITY + 2U)
#define APPLICATION_TASK_MATRIX_KEYPAD_STACK_SIZE \
    (configMINIMAL_STACK_SIZE)

#define APPLICATION_TASK_MPU6050_INPUT_PRIORITY \
    (tskIDLE_PRIORITY + 2U)
#define APPLICATION_TASK_MPU6050_INPUT_STACK_SIZE \
    (configMINIMAL_STACK_SIZE + 128U)

/* PA27 触发任务的调度优先级由 Task Manager 统一维护。 */
#define APPLICATION_TASK_PA27_THRESHOLD_TRIGGER_PRIORITY \
    (tskIDLE_PRIORITY + 2U)
/*
 * 触发保存后还会在本任务上下文执行外部样本的 FFT、波形分类和结果发布。
 * 原来的最小扩展栈不足以覆盖 FFT 调用链，栈溢出会进入 SafeState，表现为
 * TFT 白屏；这里与 Waveform Measurement 任务使用同等级的分析栈空间。
 */
#define APPLICATION_TASK_PA27_THRESHOLD_TRIGGER_STACK_SIZE \
    (configMINIMAL_STACK_SIZE + 288U)

#define APPLICATION_TASK_WAVEFORM_MEASUREMENT_PRIORITY \
    (tskIDLE_PRIORITY + 2U)
/* 多峰 FFT 分析期间会嵌套持有 FFTResult 和 FFTAnalysisResult。 */
#define APPLICATION_TASK_WAVEFORM_MEASUREMENT_STACK_SIZE \
    (configMINIMAL_STACK_SIZE + 288U)

#define APPLICATION_TASK_DAC_REFILL_PRIORITY \
    (tskIDLE_PRIORITY + 3U)
/* 回填任务只执行查表和相位累加，不在栈上保存整块波形数据。 */
#define APPLICATION_TASK_DAC_REFILL_STACK_SIZE \
    (configMINIMAL_STACK_SIZE)

#define APPLICATION_TASK_DISPLAY_MENU_PRIORITY \
    (tskIDLE_PRIORITY + 1U)
/* TFT 全屏刷新会经过 Display、TFT、SPI 和 FreeRTOS 互斥锁调用链。 */
#define APPLICATION_TASK_DISPLAY_MENU_STACK_SIZE \
    (configMINIMAL_STACK_SIZE + 192U)
#define APPLICATION_TASK_STACK_FILL_BYTE (0xA5U)

/*
 * 一项配置对应一个 ApplicationTask_e。
 * stack/control 由本文件静态分配，handle 在首次创建成功后保存，用于防止
 * 同一编号重复创建多个任务。
 */
typedef struct {
    /* FreeRTOS 调试器和任务列表中显示的名称。 */
    const char *name;
    /* 静态栈的 StackType_t 元素数量。 */
    uint32_t stack_size;
    UBaseType_t priority;
    /* 任务栈和 TCB 均由调用方提供，创建任务时不使用 FreeRTOS 堆。 */
    StackType_t *stack;
    StaticTask_t *control;
    TaskHandle_t handle;
} ApplicationTaskControl;

/* 关闭的串口不再预留 512 字节任务栈和 104 字节静态 TCB。 */
#if APP_ENABLE_UART1 != 0U
static StaticTask_t uart1_receive_task_control;
static StackType_t uart1_receive_task_stack[
    APPLICATION_TASK_SERIAL_RX_STACK_SIZE];
#endif
#if APP_ENABLE_UART2 != 0U
static StaticTask_t uart2_receive_task_control;
static StackType_t uart2_receive_task_stack[
    APPLICATION_TASK_SERIAL_RX_STACK_SIZE];
#endif
#if APP_ENABLE_UART3 != 0U
static StaticTask_t uart3_receive_task_control;
static StackType_t uart3_receive_task_stack[
    APPLICATION_TASK_SERIAL_RX_STACK_SIZE];
#endif

/* JustFloat 关闭时不分配它的 TCB 和栈，避免占用额外静态 RAM。 */
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
static StaticTask_t adc_justfloat_task_control;
static StackType_t adc_justfloat_task_stack[
    APPLICATION_TASK_ADC_JUSTFLOAT_STACK_SIZE];
#endif

#if APP_ENABLE_SERVO_CONTROL != 0U
static StaticTask_t servo_control_task_control;
static StackType_t servo_control_task_stack[
    APPLICATION_TASK_SERVO_CONTROL_STACK_SIZE];
#endif

#if APP_ENABLE_TB6612_CONTROL != 0U
static StaticTask_t tb6612_control_task_control;
static StackType_t tb6612_control_task_stack[
    APPLICATION_TASK_TB6612_CONTROL_STACK_SIZE];
#endif

#if APP_ENABLE_MATRIX_KEYPAD != 0U
static StaticTask_t matrix_keypad_task_control;
static StackType_t matrix_keypad_task_stack[
    APPLICATION_TASK_MATRIX_KEYPAD_STACK_SIZE];
#endif

#if APP_ENABLE_MPU6050_INPUT != 0U
static StaticTask_t mpu6050_input_task_control;
static StackType_t mpu6050_input_task_stack[
    APPLICATION_TASK_MPU6050_INPUT_STACK_SIZE];
#endif

#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
static StaticTask_t pa27_threshold_trigger_task_control;
static StackType_t pa27_threshold_trigger_task_stack[
    APPLICATION_TASK_PA27_THRESHOLD_TRIGGER_STACK_SIZE];
#endif

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
static StaticTask_t waveform_measurement_task_control;
static StackType_t waveform_measurement_task_stack[
    APPLICATION_TASK_WAVEFORM_MEASUREMENT_STACK_SIZE];
#endif

#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
static StaticTask_t dac_refill_task_control;
static StackType_t dac_refill_task_stack[
    APPLICATION_TASK_DAC_REFILL_STACK_SIZE];
#endif

static StaticTask_t display_menu_task_control;
static StackType_t display_menu_task_stack[
    APPLICATION_TASK_DISPLAY_MENU_STACK_SIZE];

#if APP_ENABLE_TFT_MENU != 0U
#define APPLICATION_TASK_DISPLAY_MENU_NAME "TFTMenu"
#else
#define APPLICATION_TASK_DISPLAY_MENU_NAME "OLEDMenu"
#endif

/*
 * 使用指定下标初始化，确保枚举编号和任务资源一一对应。
 * 条件编译关闭的任务项保持全零，误调用时会由配置完整性检查拒绝。
 */
static ApplicationTaskControl application_tasks[APPLICATION_TASK_COUNT] = {
#if APP_ENABLE_UART1 != 0U
    [APPLICATION_TASK_SERIAL_UART1_RX] = {
        "UART1Rx", APPLICATION_TASK_SERIAL_RX_STACK_SIZE,
        APPLICATION_TASK_SERIAL_RX_PRIORITY, uart1_receive_task_stack,
        &uart1_receive_task_control, NULL
    },
#endif
#if APP_ENABLE_UART2 != 0U
    [APPLICATION_TASK_SERIAL_UART2_RX] = {
        "UART2Rx", APPLICATION_TASK_SERIAL_RX_STACK_SIZE,
        APPLICATION_TASK_SERIAL_RX_PRIORITY, uart2_receive_task_stack,
        &uart2_receive_task_control, NULL
    },
#endif
#if APP_ENABLE_UART3 != 0U
    [APPLICATION_TASK_SERIAL_UART3_RX] = {
        "UART3Rx", APPLICATION_TASK_SERIAL_RX_STACK_SIZE,
        APPLICATION_TASK_SERIAL_RX_PRIORITY, uart3_receive_task_stack,
        &uart3_receive_task_control, NULL
    },
#endif
#if APP_ENABLE_ADC_JUSTFLOAT != 0U
    [APPLICATION_TASK_ADC_JUSTFLOAT] = {
        "ADC2Vofa", APPLICATION_TASK_ADC_JUSTFLOAT_STACK_SIZE,
        APPLICATION_TASK_ADC_JUSTFLOAT_PRIORITY, adc_justfloat_task_stack,
        &adc_justfloat_task_control, NULL
    },
#endif
#if APP_ENABLE_SERVO_CONTROL != 0U
    [APPLICATION_TASK_SERVO_CONTROL] = {
        "ServoControl", APPLICATION_TASK_SERVO_CONTROL_STACK_SIZE,
        APPLICATION_TASK_SERVO_CONTROL_PRIORITY,
        servo_control_task_stack, &servo_control_task_control, NULL
    },
#endif
#if APP_ENABLE_TB6612_CONTROL != 0U
    [APPLICATION_TASK_MOTOR_CONTROL] = {
        "MotorControl", APPLICATION_TASK_TB6612_CONTROL_STACK_SIZE,
        APPLICATION_TASK_TB6612_CONTROL_PRIORITY,
        tb6612_control_task_stack, &tb6612_control_task_control, NULL
    },
#endif
#if APP_ENABLE_MATRIX_KEYPAD != 0U
    [APPLICATION_TASK_MATRIX_KEYPAD] = {
        "MatrixKeypad", APPLICATION_TASK_MATRIX_KEYPAD_STACK_SIZE,
        APPLICATION_TASK_MATRIX_KEYPAD_PRIORITY,
        matrix_keypad_task_stack, &matrix_keypad_task_control, NULL
    },
#endif
#if APP_ENABLE_MPU6050_INPUT != 0U
    [APPLICATION_TASK_MPU6050_INPUT] = {
        "MPU6050Input", APPLICATION_TASK_MPU6050_INPUT_STACK_SIZE,
        APPLICATION_TASK_MPU6050_INPUT_PRIORITY,
        mpu6050_input_task_stack, &mpu6050_input_task_control, NULL
    },
#endif
#if APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U
    [APPLICATION_TASK_PA27_THRESHOLD_TRIGGER] = {
        "PA27Trigger", APPLICATION_TASK_PA27_THRESHOLD_TRIGGER_STACK_SIZE,
        APPLICATION_TASK_PA27_THRESHOLD_TRIGGER_PRIORITY,
        pa27_threshold_trigger_task_stack,
        &pa27_threshold_trigger_task_control, NULL
    },
#endif
#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U
    [APPLICATION_TASK_WAVEFORM_MEASUREMENT] = {
        "WaveMeasure", APPLICATION_TASK_WAVEFORM_MEASUREMENT_STACK_SIZE,
        APPLICATION_TASK_WAVEFORM_MEASUREMENT_PRIORITY,
        waveform_measurement_task_stack,
        &waveform_measurement_task_control, NULL
    },
#endif
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
    [APPLICATION_TASK_DAC_REFILL] = {
        "DACRefill", APPLICATION_TASK_DAC_REFILL_STACK_SIZE,
        APPLICATION_TASK_DAC_REFILL_PRIORITY,
        dac_refill_task_stack, &dac_refill_task_control, NULL
    },
#endif
    [APPLICATION_TASK_DISPLAY_MENU] = {
        APPLICATION_TASK_DISPLAY_MENU_NAME,
        APPLICATION_TASK_DISPLAY_MENU_STACK_SIZE,
        APPLICATION_TASK_DISPLAY_MENU_PRIORITY,
        display_menu_task_stack, &display_menu_task_control, NULL
    }
};

TaskHandle_t ApplicationTaskCreate(ApplicationTask_e task,
    TaskFunction_t task_function, void *argument)
{
    ApplicationTaskControl *task_control;

    /* 先检查任务编号和入口函数，避免访问配置表越界。 */
    if ((task < APPLICATION_TASK_SERIAL_UART1_RX) ||
        (task >= APPLICATION_TASK_COUNT) || (task_function == NULL)) {
        return NULL;
    }

    task_control = &application_tasks[task];

    /* 初始化函数可能被重复调用；已有任务直接复用原句柄。 */
    if (task_control->handle != NULL) {
        return task_control->handle;
    }

    /* 条件编译关闭或配置遗漏时，配置项会包含 NULL/0，禁止继续创建。 */
    if ((task_control->name == NULL) || (task_control->stack == NULL) ||
        (task_control->control == NULL) ||
        (task_control->stack_size == 0U)) {
        return NULL;
    }

    /*
     * 所有 Application 任务统一采用静态创建；返回 NULL 表示 FreeRTOS 拒绝
     * 了本次创建，handle 保持 NULL，调用方可进入初始化失败处理。
     */
    task_control->handle = xTaskCreateStatic(task_function,
        task_control->name, task_control->stack_size, argument,
        task_control->priority, task_control->stack,
        task_control->control);
    return task_control->handle;
}

TaskHandle_t ApplicationTaskGetHandle(ApplicationTask_e task)
{
    /* 查询接口同样执行边界检查，但不会检查任务是否已创建。 */
    if ((task < APPLICATION_TASK_SERIAL_UART1_RX) ||
        (task >= APPLICATION_TASK_COUNT)) {
        return NULL;
    }
    return application_tasks[task].handle;
}

uint32_t ApplicationTaskGetMinimumFreeStackWords(ApplicationTask_e task)
{
    const ApplicationTaskControl *task_control;
    const uint8_t *stack_bytes;
    size_t free_bytes = 0U;
    size_t stack_byte_count;

    if ((task < APPLICATION_TASK_SERIAL_UART1_RX) ||
        (task >= APPLICATION_TASK_COUNT)) {
        return 0U;
    }
    task_control = &application_tasks[task];
    if ((task_control->handle == NULL) ||
        (task_control->stack == NULL) ||
        (task_control->stack_size == 0U)) {
        return 0U;
    }

    /*
     * 当前 Cortex-M0+ 栈从高地址向低地址增长。FreeRTOS 创建任务时用
     * 0xA5 填满静态栈，因此从低地址连续保留的 0xA5 就是历史最小余量。
     * 加入总长度边界，避免在异常情况下读出静态栈数组。
     */
    stack_bytes = (const uint8_t *)task_control->stack;
    stack_byte_count =
        (size_t)task_control->stack_size * sizeof(StackType_t);
    while ((free_bytes < stack_byte_count) &&
           (stack_bytes[free_bytes] == APPLICATION_TASK_STACK_FILL_BYTE)) {
        ++free_bytes;
    }
    return (uint32_t)(free_bytes / sizeof(StackType_t));
}
