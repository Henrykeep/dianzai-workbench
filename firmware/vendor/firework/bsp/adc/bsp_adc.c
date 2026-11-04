/*
 * ADC BSP 封装 ADC0/ADC1、采样定时器和 DMA，支持直接、阈值触发及双路同步采集。
 * 中断只推进静态状态并回调上层，采集资源在任一模式活动时保持互斥。
 */
#include "bsp/adc/bsp_adc.h"

#include "application/app_config.h"

#include "ti_msp_dl_config.h"

#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
#include "bsp/dac/bsp_dac.h"
#endif

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U)

#include <stddef.h>

#include "FreeRTOS.h"

#include "bsp/board_config.h"

#define BSP_ADC_MAXIMUM_RAW_VALUE    (4095U)
#define BSP_ADC_REFERENCE_MILLIVOLTS (3300U)
#define BSP_ADC_FIFO_DMA_SAMPLE_COUNT (6U)
#define BSP_ADC_RTOS_INTERRUPT_PRIORITY \
    ((uint32_t)configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY)

#if (ADC_SAMPLE_TIMER_INST_LOAD_VALUE + 1UL) == 0UL
#error "ADC sample timer period must be non-zero"
#endif

#if (ADC_SAMPLE_TIMER_INST_LOAD_VALUE + 1UL) != \
    ((BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ / 1000000UL) * \
        BSP_BOARD_ADC_SAMPLE_TIMER_PERIOD_US)
#error "ADC sample timer clock/period does not match bsp/board_config.h"
#endif

typedef enum {
    BSP_ADC_ENGINE_ADC0 = 0,
    BSP_ADC_ENGINE_ADC1,
    BSP_ADC_ENGINE_COUNT
} BSPADCEngineIndex;

typedef struct {
    ADC12_Regs *regs;
    GPTIMER_Regs *sample_timer;
    DL_TIMER_EVENT_ROUTE timer_event_route;
    uint32_t input_channel;
    uint8_t dma_channel;
    uint32_t dma_trigger;
    uint32_t dma_interrupt;
    volatile bool direct_capture_active;
    volatile bool direct_capture_complete;
    uint16_t *direct_capture_buffer;
    size_t direct_capture_sample_count;
    uint8_t direct_capture_decimation;
    volatile uint32_t last_adc_interrupt_status;
    uint32_t direct_capture_sequence;
    BSPADCDirectCaptureCallback_t direct_capture_callback;
    void *direct_capture_context;
    volatile bool threshold_capture_active;
    volatile bool threshold_dma_active;
    volatile bool threshold_waiting_low;
    uint16_t *threshold_capture_buffer;
    size_t threshold_capture_sample_count;
    uint16_t threshold_high_raw;
    uint16_t threshold_low_raw;
    uint32_t threshold_sample_rate_hz;
    uint32_t threshold_sequence;
    BSPADCThresholdCaptureCallback_t threshold_callback;
    void *threshold_context;
    bool configured;
} BSPADCEngine;

typedef struct {
    volatile bool active;
    volatile uint8_t completed_mask;
    BSPADCEngine *first_engine;
    BSPADCEngine *second_engine;
    BSPADCSynchronizedCaptureCallback_t callback;
    void *context;
    uint32_t sequence;
} BSPADCSynchronizedCapture;

struct BSPADCInstance {
    BSP_ADC_Channel_e channel;
    BSPADCEngine *engine;
    bool registered;
};

static BSPADCEngine adc_engines[BSP_ADC_ENGINE_COUNT];
static BSPADCInstance adc_instances[BSP_ADC_CHANNEL_COUNT];
static BSPADCSynchronizedCapture adc_synchronized_capture;

static bool BSPADCIsValid(const BSPADCInstance *instance);
static bool BSPADCAnyEngineBusy(void);
static void BSPADCQuiesceHardware(BSPADCEngine *engine);
static void BSPADCResetCaptureHardware(BSPADCEngine *engine);
static void BSPADCResetDMAChannel(BSPADCEngine *engine);
static void BSPADCConfigureTimerTriggeredCapture(BSPADCEngine *engine,
    uint16_t *buffer, size_t sample_count,
    uint16_t sample_time_clocks, uint32_t timer_load_value);
static void BSPADCConfigureMaximumRateCapture(BSPADCEngine *engine,
    uint16_t *buffer, size_t raw_sample_count);
static void BSPADCConfigureThresholdMonitor(BSPADCEngine *engine,
    uint16_t low_threshold_raw, uint16_t high_threshold_raw,
    uint32_t timer_load_value);
static void BSPADCConfigureThresholdDMA(BSPADCEngine *engine);
static void BSPADCHandleDMAComplete(BSPADCEngine *engine);
static void BSPADCHandleThresholdInterrupt(BSPADCEngine *engine);
static void BSPADCHandleThresholdDMAComplete(BSPADCEngine *engine);
static void BSPADCHandleThresholdRearmed(BSPADCEngine *engine);
static void BSPADCHandleSynchronizedDMAComplete(BSPADCEngine *engine);
static void BSPADCQuiesceEngineOnly(BSPADCEngine *engine);
static void BSPADCResetSynchronizedState(void);
static uint32_t BSPADCLockInterrupts(void);
static void BSPADCUnlockInterrupts(uint32_t interrupt_state);

BSPADCInstance *BSPADCRegister(BSP_ADC_Channel_e channel)
{
    BSPADCEngineIndex engine_index;
    BSPADCEngine *engine;
    BSPADCInstance *instance;

    if ((channel < BSP_ADC_CHANNEL_INPUT_0) ||
        (channel >= BSP_ADC_CHANNEL_COUNT)) {
        return NULL;
    }
    instance = &adc_instances[channel];
    if (instance->registered) {
        return instance;
    }

    engine_index = (channel == BSP_ADC_CHANNEL_INPUT_1)
                       ? BSP_ADC_ENGINE_ADC1
                       : BSP_ADC_ENGINE_ADC0;
    engine = &adc_engines[engine_index];
    if (!engine->configured) {
        if (engine_index == BSP_ADC_ENGINE_ADC1) {
            engine->regs = ADC_INPUT_1_INST;
            engine->timer_event_route = DL_TIMERG_EVENT_ROUTE_2;
            /* 第二路改接 PB19 / ADC1.6；PA21 在 LaunchPad 上接 VREF-。 */
            engine->input_channel = DL_ADC12_INPUT_CHAN_6;
            engine->dma_channel = DMA_ADC_INPUT_1_CHAN_ID;
            engine->dma_trigger = ADC_INPUT_1_INST_DMA_TRIGGER;
            engine->dma_interrupt = DL_DMA_INTERRUPT_CHANNEL6;
        } else {
            engine->regs = ADC_INPUT_0_INST;
            engine->timer_event_route = DL_TIMERG_EVENT_ROUTE_1;
            engine->input_channel = DL_ADC12_INPUT_CHAN_0;
            engine->dma_channel = DMA_ADC_INPUT_0_CHAN_ID;
            engine->dma_trigger = ADC_INPUT_0_INST_DMA_TRIGGER;
            engine->dma_interrupt = DL_DMA_INTERRUPT_CHANNEL5;
        }
        engine->sample_timer = ADC_SAMPLE_TIMER_INST;
        engine->configured = true;
    }

    instance->channel = channel;
    instance->engine = engine;
    instance->registered = true;

    /*
     * ADC/DMA 完成回调会继续调用 FreeRTOS 的 FromISR API，因此中断优先级
     * 不能高于 configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY。SysConfig 当前
     * 只为 UART 写入了优先级，这里在 BSP 注册时显式补齐，避免默认优先级0
     * 进入内核 API。
     */
    NVIC_SetPriority(DMA_INT_IRQn, BSP_ADC_RTOS_INTERRUPT_PRIORITY);
    if (engine_index == BSP_ADC_ENGINE_ADC0) {
        NVIC_SetPriority(ADC_INPUT_0_INST_INT_IRQN,
            BSP_ADC_RTOS_INTERRUPT_PRIORITY);
    }
    return instance;
}

bool BSPADCStartDirectCapture(BSPADCInstance *instance,
    uint16_t *buffer, size_t buffer_capacity, size_t sample_count,
    uint32_t sample_rate_hz,
    BSPADCDirectCaptureCallback_t callback, void *context)
{
    BSPADCEngine *engine;
    uint32_t interrupt_state;
    size_t raw_sample_count;
    uint8_t decimation;
    uint16_t sample_time_clocks;
    uint32_t timer_load_value;

    if (!BSPADCIsValid(instance) || (buffer == NULL) ||
        (sample_count == 0U) || (sample_count > UINT16_MAX) ||
        !BSPADCIsSampleRateSupported(sample_rate_hz) ||
        (callback == NULL)) {
        return false;
    }
    engine = instance->engine;
    decimation = (sample_rate_hz >
                     BSPADCGetDefaultSampleRateHz(instance))
                       ? (uint8_t)(BSP_BOARD_ADC_MAXIMUM_SAMPLE_RATE_HZ /
                             sample_rate_hz)
                       : 1U;
    raw_sample_count = sample_count * (size_t)decimation;
    if ((decimation == 0U) ||
        ((BSP_BOARD_ADC_MAXIMUM_SAMPLE_RATE_HZ % sample_rate_hz) != 0UL) ||
        (raw_sample_count > buffer_capacity) ||
        (raw_sample_count > UINT16_MAX) ||
        ((sample_rate_hz > BSPADCGetDefaultSampleRateHz(instance)) &&
            ((((uintptr_t)buffer & (sizeof(uint32_t) - 1U)) != 0U) ||
                ((raw_sample_count & 1U) != 0U)))) {
        return false;
    }
    sample_time_clocks =
        (sample_rate_hz > BSPADCGetDefaultSampleRateHz(instance))
            ? BSP_BOARD_ADC_HIGH_SPEED_SAMPLE_TIME_CLOCKS
            : BSP_BOARD_ADC_DEFAULT_SAMPLE_TIME_CLOCKS;
    timer_load_value =
        (BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ / sample_rate_hz) - 1UL;

    interrupt_state = BSPADCLockInterrupts();
    /* 两路共用采集状态和上层 FFT 工作区，一次只允许一路。 */
    if (BSPADCAnyEngineBusy()) {
        BSPADCUnlockInterrupts(interrupt_state);
        return false;
    }

    BSPADCQuiesceHardware(engine);
    BSPADCResetCaptureHardware(engine);

    engine->direct_capture_callback = callback;
    engine->direct_capture_context = context;
    engine->direct_capture_active = true;
    engine->direct_capture_complete = false;
    engine->direct_capture_buffer = buffer;
    engine->direct_capture_sample_count = sample_count;
    engine->direct_capture_decimation = decimation;
    engine->last_adc_interrupt_status = 0UL;

    if (sample_rate_hz > BSPADCGetDefaultSampleRateHz(instance)) {
        BSPADCConfigureMaximumRateCapture(engine, buffer,
            raw_sample_count);
    } else {
        BSPADCConfigureTimerTriggeredCapture(engine, buffer,
            sample_count, sample_time_clocks, timer_load_value);
    }
    BSPADCUnlockInterrupts(interrupt_state);

    NVIC_EnableIRQ(DMA_INT_IRQn);
    if (sample_rate_hz > BSPADCGetDefaultSampleRateHz(instance)) {
        /* 只用一次软件启动，后续由 ADC AUTO_NEXT 连续转换。 */
        DL_ADC12_startConversion(engine->regs);
    } else {
        DL_TimerG_startCounter(engine->sample_timer);
    }
    return true;
}

bool BSPADCStartThresholdTriggeredCapture(
    BSPADCInstance *instance, uint16_t *buffer, size_t buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    uint16_t high_threshold_raw, uint16_t low_threshold_raw,
    BSPADCThresholdCaptureCallback_t callback, void *context)
{
    BSPADCEngine *engine;
    uint32_t interrupt_state;
    uint32_t timer_load_value;

    if (!BSPADCIsValid(instance) ||
        (instance->engine != &adc_engines[BSP_ADC_ENGINE_ADC0]) ||
        (buffer == NULL) ||
        (buffer_capacity < sample_count) || (sample_count < 2U) ||
        (sample_count > UINT16_MAX) ||
        (high_threshold_raw > BSP_ADC_MAXIMUM_RAW_VALUE) ||
        (low_threshold_raw > high_threshold_raw) ||
        !BSPADCIsSampleRateSupported(sample_rate_hz) ||
        (sample_rate_hz > BSPADCGetDefaultSampleRateHz(instance)) ||
        (callback == NULL)) {
        return false;
    }

    engine = instance->engine;
    timer_load_value =
        (BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ / sample_rate_hz) - 1UL;
    interrupt_state = BSPADCLockInterrupts();
    if (BSPADCAnyEngineBusy()) {
        BSPADCUnlockInterrupts(interrupt_state);
        return false;
    }

    BSPADCQuiesceHardware(engine);
    BSPADCResetCaptureHardware(engine);
    engine->threshold_capture_active = true;
    engine->threshold_dma_active = false;
    engine->threshold_waiting_low = false;
    engine->threshold_capture_buffer = buffer;
    engine->threshold_capture_sample_count = sample_count;
    engine->threshold_high_raw = high_threshold_raw;
    engine->threshold_low_raw = low_threshold_raw;
    engine->threshold_sample_rate_hz = sample_rate_hz;
    engine->threshold_callback = callback;
    engine->threshold_context = context;
    engine->last_adc_interrupt_status = 0UL;
    BSPADCConfigureThresholdMonitor(engine, low_threshold_raw,
        high_threshold_raw, timer_load_value);
    BSPADCUnlockInterrupts(interrupt_state);

    NVIC_ClearPendingIRQ(ADC_INPUT_0_INST_INT_IRQN);
    NVIC_EnableIRQ(ADC_INPUT_0_INST_INT_IRQN);
    DL_TimerG_startCounter(engine->sample_timer);
    return true;
}

bool BSPADCStartSynchronizedCapture(
    BSPADCInstance *first_instance, uint16_t *first_buffer,
    size_t first_buffer_capacity, BSPADCInstance *second_instance,
    uint16_t *second_buffer, size_t second_buffer_capacity,
    size_t sample_count, uint32_t sample_rate_hz,
    BSPADCSynchronizedCaptureCallback_t callback, void *context)
{
    BSPADCEngine *first_engine;
    BSPADCEngine *second_engine;
    uint32_t interrupt_state;
    uint16_t sample_time_clocks;
    uint32_t timer_load_value;

    /* 同步路径先限定为共享 TIMG0 的定时触发模式，保证索引对齐。 */
    if (!BSPADCIsValid(first_instance) ||
        !BSPADCIsValid(second_instance) ||
        (first_instance == second_instance) ||
        (first_instance->engine == second_instance->engine) ||
        (first_buffer == NULL) || (second_buffer == NULL) ||
        (first_buffer_capacity < sample_count) ||
        (second_buffer_capacity < sample_count) ||
        (sample_count == 0U) || (sample_count > UINT16_MAX) ||
        (callback == NULL) ||
        (sample_rate_hz == 0UL) ||
        (sample_rate_hz > BSPADCGetDefaultSampleRateHz(first_instance)) ||
        !BSPADCIsSampleRateSupported(sample_rate_hz)) {
        return false;
    }

    first_engine = first_instance->engine;
    second_engine = second_instance->engine;
    interrupt_state = BSPADCLockInterrupts();
    if (adc_synchronized_capture.active || BSPADCAnyEngineBusy()) {
        BSPADCUnlockInterrupts(interrupt_state);
        return false;
    }

    /* 两路先分别复位，再统一写入完全相同的 TIMG0 周期。 */
    BSPADCQuiesceHardware(first_engine);
    BSPADCQuiesceHardware(second_engine);
    BSPADCResetCaptureHardware(first_engine);
    BSPADCResetCaptureHardware(second_engine);

    sample_time_clocks = BSP_BOARD_ADC_DEFAULT_SAMPLE_TIME_CLOCKS;
    timer_load_value =
        (BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ / sample_rate_hz) - 1UL;

    first_engine->direct_capture_callback = NULL;
    first_engine->direct_capture_context = NULL;
    first_engine->direct_capture_active = true;
    first_engine->direct_capture_complete = false;
    first_engine->direct_capture_buffer = first_buffer;
    first_engine->direct_capture_sample_count = sample_count;
    first_engine->direct_capture_decimation = 1U;
    first_engine->last_adc_interrupt_status = 0UL;

    second_engine->direct_capture_callback = NULL;
    second_engine->direct_capture_context = NULL;
    second_engine->direct_capture_active = true;
    second_engine->direct_capture_complete = false;
    second_engine->direct_capture_buffer = second_buffer;
    second_engine->direct_capture_sample_count = sample_count;
    second_engine->direct_capture_decimation = 1U;
    second_engine->last_adc_interrupt_status = 0UL;

    adc_synchronized_capture.active = true;
    adc_synchronized_capture.completed_mask = 0U;
    adc_synchronized_capture.first_engine = first_engine;
    adc_synchronized_capture.second_engine = second_engine;
    adc_synchronized_capture.callback = callback;
    adc_synchronized_capture.context = context;

    BSPADCConfigureTimerTriggeredCapture(first_engine, first_buffer,
        sample_count, sample_time_clocks, timer_load_value);
    BSPADCConfigureTimerTriggeredCapture(second_engine, second_buffer,
        sample_count, sample_time_clocks, timer_load_value);
    BSPADCUnlockInterrupts(interrupt_state);

    NVIC_EnableIRQ(DMA_INT_IRQn);
    /* 两个 ADC/DMA 已经就绪，最后才打开共享定时器，形成统一起点。 */
    DL_TimerG_startCounter(ADC_SAMPLE_TIMER_INST);
    return true;
}

bool BSPADCFinishSynchronizedCapture(void)
{
    uint32_t interrupt_state;
    bool active;

    interrupt_state = BSPADCLockInterrupts();
    active = adc_synchronized_capture.active ||
        (adc_synchronized_capture.first_engine != NULL) ||
        (adc_synchronized_capture.second_engine != NULL);
    if (active) {
        BSPADCQuiesceHardware(&adc_engines[BSP_ADC_ENGINE_ADC0]);
        BSPADCQuiesceHardware(&adc_engines[BSP_ADC_ENGINE_ADC1]);
        adc_engines[BSP_ADC_ENGINE_ADC0].direct_capture_active = false;
        adc_engines[BSP_ADC_ENGINE_ADC1].direct_capture_active = false;
        adc_engines[BSP_ADC_ENGINE_ADC0].direct_capture_complete = false;
        adc_engines[BSP_ADC_ENGINE_ADC1].direct_capture_complete = false;
        adc_engines[BSP_ADC_ENGINE_ADC0].direct_capture_buffer = NULL;
        adc_engines[BSP_ADC_ENGINE_ADC1].direct_capture_buffer = NULL;
        adc_engines[BSP_ADC_ENGINE_ADC0].direct_capture_sample_count = 0U;
        adc_engines[BSP_ADC_ENGINE_ADC1].direct_capture_sample_count = 0U;
        adc_engines[BSP_ADC_ENGINE_ADC0].direct_capture_callback = NULL;
        adc_engines[BSP_ADC_ENGINE_ADC1].direct_capture_callback = NULL;
        adc_engines[BSP_ADC_ENGINE_ADC0].direct_capture_context = NULL;
        adc_engines[BSP_ADC_ENGINE_ADC1].direct_capture_context = NULL;
        BSPADCResetSynchronizedState();
    }
    BSPADCUnlockInterrupts(interrupt_state);
    return true;
}

bool BSPADCIsSynchronizedCaptureActive(void)
{
    return adc_synchronized_capture.active;
}

bool BSPADCFinishDirectCapture(BSPADCInstance *instance)
{
    BSPADCEngine *engine;
    uint32_t interrupt_state;

    if (!BSPADCIsValid(instance)) {
        return false;
    }
    engine = instance->engine;
    if (engine->threshold_capture_active || engine->threshold_dma_active ||
        engine->threshold_waiting_low) {
        return false;
    }
    /* 配对采集必须统一结束，不能只拆掉其中一路。 */
    if ((engine == adc_synchronized_capture.first_engine) ||
        (engine == adc_synchronized_capture.second_engine)) {
        return false;
    }
    interrupt_state = BSPADCLockInterrupts();

    BSPADCQuiesceHardware(engine);
    engine->direct_capture_active = false;
    engine->direct_capture_complete = false;
    engine->direct_capture_buffer = NULL;
    engine->direct_capture_sample_count = 0U;
    engine->direct_capture_decimation = 1U;
    engine->direct_capture_callback = NULL;
    engine->direct_capture_context = NULL;

    /*
     * 保留本次采样时间和 TIMG0 周期。当前仅使用一次性采集，
     * 不应在结束时强制写回 SysConfig 的 1 MHz 默认值；下一次
     * 启动仍会在 ENC=0 时按请求重新设置二者。
     */
    BSPADCUnlockInterrupts(interrupt_state);
    return true;
}

bool BSPADCFinishThresholdTriggeredCapture(BSPADCInstance *instance)
{
    BSPADCEngine *engine;
    bool active;
    uint32_t interrupt_state;

    if (!BSPADCIsValid(instance)) {
        return false;
    }
    engine = instance->engine;
    if (engine != &adc_engines[BSP_ADC_ENGINE_ADC0]) {
        return false;
    }

    interrupt_state = BSPADCLockInterrupts();
    active = engine->threshold_capture_active ||
        engine->threshold_dma_active || engine->threshold_waiting_low;
    if (active) {
        BSPADCQuiesceHardware(engine);
        engine->threshold_capture_active = false;
        engine->threshold_dma_active = false;
        engine->threshold_waiting_low = false;
        engine->threshold_capture_buffer = NULL;
        engine->threshold_capture_sample_count = 0U;
        engine->threshold_callback = NULL;
        engine->threshold_context = NULL;
    }
    BSPADCUnlockInterrupts(interrupt_state);
    if (active) {
        NVIC_DisableIRQ(ADC_INPUT_0_INST_INT_IRQN);
        NVIC_ClearPendingIRQ(ADC_INPUT_0_INST_INT_IRQN);
    }
    return true;
}

bool BSPADCIsDirectCaptureActive(const BSPADCInstance *instance)
{
    return BSPADCIsValid(instance) &&
           instance->engine->direct_capture_active;
}

bool BSPADCIsThresholdTriggeredCaptureActive(
    const BSPADCInstance *instance)
{
    return BSPADCIsValid(instance) &&
        (instance->engine == &adc_engines[BSP_ADC_ENGINE_ADC0]) &&
        (instance->engine->threshold_capture_active ||
            instance->engine->threshold_dma_active ||
            instance->engine->threshold_waiting_low);
}

uint16_t BSPADCGetMaximumRawValue(const BSPADCInstance *instance)
{
    return BSPADCIsValid(instance) ? BSP_ADC_MAXIMUM_RAW_VALUE : 0U;
}

uint16_t BSPADCGetReferenceMillivolts(const BSPADCInstance *instance)
{
    return BSPADCIsValid(instance) ? BSP_ADC_REFERENCE_MILLIVOLTS : 0U;
}

uint32_t BSPADCGetDefaultSampleRateHz(const BSPADCInstance *instance)
{
    return BSPADCIsValid(instance)
               ? (BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ /
                     (ADC_SAMPLE_TIMER_INST_LOAD_VALUE + 1UL))
               : 0UL;
}

bool BSPADCIsSampleRateSupported(uint32_t sample_rate_hz)
{
    return (sample_rate_hz > 0UL) &&
           (sample_rate_hz <= BSP_BOARD_ADC_MAXIMUM_SAMPLE_RATE_HZ) &&
           ((BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ % sample_rate_hz) == 0UL);
}

static bool BSPADCIsValid(const BSPADCInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->channel >= BSP_ADC_CHANNEL_INPUT_0) &&
           (instance->channel < BSP_ADC_CHANNEL_COUNT) &&
           (instance->engine != NULL) && instance->engine->configured &&
           (instance->engine->regs != NULL) &&
           (instance->engine->sample_timer != NULL);
}

static bool BSPADCAnyEngineBusy(void)
{
    BSPADCEngineIndex index;

    for (index = BSP_ADC_ENGINE_ADC0;
         index < BSP_ADC_ENGINE_COUNT; ++index) {
        if (adc_engines[index].direct_capture_active ||
            adc_engines[index].direct_capture_complete ||
            adc_engines[index].threshold_capture_active ||
            adc_engines[index].threshold_dma_active ||
            adc_engines[index].threshold_waiting_low) {
            return true;
        }
    }
    return false;
}

/*
 * 先切断 TIMG0 事件路由，再关闭 ADC/DMA。MSPM0 的硬件事件可在
 * ADC 禁用前已经进入队列，只停定时器计数或清 ENC 不足以保证
 * 下一轮从干净的触发边界开始。
 */
static void BSPADCQuiesceHardware(BSPADCEngine *engine)
{
    if ((engine == NULL) || !engine->configured) {
        return;
    }

    DL_TimerG_disableEvent(engine->sample_timer,
        DL_TIMERG_EVENT_ROUTE_1, DL_TIMERG_EVENT_ZERO_EVENT);
    DL_TimerG_disableEvent(engine->sample_timer,
        DL_TIMERG_EVENT_ROUTE_2, DL_TIMERG_EVENT_ZERO_EVENT);
    DL_TimerG_stopCounter(engine->sample_timer);
    DL_ADC12_stopConversion(engine->regs);
    DL_ADC12_disableDMATrigger(engine->regs,
        DL_ADC12_DMA_MEM0_RESULT_LOADED |
        DL_ADC12_DMA_MEM10_RESULT_LOADED);
    DL_ADC12_disableDMA(engine->regs);
    DL_ADC12_disableInterrupt(engine->regs,
        DL_ADC12_INTERRUPT_WINDOW_COMP_HIGH |
        DL_ADC12_INTERRUPT_WINDOW_COMP_LOW |
        DL_ADC12_INTERRUPT_INIFG);
    DL_DMA_disableChannel(DMA, engine->dma_channel);
    DL_ADC12_disableConversions(engine->regs);
    DL_DMA_clearInterruptStatus(DMA, engine->dma_interrupt);
    DL_ADC12_clearInterruptStatus(engine->regs,
        DL_ADC12_INTERRUPT_WINDOW_COMP_HIGH |
        DL_ADC12_INTERRUPT_WINDOW_COMP_LOW |
        DL_ADC12_INTERRUPT_INIFG |
        DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED |
        DL_ADC12_INTERRUPT_TRIG_OVF |
        DL_ADC12_INTERRUPT_OVERFLOW |
        DL_ADC12_INTERRUPT_DMA_DONE);
}

/*
 * 每次一次性采集都重置共享 TIMG0 和当前 ADC，并重新初始化
 * 当前 DMA 通道。这样可清除重复模式内部指针、排队事件和
 * 单次 DMA 完成后的通道状态。
 */
static void BSPADCResetCaptureHardware(BSPADCEngine *engine)
{
    DL_TimerG_reset(engine->sample_timer);
    DL_ADC12_reset(engine->regs);
    DL_TimerG_enablePower(engine->sample_timer);
    DL_ADC12_enablePower(engine->regs);
    delay_cycles(POWER_STARTUP_DELAY);

    SYSCFG_DL_ADC_SAMPLE_TIMER_init();
    if (engine->regs == ADC_INPUT_1_INST) {
        SYSCFG_DL_ADC_INPUT_1_init();
    } else {
        SYSCFG_DL_ADC_INPUT_0_init();
    }
    BSPADCResetDMAChannel(engine);

    /* SysConfig 初始化会开启 ADC/DMA；保持停止直到本次参数写完。 */
    BSPADCQuiesceHardware(engine);
}

/* 单次 DMA 完成后重建通道模式和外部触发映射。 */
static void BSPADCResetDMAChannel(BSPADCEngine *engine)
{
    DL_DMA_disableChannel(DMA, engine->dma_channel);
    DL_DMA_clearInterruptStatus(DMA, engine->dma_interrupt);
    DL_DMA_enableInterrupt(DMA, engine->dma_interrupt);
    DL_DMA_configTransfer(DMA, engine->dma_channel,
        DL_DMA_SINGLE_TRANSFER_MODE, DL_DMA_NORMAL_MODE,
        DL_DMA_WIDTH_HALF_WORD, DL_DMA_WIDTH_HALF_WORD,
        DL_DMA_ADDR_UNCHANGED, DL_DMA_ADDR_INCREMENT);
    DL_DMA_setTrigger(DMA, engine->dma_channel,
        engine->dma_trigger, DL_DMA_TRIGGER_TYPE_EXTERNAL);
}

/* 1 MHz 及更低速率由 TIMG0 逐点触发，可精确设定采样间隔。 */
static void BSPADCConfigureTimerTriggeredCapture(BSPADCEngine *engine,
    uint16_t *buffer, size_t sample_count,
    uint16_t sample_time_clocks, uint32_t timer_load_value)
{
    DL_DMA_setSrcAddr(DMA, engine->dma_channel,
        DL_ADC12_getMemResultAddress(
            engine->regs, DL_ADC12_MEM_IDX_0));
    DL_DMA_setSrcWidth(DMA, engine->dma_channel,
        DL_DMA_WIDTH_HALF_WORD);
    DL_DMA_setDestWidth(DMA, engine->dma_channel,
        DL_DMA_WIDTH_HALF_WORD);
    DL_DMA_setDestAddr(DMA, engine->dma_channel,
        (uint32_t)(uintptr_t)buffer);
    DL_DMA_setTransferSize(DMA, engine->dma_channel,
        (uint16_t)sample_count);

    DL_ADC12_disableFIFO(engine->regs);
    DL_ADC12_setSampleTime0(engine->regs, sample_time_clocks);
    DL_Timer_disableShadowFeatures(engine->sample_timer);
    DL_TimerG_setLoadValue(engine->sample_timer, timer_load_value);
    DL_TimerG_setTimerCount(engine->sample_timer, timer_load_value);

    DL_ADC12_clearInterruptStatus(engine->regs,
        DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED |
        DL_ADC12_INTERRUPT_TRIG_OVF |
        DL_ADC12_INTERRUPT_OVERFLOW |
        DL_ADC12_INTERRUPT_DMA_DONE);
    DL_ADC12_enableDMATrigger(engine->regs,
        DL_ADC12_DMA_MEM0_RESULT_LOADED);
    DL_DMA_enableChannel(DMA, engine->dma_channel);
    DL_ADC12_enableDMA(engine->regs);
    DL_ADC12_enableConversions(engine->regs);
    DL_TimerG_enableEvent(engine->sample_timer,
        engine->timer_event_route, DL_TIMERG_EVENT_ZERO_EVENT);
}

/*
 * TI 的 MSPM0G3507 adc12_max_freq_dma 例程使用 AUTO_NEXT + FIFO
 * 达到 12 位 4 MSPS。2 MHz 先按 4 MSPS 采集双倍原始点，
 * DMA 完成后原地隔一点取一点，避免高速定时器事件丢触发。
 */
static void BSPADCConfigureMaximumRateCapture(BSPADCEngine *engine,
    uint16_t *buffer, size_t raw_sample_count)
{
    DL_ADC12_initSingleSample(engine->regs,
        DL_ADC12_REPEAT_MODE_ENABLED, DL_ADC12_SAMPLING_SOURCE_AUTO,
        DL_ADC12_TRIG_SRC_SOFTWARE, DL_ADC12_SAMP_CONV_RES_12_BIT,
        DL_ADC12_SAMP_CONV_DATA_FORMAT_UNSIGNED);
    DL_ADC12_configConversionMem(engine->regs, DL_ADC12_MEM_IDX_0,
        engine->input_channel, DL_ADC12_REFERENCE_VOLTAGE_VDDA,
        DL_ADC12_SAMPLE_TIMER_SOURCE_SCOMP0,
        DL_ADC12_AVERAGING_MODE_DISABLED,
        DL_ADC12_BURN_OUT_SOURCE_DISABLED,
        DL_ADC12_TRIGGER_MODE_AUTO_NEXT,
        DL_ADC12_WINDOWS_COMP_MODE_DISABLED);
    DL_ADC12_setPowerDownMode(engine->regs,
        DL_ADC12_POWER_DOWN_MODE_MANUAL);
    DL_ADC12_setSampleTime0(engine->regs,
        BSP_BOARD_ADC_HIGH_SPEED_SAMPLE_TIME_CLOCKS);
    DL_ADC12_enableFIFO(engine->regs);
    DL_ADC12_setDMASamplesCnt(engine->regs,
        BSP_ADC_FIFO_DMA_SAMPLE_COUNT);

    /* FIFO 每次读出两个 16 位样本，DMA 以 32 位宽度搬运。 */
    DL_DMA_setSrcAddr(DMA, engine->dma_channel,
        DL_ADC12_getFIFOAddress(engine->regs));
    DL_DMA_setSrcWidth(DMA, engine->dma_channel, DL_DMA_WIDTH_WORD);
    DL_DMA_setDestWidth(DMA, engine->dma_channel, DL_DMA_WIDTH_WORD);
    DL_DMA_setDestAddr(DMA, engine->dma_channel,
        (uint32_t)(uintptr_t)buffer);
    DL_DMA_setTransferSize(DMA, engine->dma_channel,
        (uint16_t)(raw_sample_count / 2U));

    DL_ADC12_clearInterruptStatus(engine->regs,
        DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED |
        DL_ADC12_INTERRUPT_TRIG_OVF |
        DL_ADC12_INTERRUPT_OVERFLOW |
        DL_ADC12_INTERRUPT_DMA_DONE);
    DL_ADC12_enableDMATrigger(engine->regs,
        DL_ADC12_DMA_MEM10_RESULT_LOADED);
    DL_DMA_enableChannel(DMA, engine->dma_channel);
    DL_ADC12_enableDMA(engine->regs);
    DL_ADC12_enableConversions(engine->regs);
}

/* ADC0 以定时器逐点转换，窗口比较器只开一个方向的 CPU 中断。 */
static void BSPADCConfigureThresholdMonitor(BSPADCEngine *engine,
    uint16_t low_threshold_raw, uint16_t high_threshold_raw,
    uint32_t timer_load_value)
{
    uint32_t interrupt_mask;

    DL_TimerG_disableEvent(engine->sample_timer,
        engine->timer_event_route, DL_TIMERG_EVENT_ZERO_EVENT);
    DL_TimerG_stopCounter(engine->sample_timer);
    DL_ADC12_disableInterrupt(engine->regs,
        DL_ADC12_INTERRUPT_WINDOW_COMP_HIGH |
        DL_ADC12_INTERRUPT_WINDOW_COMP_LOW |
        DL_ADC12_INTERRUPT_INIFG);
    DL_ADC12_configConversionMem(engine->regs, DL_ADC12_MEM_IDX_0,
        engine->input_channel, DL_ADC12_REFERENCE_VOLTAGE_VDDA,
        DL_ADC12_SAMPLE_TIMER_SOURCE_SCOMP0,
        DL_ADC12_AVERAGING_MODE_DISABLED,
        DL_ADC12_BURN_OUT_SOURCE_DISABLED,
        DL_ADC12_TRIGGER_MODE_TRIGGER_NEXT,
        DL_ADC12_WINDOWS_COMP_MODE_ENABLED);
    DL_ADC12_configWinCompLowThld(engine->regs, low_threshold_raw);
    DL_ADC12_configWinCompHighThld(engine->regs, high_threshold_raw);
    DL_ADC12_disableFIFO(engine->regs);
    DL_ADC12_setDMASamplesCnt(engine->regs, 1U);
    DL_ADC12_setSampleTime0(engine->regs,
        BSP_BOARD_ADC_DEFAULT_SAMPLE_TIME_CLOCKS);
    DL_Timer_disableShadowFeatures(engine->sample_timer);
    DL_TimerG_setLoadValue(engine->sample_timer, timer_load_value);
    DL_TimerG_setTimerCount(engine->sample_timer, timer_load_value);
    DL_ADC12_clearInterruptStatus(engine->regs,
        DL_ADC12_INTERRUPT_WINDOW_COMP_HIGH |
        DL_ADC12_INTERRUPT_WINDOW_COMP_LOW |
        DL_ADC12_INTERRUPT_INIFG |
        DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED |
        DL_ADC12_INTERRUPT_TRIG_OVF |
        DL_ADC12_INTERRUPT_OVERFLOW |
        DL_ADC12_INTERRUPT_DMA_DONE);
    interrupt_mask = engine->threshold_waiting_low
        ? DL_ADC12_INTERRUPT_WINDOW_COMP_LOW
        : DL_ADC12_INTERRUPT_WINDOW_COMP_HIGH;
    DL_ADC12_enableInterrupt(engine->regs, interrupt_mask);
    DL_ADC12_enableConversions(engine->regs);
    DL_TimerG_enableEvent(engine->sample_timer,
        engine->timer_event_route, DL_TIMERG_EVENT_ZERO_EVENT);
}

/* 高阈值 ISR 已经保存了 buffer[0]，DMA 只负责剩余点数。 */
static void BSPADCConfigureThresholdDMA(BSPADCEngine *engine)
{
    DL_DMA_setSrcAddr(DMA, engine->dma_channel,
        DL_ADC12_getMemResultAddress(
            engine->regs, DL_ADC12_MEM_IDX_0));
    DL_DMA_setSrcWidth(DMA, engine->dma_channel,
        DL_DMA_WIDTH_HALF_WORD);
    DL_DMA_setDestWidth(DMA, engine->dma_channel,
        DL_DMA_WIDTH_HALF_WORD);
    DL_DMA_setDestAddr(DMA, engine->dma_channel,
        (uint32_t)(uintptr_t)(engine->threshold_capture_buffer + 1U));
    DL_DMA_setTransferSize(DMA, engine->dma_channel,
        (uint16_t)(engine->threshold_capture_sample_count - 1U));
    DL_ADC12_clearInterruptStatus(engine->regs,
        DL_ADC12_INTERRUPT_WINDOW_COMP_HIGH |
        DL_ADC12_INTERRUPT_WINDOW_COMP_LOW |
        DL_ADC12_INTERRUPT_INIFG |
        DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED |
        DL_ADC12_INTERRUPT_TRIG_OVF |
        DL_ADC12_INTERRUPT_OVERFLOW |
        DL_ADC12_INTERRUPT_DMA_DONE);
    DL_TimerG_setTimerCount(engine->sample_timer,
        (BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ /
            engine->threshold_sample_rate_hz) - 1UL);
    DL_ADC12_enableDMATrigger(engine->regs,
        DL_ADC12_DMA_MEM0_RESULT_LOADED);
    DL_DMA_enableChannel(DMA, engine->dma_channel);
    DL_ADC12_enableDMA(engine->regs);
    DL_ADC12_enableConversions(engine->regs);
    DL_TimerG_enableEvent(engine->sample_timer,
        engine->timer_event_route, DL_TIMERG_EVENT_ZERO_EVENT);
}

static void BSPADCHandleDMAComplete(BSPADCEngine *engine)
{
    BSPADCDirectCaptureCallback_t callback;
    void *context;
    uint32_t sequence;
    size_t index;

    if ((engine == NULL) || !engine->configured ||
        (!engine->direct_capture_active &&
            !(engine->threshold_capture_active &&
                engine->threshold_dma_active))) {
        return;
    }

    if (engine->threshold_capture_active && engine->threshold_dma_active) {
        BSPADCHandleThresholdDMAComplete(engine);
        return;
    }

    if (adc_synchronized_capture.active &&
        ((engine == adc_synchronized_capture.first_engine) ||
            (engine == adc_synchronized_capture.second_engine))) {
        BSPADCHandleSynchronizedDMAComplete(engine);
        return;
    }

    engine->last_adc_interrupt_status =
        DL_ADC12_getRawInterruptStatus(engine->regs,
            DL_ADC12_INTERRUPT_TRIG_OVF |
            DL_ADC12_INTERRUPT_OVERFLOW);
    BSPADCQuiesceHardware(engine);

    /* 2 MHz 路径将 4 MSPS FIFO 数据原地二分频为最终 N 点。 */
    if ((engine->direct_capture_decimation > 1U) &&
        (engine->direct_capture_buffer != NULL)) {
        for (index = 0U;
             index < engine->direct_capture_sample_count; ++index) {
            engine->direct_capture_buffer[index] =
                engine->direct_capture_buffer[
                    index * engine->direct_capture_decimation];
        }
    }
    engine->direct_capture_active = false;
    engine->direct_capture_complete = true;
    sequence = ++engine->direct_capture_sequence;
    callback = engine->direct_capture_callback;
    context = engine->direct_capture_context;
    if (callback != NULL) {
        callback(sequence, context);
    }
}

/* ADC12 窗口比较器越过高阈值后，在同一个 ADC ISR 内切换到 DMA。 */
static void BSPADCHandleThresholdInterrupt(BSPADCEngine *engine)
{
    uint16_t sample;

    if ((engine == NULL) || !engine->threshold_capture_active) {
        return;
    }
    if (engine->threshold_dma_active) {
        return;
    }
    if (engine->threshold_waiting_low) {
        BSPADCHandleThresholdRearmed(engine);
        return;
    }
    sample = DL_ADC12_getMemResult(engine->regs, DL_ADC12_MEM_IDX_0);
    if (engine->threshold_capture_buffer != NULL) {
        engine->threshold_capture_buffer[0] = sample;
    }
    DL_TimerG_disableEvent(engine->sample_timer,
        engine->timer_event_route, DL_TIMERG_EVENT_ZERO_EVENT);
    DL_TimerG_stopCounter(engine->sample_timer);
    BSPADCQuiesceEngineOnly(engine);
    engine->threshold_dma_active = true;
    BSPADCConfigureThresholdDMA(engine);
    NVIC_EnableIRQ(DMA_INT_IRQn);
    DL_TimerG_startCounter(engine->sample_timer);
}

/* DMA 采满后切到低阈值监视；在此期间不允许新的高阈值触发。 */
static void BSPADCHandleThresholdDMAComplete(BSPADCEngine *engine)
{
    BSPADCThresholdCaptureCallback_t callback;
    void *context;
    uint32_t sequence;

    if ((engine == NULL) || !engine->threshold_capture_active ||
        !engine->threshold_dma_active) {
        return;
    }
    engine->last_adc_interrupt_status =
        DL_ADC12_getRawInterruptStatus(engine->regs,
            DL_ADC12_INTERRUPT_TRIG_OVF |
            DL_ADC12_INTERRUPT_OVERFLOW);
    DL_TimerG_disableEvent(engine->sample_timer,
        engine->timer_event_route, DL_TIMERG_EVENT_ZERO_EVENT);
    DL_TimerG_stopCounter(engine->sample_timer);
    BSPADCQuiesceEngineOnly(engine);
    engine->threshold_dma_active = false;
    engine->threshold_waiting_low = true;
    BSPADCConfigureThresholdMonitor(engine, engine->threshold_low_raw,
        engine->threshold_high_raw,
        (BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ /
            engine->threshold_sample_rate_hz) - 1UL);
    NVIC_ClearPendingIRQ(ADC_INPUT_0_INST_INT_IRQN);
    NVIC_EnableIRQ(ADC_INPUT_0_INST_INT_IRQN);
    DL_TimerG_startCounter(engine->sample_timer);

    callback = engine->threshold_callback;
    context = engine->threshold_context;
    sequence = ++engine->threshold_sequence;
    if (callback != NULL) {
        callback(BSP_ADC_THRESHOLD_CAPTURE_COMPLETE, sequence, context);
    }
}

/* 低阈值命中后停止 ADC，直到下一次显式 Arm 才重新开始监视。 */
static void BSPADCHandleThresholdRearmed(BSPADCEngine *engine)
{
    BSPADCThresholdCaptureCallback_t callback;
    void *context;
    uint32_t sequence;

    if ((engine == NULL) || !engine->threshold_capture_active ||
        !engine->threshold_waiting_low) {
        return;
    }
    DL_TimerG_disableEvent(engine->sample_timer,
        engine->timer_event_route, DL_TIMERG_EVENT_ZERO_EVENT);
    DL_TimerG_stopCounter(engine->sample_timer);
    BSPADCQuiesceEngineOnly(engine);
    NVIC_DisableIRQ(ADC_INPUT_0_INST_INT_IRQN);
    NVIC_ClearPendingIRQ(ADC_INPUT_0_INST_INT_IRQN);
    /* 保留逻辑占用标志，直到上层收到 REARMED 并调用 Finish。 */
    callback = engine->threshold_callback;
    context = engine->threshold_context;
    sequence = ++engine->threshold_sequence;
    if (callback != NULL) {
        callback(BSP_ADC_THRESHOLD_SIGNAL_REARMED, sequence, context);
    }
}

/* 配对 DMA 中断：先只停已完成的 ADC，第二路完成后再停共享 TIMG0。 */
static void BSPADCHandleSynchronizedDMAComplete(BSPADCEngine *engine)
{
    uint8_t bit;
    BSPADCSynchronizedCaptureCallback_t callback;
    void *context;
    uint32_t sequence;

    if ((engine == NULL) || !adc_synchronized_capture.active) {
        return;
    }
    bit = (engine == adc_synchronized_capture.first_engine) ? 1U : 2U;
    if ((adc_synchronized_capture.completed_mask & bit) != 0U) {
        return;
    }
    engine->last_adc_interrupt_status =
        DL_ADC12_getRawInterruptStatus(engine->regs,
            DL_ADC12_INTERRUPT_TRIG_OVF |
            DL_ADC12_INTERRUPT_OVERFLOW);
    BSPADCQuiesceEngineOnly(engine);
    engine->direct_capture_active = false;
    engine->direct_capture_complete = true;
    adc_synchronized_capture.completed_mask |= bit;

    if (adc_synchronized_capture.completed_mask != 3U) {
        return;
    }
    /* 两路都完成后才关闭共享定时器，并一次性通知上层。 */
    DL_TimerG_disableEvent(ADC_SAMPLE_TIMER_INST,
        DL_TIMERG_EVENT_ROUTE_1, DL_TIMERG_EVENT_ZERO_EVENT);
    DL_TimerG_disableEvent(ADC_SAMPLE_TIMER_INST,
        DL_TIMERG_EVENT_ROUTE_2, DL_TIMERG_EVENT_ZERO_EVENT);
    DL_TimerG_stopCounter(ADC_SAMPLE_TIMER_INST);
    adc_synchronized_capture.active = false;
    callback = adc_synchronized_capture.callback;
    context = adc_synchronized_capture.context;
    sequence = ++adc_synchronized_capture.sequence;
    if (callback != NULL) {
        callback(sequence, context);
    }
}

static void BSPADCQuiesceEngineOnly(BSPADCEngine *engine)
{
    if ((engine == NULL) || !engine->configured) {
        return;
    }
    DL_ADC12_stopConversion(engine->regs);
    DL_ADC12_disableDMATrigger(engine->regs,
        DL_ADC12_DMA_MEM0_RESULT_LOADED |
        DL_ADC12_DMA_MEM10_RESULT_LOADED);
    DL_ADC12_disableDMA(engine->regs);
    DL_ADC12_disableInterrupt(engine->regs,
        DL_ADC12_INTERRUPT_WINDOW_COMP_HIGH |
        DL_ADC12_INTERRUPT_WINDOW_COMP_LOW |
        DL_ADC12_INTERRUPT_INIFG);
    DL_DMA_disableChannel(DMA, engine->dma_channel);
    DL_ADC12_disableConversions(engine->regs);
    DL_DMA_clearInterruptStatus(DMA, engine->dma_interrupt);
    DL_ADC12_clearInterruptStatus(engine->regs,
        DL_ADC12_INTERRUPT_WINDOW_COMP_HIGH |
        DL_ADC12_INTERRUPT_WINDOW_COMP_LOW |
        DL_ADC12_INTERRUPT_INIFG |
        DL_ADC12_INTERRUPT_MEM0_RESULT_LOADED |
        DL_ADC12_INTERRUPT_TRIG_OVF |
        DL_ADC12_INTERRUPT_OVERFLOW |
        DL_ADC12_INTERRUPT_DMA_DONE);
}

static void BSPADCResetSynchronizedState(void)
{
    adc_synchronized_capture.active = false;
    adc_synchronized_capture.completed_mask = 0U;
    adc_synchronized_capture.first_engine = NULL;
    adc_synchronized_capture.second_engine = NULL;
    adc_synchronized_capture.callback = NULL;
    adc_synchronized_capture.context = NULL;
}

static uint32_t BSPADCLockInterrupts(void)
{
    uint32_t interrupt_state = __get_PRIMASK();

    __disable_irq();
    return interrupt_state;
}

static void BSPADCUnlockInterrupts(uint32_t interrupt_state)
{
    if (interrupt_state == 0U) {
        __enable_irq();
    }
}

void ADC0_IRQHandler(void)
{
    DL_ADC12_IIDX interrupt_index;
    BSPADCEngine *engine = &adc_engines[BSP_ADC_ENGINE_ADC0];

    interrupt_index = DL_ADC12_getPendingInterrupt(ADC_INPUT_0_INST);
    if (!engine->threshold_capture_active) {
        return;
    }
    switch (interrupt_index) {
        case DL_ADC12_IIDX_WINDOW_COMP_HIGH:
            if (!engine->threshold_waiting_low) {
                BSPADCHandleThresholdInterrupt(engine);
            }
            break;

        case DL_ADC12_IIDX_WINDOW_COMP_LOW:
            if (engine->threshold_waiting_low) {
                BSPADCHandleThresholdRearmed(engine);
            }
            break;

        default:
            break;
    }
}

#endif /* ADC/trigger feature set */

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U) || \
    (APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U)
/* DMA是共享中断向量，在这里统一分发ADC完成事件和DAC半缓冲事件。 */
void DMA_IRQHandler(void)
{
    DL_DMA_EVENT_IIDX interrupt_index;

    do {
        interrupt_index = DL_DMA_getPendingInterrupt(DMA);
        switch (interrupt_index) {
#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U
            case DL_DMA_FULL_CH_EVENT_IIDX_EARLY_IRQ_DMACH0:
                BSPDACHandleDMAEarlyInterrupt();
                break;
#endif

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) || \
    (APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U)
            case DL_DMA_EVENT_IIDX_DMACH5:
                BSPADCHandleDMAComplete(
                    &adc_engines[BSP_ADC_ENGINE_ADC0]);
                break;

            case DL_DMA_EVENT_IIDX_DMACH6:
                BSPADCHandleDMAComplete(
                    &adc_engines[BSP_ADC_ENGINE_ADC1]);
                break;
#endif

            default:
                break;
        }
    } while (interrupt_index != DL_DMA_EVENT_IIDX_NO_INTR);
}
#endif
