/*
 * 模拟捕获 BSP 把比较器边沿送入定时器，生成供上层读取的周期和边沿序号快照。
 */
#include "bsp/capture/bsp_capture.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_MEASUREMENT != 0U

#include <stddef.h>

#include "bsp/board_config.h"
#include "ti_msp_dl_config.h"

#define BSP_CAPTURE_DAC_MAXIMUM_CODE (255U)

#if (ANALOG_CAPTURE_TIMER_0_INST_LOAD_VALUE + 1UL) != \
    (BSP_BOARD_CAPTURE_PA27_TIMER_CLOCK_HZ * \
        BSP_BOARD_CAPTURE_PA27_TIMER_PERIOD_SECONDS)
#error "PA27 capture timer does not match bsp/board_config.h"
#endif

#if (ANALOG_CAPTURE_TIMER_1_INST_LOAD_VALUE + 1UL) != \
    (BSP_BOARD_CAPTURE_PA21_TIMER_CLOCK_HZ * \
        BSP_BOARD_CAPTURE_PA21_TIMER_PERIOD_SECONDS)
#error "PA21 capture timer does not match bsp/board_config.h"
#endif

struct BSPCaptureInstance {
    BSP_Capture_Device_e device;
    COMP_Regs *comparator;
    GPTIMER_Regs *timer;
    uint32_t timer_load_value;
    uint32_t timer_clock_hz;
    IRQn_Type timer_irqn;
    volatile uint32_t previous_capture;
    volatile uint32_t period_ticks;
    volatile uint32_t edge_count;
    volatile uint32_t sequence;
    volatile bool previous_capture_valid;
    volatile bool measurement_ready;
    volatile bool running;
    uint16_t threshold_millivolts;
    bool registered;
};

static BSPCaptureInstance capture_instances[BSP_CAPTURE_DEVICE_COUNT];

static bool BSPCaptureIsValid(const BSPCaptureInstance *instance);
static uint8_t BSPCaptureConvertThresholdToDACCode(
    uint16_t threshold_millivolts);
static uint32_t BSPCaptureCalculatePeriodTicks(
    const BSPCaptureInstance *instance,
    uint32_t previous_capture, uint32_t current_capture);
static bool BSPCaptureHandleEdge(BSPCaptureInstance *instance);
static uint32_t BSPCaptureLockInterrupts(void);
static void BSPCaptureUnlockInterrupts(uint32_t interrupt_state);

/* 将两路统一输入映射到各自的 COMP 和捕获定时器。 */
BSPCaptureInstance *BSPCaptureRegister(BSP_Capture_Device_e device)
{
    BSPCaptureInstance *instance;

    if ((device < BSP_CAPTURE_DEVICE_ANALOG_INPUT_0) ||
        (device >= BSP_CAPTURE_DEVICE_COUNT)) {
        return NULL;
    }

    instance = &capture_instances[device];
    if (instance->registered) {
        return instance;
    }

    switch (device) {
        case BSP_CAPTURE_DEVICE_ANALOG_INPUT_0:
            instance->comparator = ANALOG_CAPTURE_COMP_0_INST;
            instance->timer      = ANALOG_CAPTURE_TIMER_0_INST;
            instance->timer_load_value =
                ANALOG_CAPTURE_TIMER_0_INST_LOAD_VALUE;
            instance->timer_clock_hz =
                BSP_BOARD_CAPTURE_PA27_TIMER_CLOCK_HZ;
            instance->timer_irqn =
                ANALOG_CAPTURE_TIMER_0_INST_INT_IRQN;
            break;

        case BSP_CAPTURE_DEVICE_ANALOG_INPUT_1:
            instance->comparator = ANALOG_CAPTURE_COMP_1_INST;
            instance->timer      = ANALOG_CAPTURE_TIMER_1_INST;
            instance->timer_load_value =
                ANALOG_CAPTURE_TIMER_1_INST_LOAD_VALUE;
            instance->timer_clock_hz =
                BSP_BOARD_CAPTURE_PA21_TIMER_CLOCK_HZ;
            instance->timer_irqn =
                ANALOG_CAPTURE_TIMER_1_INST_INT_IRQN;
            break;

        default:
            return NULL;
    }
    instance->device = device;
    instance->registered = (instance->comparator != NULL) &&
                           (instance->timer != NULL);
    return instance->registered ? instance : NULL;
}

/* 清空首次边沿状态后启动硬件捕获链路。 */
bool BSPCaptureStart(BSPCaptureInstance *instance)
{
    uint32_t interrupt_state;

    if (!BSPCaptureIsValid(instance)) {
        return false;
    }
    interrupt_state = BSPCaptureLockInterrupts();
    DL_TimerG_stopCounter(instance->timer);
    DL_COMP_disable(instance->comparator);
    DL_TimerG_clearInterruptStatus(instance->timer,
        DL_TIMERG_INTERRUPT_CC0_DN_EVENT);
    DL_TimerG_setTimerCount(
        instance->timer, instance->timer_load_value);

    instance->previous_capture       = 0UL;
    instance->period_ticks           = 0UL;
    instance->edge_count             = 0UL;
    /* sequence 跨 Stop/Start 保持单调，避免重复序号被当成旧结果。 */
    instance->previous_capture_valid = false;
    instance->measurement_ready      = false;
    instance->running                = true;

    DL_COMP_setDACCode0(instance->comparator,
        BSPCaptureConvertThresholdToDACCode(
            instance->threshold_millivolts));
    NVIC_ClearPendingIRQ(instance->timer_irqn);
    NVIC_EnableIRQ(instance->timer_irqn);
    DL_TimerG_startCounter(instance->timer);
    /* 先让时间基准运行，再放开比较器，避免启用瞬间形成伪时间戳。 */
    DL_COMP_enable(instance->comparator);
    BSPCaptureUnlockInterrupts(interrupt_state);
    return true;
}

/* 停止硬件并保留最近一次完整周期结果供应用读取。 */
bool BSPCaptureStop(BSPCaptureInstance *instance)
{
    uint32_t interrupt_state;

    if (!BSPCaptureIsValid(instance)) {
        return false;
    }

    NVIC_DisableIRQ(instance->timer_irqn);
    interrupt_state = BSPCaptureLockInterrupts();
    DL_TimerG_stopCounter(instance->timer);
    DL_COMP_disable(instance->comparator);
    DL_TimerG_clearInterruptStatus(instance->timer,
        DL_TIMERG_INTERRUPT_CC0_DN_EVENT);
    instance->running = false;
    BSPCaptureUnlockInterrupts(interrupt_state);
    NVIC_ClearPendingIRQ(instance->timer_irqn);
    return true;
}

/* 将毫伏阈值换算为内部 8 位 DAC 码并立即更新。 */
bool BSPCaptureSetThresholdMillivolts(
    BSPCaptureInstance *instance, uint16_t threshold_millivolts)
{
    uint32_t interrupt_state;

    if (!BSPCaptureIsValid(instance) ||
        (threshold_millivolts > BSP_CAPTURE_REFERENCE_MILLIVOLTS)) {
        return false;
    }

    interrupt_state = BSPCaptureLockInterrupts();
    instance->threshold_millivolts = threshold_millivolts;
    DL_COMP_setDACCode0(instance->comparator,
        BSPCaptureConvertThresholdToDACCode(threshold_millivolts));
    /* 阈值改变后丢弃跨越两个阈值配置形成的不完整周期。 */
    instance->previous_capture_valid = false;
    instance->measurement_ready      = false;
    BSPCaptureUnlockInterrupts(interrupt_state);
    return true;
}

uint16_t BSPCaptureGetThresholdMillivolts(
    const BSPCaptureInstance *instance)
{
    return BSPCaptureIsValid(instance)
               ? instance->threshold_millivolts
               : 0U;
}

/* 在关闭中断的短临界区内取得一致的 ISR 结果快照。 */
bool BSPCaptureReadMeasurement(BSPCaptureInstance *instance,
    BSPCaptureMeasurement *measurement)
{
    uint32_t interrupt_state;

    if (!BSPCaptureIsValid(instance) || (measurement == NULL)) {
        return false;
    }

    interrupt_state = BSPCaptureLockInterrupts();
    if (!instance->measurement_ready) {
        BSPCaptureUnlockInterrupts(interrupt_state);
        return false;
    }

    measurement->period_ticks = instance->period_ticks;
    measurement->edge_count   = instance->edge_count;
    measurement->sequence     = instance->sequence;
    BSPCaptureUnlockInterrupts(interrupt_state);
    return true;
}

bool BSPCaptureIsRunning(const BSPCaptureInstance *instance)
{
    return BSPCaptureIsValid(instance) && instance->running;
}

uint32_t BSPCaptureGetTimerClockHz(
    const BSPCaptureInstance *instance)
{
    return BSPCaptureIsValid(instance)
               ? instance->timer_clock_hz
               : 0UL;
}

static bool BSPCaptureIsValid(const BSPCaptureInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->device >= BSP_CAPTURE_DEVICE_ANALOG_INPUT_0) &&
           (instance->device < BSP_CAPTURE_DEVICE_COUNT) &&
           (instance->comparator != NULL) && (instance->timer != NULL) &&
           (instance->timer_load_value > 0UL) &&
           (instance->timer_clock_hz > 0UL);
}

/* 使用四舍五入把 0～3300 mV 映射到 0～255。 */
static uint8_t BSPCaptureConvertThresholdToDACCode(
    uint16_t threshold_millivolts)
{
    uint32_t scaled =
        ((uint32_t)threshold_millivolts *
            BSP_CAPTURE_DAC_MAXIMUM_CODE) +
        (BSP_CAPTURE_REFERENCE_MILLIVOLTS / 2U);

    return (uint8_t)(scaled / BSP_CAPTURE_REFERENCE_MILLIVOLTS);
}

/* TIMG12 向下计数，计算相邻捕获值并处理一次计数器回卷。 */
static uint32_t BSPCaptureCalculatePeriodTicks(
    const BSPCaptureInstance *instance,
    uint32_t previous_capture, uint32_t current_capture)
{
    if (instance == NULL) {
        return 0UL;
    }
    if (previous_capture >= current_capture) {
        return previous_capture - current_capture;
    }

    return (uint32_t)((uint64_t)previous_capture +
        ((uint64_t)instance->timer_load_value + 1ULL) -
        current_capture);
}

/*
 * 保存比较器上升沿时间戳。收到第二个有效边沿后已经得到
 * 一个完整周期，返回 true，由 ISR 立即屏蔽本次 Capture 中断。
 */
static bool BSPCaptureHandleEdge(BSPCaptureInstance *instance)
{
    uint32_t current_capture;
    uint32_t period_ticks;
    bool measurement_complete = false;

    if (!BSPCaptureIsValid(instance) || !instance->running) {
        return false;
    }

    current_capture = DL_Timer_getCaptureCompareValue(
        instance->timer, DL_TIMER_CC_0_INDEX);
    ++instance->edge_count;

    if (instance->previous_capture_valid) {
        period_ticks = BSPCaptureCalculatePeriodTicks(
            instance, instance->previous_capture, current_capture);
        if (period_ticks > 0UL) {
            instance->period_ticks      = period_ticks;
            instance->measurement_ready = true;
            ++instance->sequence;
            measurement_complete = true;
        }
    }

    instance->previous_capture       = current_capture;
    instance->previous_capture_valid = true;
    return measurement_complete;
}

static uint32_t BSPCaptureLockInterrupts(void)
{
    uint32_t interrupt_state = __get_PRIMASK();

    __disable_irq();
    return interrupt_state;
}

static void BSPCaptureUnlockInterrupts(uint32_t interrupt_state)
{
    if (interrupt_state == 0U) {
        __enable_irq();
    }
}

/* PA27/COMP0 事件通过 Event Fabric 通道 2 到达 TIMG12 CC0。 */
void ANALOG_CAPTURE_TIMER_0_INST_IRQHandler(void)
{
    DL_TIMER_IIDX interrupt_index;

    do {
        interrupt_index =
            DL_TimerG_getPendingInterrupt(ANALOG_CAPTURE_TIMER_0_INST);
        if (interrupt_index == DL_TIMERG_IIDX_CC0_DN) {
            BSPCaptureInstance *instance =
                &capture_instances[BSP_CAPTURE_DEVICE_ANALOG_INPUT_0];

            if (BSPCaptureHandleEdge(instance)) {
                /* 单次测量只需要两个上升沿，避免高频中断风暴。 */
                NVIC_DisableIRQ(instance->timer_irqn);
                break;
            }
        }
    } while ((uint32_t)interrupt_index != 0UL);
}

/* PA21/COMP2 事件通过 Event Fabric 通道 3 到达 TIMG6 CC0。 */
void ANALOG_CAPTURE_TIMER_1_INST_IRQHandler(void)
{
    DL_TIMER_IIDX interrupt_index;

    do {
        interrupt_index =
            DL_TimerG_getPendingInterrupt(ANALOG_CAPTURE_TIMER_1_INST);
        if (interrupt_index == DL_TIMERG_IIDX_CC0_DN) {
            BSPCaptureInstance *instance =
                &capture_instances[BSP_CAPTURE_DEVICE_ANALOG_INPUT_1];

            if (BSPCaptureHandleEdge(instance)) {
                NVIC_DisableIRQ(instance->timer_irqn);
                break;
            }
        }
    } while ((uint32_t)interrupt_index != 0UL);
}

#endif /* APP_ENABLE_WAVEFORM_MEASUREMENT */
