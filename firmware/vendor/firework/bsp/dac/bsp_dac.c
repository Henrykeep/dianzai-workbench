/*
 * DAC BSP 管理 PA15 固定电压、周期 DMA 波形和双缓冲流式波形的硬件生命周期。
 */
#include "bsp/dac/bsp_dac.h"

#include "application/app_config.h"

#if APP_ENABLE_WAVEFORM_OUTPUT_DAC != 0U

#include <stddef.h>

#include "FreeRTOS.h"
#include "ti_msp_dl_config.h"

#define BSP_DAC_MAXIMUM_RAW_VALUE    (4095U)
#define BSP_DAC_REFERENCE_MILLIVOLTS (3300U)
#define BSP_DAC_RTOS_INTERRUPT_PRIORITY \
    ((uint32_t)configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY)

struct BSPDACInstance {
    /* 板级逻辑通道及其对应的真实 DAC 外设。 */
    BSP_DAC_Channel_e channel;
    DAC12_Regs *regs;
    /* 保存最近设置值，关闭后再次启动时恢复该电压。 */
    uint16_t raw_value;
    uint16_t *stream_buffers[2];
    uint16_t stream_sample_count;
    uint8_t stream_active_buffer;
    volatile bool stream_buffer_ready[2];
    BSP_DAC_Waveform_Refill_Callback stream_refill_callback;
    void *stream_context;
    volatile uint32_t fifo_underrun_count;
    volatile uint32_t stream_refill_miss_count;
    bool streaming;
    volatile bool waveform_running;
    bool registered;
};

/* DAC 资源固定，使用静态实例池避免动态内存分配。 */
static BSPDACInstance dac_instances[BSP_DAC_CHANNEL_COUNT];

/*
 * 重启周期输出时重新装载完整 DMA 通道配置。重复传输模式会在一轮结束后
 * 保存并恢复初始地址/长度，仅改 DMASA/DMASZ 不能可靠地替换上一轮状态。
 */
static const DL_DMA_Config bsp_dac_dma_config = {
    .transferMode  = DL_DMA_FULL_CH_REPEAT_SINGLE_TRANSFER_MODE,
    .extendedMode  = DL_DMA_NORMAL_MODE,
    .destIncrement = DL_DMA_ADDR_UNCHANGED,
    .srcIncrement  = DL_DMA_ADDR_INCREMENT,
    .destWidth     = DL_DMA_WIDTH_HALF_WORD,
    .srcWidth      = DL_DMA_WIDTH_HALF_WORD,
    .trigger       = DAC12_INST_DMA_TRIGGER,
    .triggerType   = DL_DMA_TRIGGER_TYPE_EXTERNAL,
};

/*
 * 连续 DDS 使用一个连续的双半区表。重复模式在整个表结束后由硬件无缝
 * 恢复源地址和长度，避免CPU在DAC FIFO仅剩少量数据时重装DMA。
 */
static const DL_DMA_Config bsp_dac_streaming_dma_config = {
    .transferMode  = DL_DMA_FULL_CH_REPEAT_SINGLE_TRANSFER_MODE,
    .extendedMode  = DL_DMA_NORMAL_MODE,
    .destIncrement = DL_DMA_ADDR_UNCHANGED,
    .srcIncrement  = DL_DMA_ADDR_INCREMENT,
    .destWidth     = DL_DMA_WIDTH_HALF_WORD,
    .srcWidth      = DL_DMA_WIDTH_HALF_WORD,
    .trigger       = DAC12_INST_DMA_TRIGGER,
    .triggerType   = DL_DMA_TRIGGER_TYPE_EXTERNAL,
};

static bool BSPDACIsValid(const BSPDACInstance *instance);
static bool BSPDACConvertSampleRate(BSP_DAC_Sample_Rate_e sample_rate,
    DL_DAC12_SAMPLES_PER_SECOND *driverlib_rate);
static bool BSPDACStartWaveformHardware(BSPDACInstance *instance,
    const uint16_t *samples, uint16_t sample_count,
    BSP_DAC_Sample_Rate_e sample_rate, const DL_DMA_Config *dma_config);
static void BSPDACClearStreamingState(BSPDACInstance *instance);
static void BSPDACStopWaveformHardware(BSPDACInstance *instance);
static void BSPDACAdvanceStreamingBuffer(
    BSPDACInstance *instance, uint8_t completed_buffer);

/* 注册逻辑 DAC 通道，并将 PA15 初始输出设置为 0 V。 */
BSPDACInstance *BSPDACRegister(BSP_DAC_Channel_e channel)
{
    BSPDACInstance *instance;

    if ((channel < BSP_DAC_CHANNEL_OUTPUT_0) ||
        (channel >= BSP_DAC_CHANNEL_COUNT)) {
        return NULL;
    }

    instance = &dac_instances[channel];
    if (instance->registered) {
        return instance;
    }

    switch (channel) {
        case BSP_DAC_CHANNEL_OUTPUT_0:
            instance->regs = DAC0;
            break;

        default:
            return NULL;
    }

    instance->channel    = channel;
    instance->raw_value  = 0U;
    instance->fifo_underrun_count = 0UL;
    instance->stream_refill_miss_count = 0UL;
    instance->waveform_running = false;
    instance->registered = true;
    BSPDACStopWaveformHardware(instance);
    DL_DAC12_output12(instance->regs, instance->raw_value);
    return instance;
}

/* 检查范围后写入 DAC 数据寄存器，并保存最新设置值。 */
bool BSPDACWriteRaw(BSPDACInstance *instance, uint16_t raw_value)
{
    if (!BSPDACIsValid(instance) ||
        (raw_value > BSP_DAC_MAXIMUM_RAW_VALUE)) {
        return false;
    }

    BSPDACStopWaveformHardware(instance);
    DL_DAC12_output12(instance->regs, raw_value);
    instance->raw_value = raw_value;
    return true;
}

/* 配置 DMA_CH0 循环搬运查找表，由 DAC 内部 Sample Timer 消费 FIFO。 */
bool BSPDACStartWaveform(BSPDACInstance *instance,
    const uint16_t *samples, uint16_t sample_count,
    BSP_DAC_Sample_Rate_e sample_rate)
{
    if (!BSPDACIsValid(instance) || (samples == NULL) ||
        (sample_count < 2U)) {
        return false;
    }

    BSPDACStopWaveformHardware(instance);
    return BSPDACStartWaveformHardware(instance, samples,
        sample_count, sample_rate, &bsp_dac_dma_config);
}

bool BSPDACStartStreamingWaveform(BSPDACInstance *instance,
    uint16_t *buffer_a, uint16_t *buffer_b, uint16_t sample_count,
    BSP_DAC_Sample_Rate_e sample_rate,
    BSP_DAC_Waveform_Refill_Callback refill_callback, void *context)
{
    uint32_t total_sample_count;
    bool result;

    total_sample_count = (uint32_t)sample_count * 2UL;
    if (!BSPDACIsValid(instance) || (buffer_a == NULL) ||
        (buffer_b == NULL) || (sample_count < 2U) ||
        (total_sample_count > UINT16_MAX) ||
        (buffer_b != &buffer_a[sample_count]) ||
        (refill_callback == NULL)) {
        return false;
    }

    BSPDACStopWaveformHardware(instance);
    instance->stream_buffers[0] = buffer_a;
    instance->stream_buffers[1] = buffer_b;
    instance->stream_sample_count = sample_count;
    instance->stream_active_buffer = 0U;
    instance->stream_buffer_ready[0] = false;
    instance->stream_buffer_ready[1] = true;
    instance->stream_refill_callback = refill_callback;
    instance->stream_context = context;
    instance->streaming = true;

    result = BSPDACStartWaveformHardware(instance, buffer_a,
        (uint16_t)total_sample_count, sample_rate,
        &bsp_dac_streaming_dma_config);
    if (!result) {
        BSPDACClearStreamingState(instance);
    }
    return result;
}

static bool BSPDACStartWaveformHardware(BSPDACInstance *instance,
    const uint16_t *samples, uint16_t sample_count,
    BSP_DAC_Sample_Rate_e sample_rate, const DL_DMA_Config *dma_config)
{
    DL_DAC12_SAMPLES_PER_SECOND driverlib_rate;
    DL_DAC12_Config dac_stream_config;

    if ((instance == NULL) || (samples == NULL) ||
        (dma_config == NULL) ||
        !BSPDACConvertSampleRate(sample_rate, &driverlib_rate)) {
        return false;
    }

    /*
     * TI 官方函数发生器在更换查找表时会复位并重新初始化 DAC。单纯清除
     * FIFOEN 不能保证内部 FIFO 指针和 DMA 握手状态回到上电值，因此这里
     * 同样执行外设硬复位，修复高频波形切换到低频波形后输出停止的问题。
     * Sample Timer 和 DMA trigger 最后才启用，避免装载完成前发生欠载。
     */
    DL_DAC12_disable(instance->regs);
    DL_DAC12_reset(instance->regs);
    DL_DAC12_enablePower(instance->regs);
    delay_cycles(POWER_STARTUP_DELAY);
    dac_stream_config.outputEnable = DL_DAC12_OUTPUT_ENABLED;
    dac_stream_config.resolution = DL_DAC12_RESOLUTION_12BIT;
    dac_stream_config.representation = DL_DAC12_REPRESENTATION_BINARY;
    dac_stream_config.voltageReferenceSource =
        DL_DAC12_VREF_SOURCE_VDDA_VSSA;
    dac_stream_config.amplifierSetting = DL_DAC12_AMP_ON;
    dac_stream_config.fifoEnable = DL_DAC12_FIFO_ENABLED;
    dac_stream_config.fifoTriggerSource =
        DL_DAC12_FIFO_TRIGGER_SAMPLETIMER;
    dac_stream_config.dmaTriggerEnable =
        DL_DAC12_DMA_TRIGGER_DISABLED;
    dac_stream_config.dmaTriggerThreshold =
        DL_DAC12_FIFO_THRESHOLD_TWO_QTRS_EMPTY;
    dac_stream_config.sampleTimeGeneratorEnable =
        DL_DAC12_SAMPLETIMER_DISABLE;
    dac_stream_config.sampleRate = driverlib_rate;
    DL_DAC12_init(instance->regs, &dac_stream_config);

    DL_DMA_initChannel(DMA, DMA_DAC_OUTPUT_CHAN_ID, dma_config);
    DL_DMA_disableInterrupt(DMA,
        DL_DMA_INTERRUPT_CHANNEL0 |
            DL_DMA_FULL_CH_INTERRUPT_EARLY_CHANNEL0);
    DL_DMA_clearInterruptStatus(DMA,
        DL_DMA_INTERRUPT_CHANNEL0 |
            DL_DMA_FULL_CH_INTERRUPT_EARLY_CHANNEL0);
    if (instance->streaming) {
        /*
         * 2048点循环表走到一半时前半区已经空闲；硬件继续播放后半区，
         * 给回填任务留下完整1024点（1 MSPS时为1.024 ms）的处理时间。
         */
        DL_DMA_Full_Ch_setEarlyInterruptThreshold(DMA,
            DMA_DAC_OUTPUT_CHAN_ID,
            DL_DMA_EARLY_INTERRUPT_THRESHOLD_HALF);
        DL_DMA_enableInterrupt(DMA,
            DL_DMA_FULL_CH_INTERRUPT_EARLY_CHANNEL0);
        NVIC_SetPriority(DMA_INT_IRQn,
            BSP_DAC_RTOS_INTERRUPT_PRIORITY);
        NVIC_EnableIRQ(DMA_INT_IRQn);
    }

    DL_DMA_setSrcAddr(DMA, DMA_DAC_OUTPUT_CHAN_ID,
        (uint32_t)(uintptr_t)samples);
    DL_DMA_setDestAddr(DMA, DMA_DAC_OUTPUT_CHAN_ID,
        (uint32_t)(uintptr_t)&instance->regs->DATA0);
    DL_DMA_setTransferSize(
        DMA, DMA_DAC_OUTPUT_CHAN_ID, sample_count);

    DL_DAC12_clearInterruptStatus(
        instance->regs, DL_DAC12_INTERRUPT_DMA_DONE |
                            DL_DAC12_INTERRUPT_FIFO_UNDERRUN);
    DL_DAC12_enableInterrupt(instance->regs,
        DL_DAC12_INTERRUPT_DMA_DONE |
            DL_DAC12_INTERRUPT_FIFO_UNDERRUN);
    /*
     * 两个中断的回调都会调用 FreeRTOS FromISR 接口，因此使用系统允许调用
     * 内核API的最高中断优先级，减少高采样率下的通知延迟。
     */
    NVIC_SetPriority(DAC12_INT_IRQN,
        BSP_DAC_RTOS_INTERRUPT_PRIORITY);
    NVIC_ClearPendingIRQ(DAC12_INT_IRQN);
    DL_DMA_enableChannel(DMA, DMA_DAC_OUTPUT_CHAN_ID);
    DL_DAC12_enable(instance->regs);
    instance->waveform_running = true;
    NVIC_EnableIRQ(DAC12_INT_IRQN);
    DL_DAC12_enableDMATrigger(instance->regs);
    DL_DAC12_enableSampleTimeGenerator(instance->regs);
    return true;
}

bool BSPDACStopWaveform(BSPDACInstance *instance)
{
    if (!BSPDACIsValid(instance)) {
        return false;
    }

    BSPDACStopWaveformHardware(instance);
    return true;
}

/* 根据 enabled 控制 DAC，并在重新启用时恢复最近设置值。 */
bool BSPDACSetEnabled(BSPDACInstance *instance, bool enabled)
{
    if (!BSPDACIsValid(instance)) {
        return false;
    }

    if (enabled) {
        DL_DAC12_enable(instance->regs);
        BSPDACStopWaveformHardware(instance);
        DL_DAC12_output12(instance->regs, instance->raw_value);
    } else {
        BSPDACStopWaveformHardware(instance);
        DL_DAC12_disable(instance->regs);
    }

    return true;
}

/* 读取 DAC 控制寄存器中的实际启用状态。 */
bool BSPDACIsEnabled(const BSPDACInstance *instance)
{
    return BSPDACIsValid(instance) &&
           DL_DAC12_isEnabled(instance->regs);
}

bool BSPDACIsWaveformRunning(const BSPDACInstance *instance)
{
    return BSPDACIsValid(instance) && instance->waveform_running;
}

/* 返回最近一次成功写入 DAC 的原始值。 */
uint16_t BSPDACGetRawValue(const BSPDACInstance *instance)
{
    return BSPDACIsValid(instance) ? instance->raw_value : 0U;
}

/* 返回当前 DAC 通道的 12 位满量程原始值。 */
uint16_t BSPDACGetMaximumRawValue(const BSPDACInstance *instance)
{
    return BSPDACIsValid(instance) ? BSP_DAC_MAXIMUM_RAW_VALUE : 0U;
}

/* 返回 VDDA/VSSA 模式下用于换算的 3.3 V 标称参考值。 */
uint16_t BSPDACGetReferenceMillivolts(const BSPDACInstance *instance)
{
    return BSPDACIsValid(instance) ? BSP_DAC_REFERENCE_MILLIVOLTS : 0U;
}

/* 返回上电以来检测到的 FIFO 欠载次数，32位读在 Cortex-M0+ 上是原子的。 */
uint32_t BSPDACGetFIFOunderrunCount(const BSPDACInstance *instance)
{
    return BSPDACIsValid(instance) ? instance->fifo_underrun_count : 0UL;
}

uint32_t BSPDACGetStreamRefillMissCount(
    const BSPDACInstance *instance)
{
    return BSPDACIsValid(instance)
               ? instance->stream_refill_miss_count
               : 0UL;
}

bool BSPDACCommitStreamingBuffer(
    BSPDACInstance *instance, uint16_t *samples)
{
    uint32_t interrupt_state;
    uint8_t buffer_index;
    bool result = false;

    if (!BSPDACIsValid(instance) || (samples == NULL)) {
        return false;
    }

    /* 与 DAC ISR 原子核对活动缓冲区，防止停机/切换发生在检查与提交之间。 */
    interrupt_state = __get_PRIMASK();
    __disable_irq();
    if (!instance->streaming || !instance->waveform_running) {
        goto restore_interrupts;
    }
    if (samples == instance->stream_buffers[0]) {
        buffer_index = 0U;
    } else if (samples == instance->stream_buffers[1]) {
        buffer_index = 1U;
    } else {
        goto restore_interrupts;
    }
    if (buffer_index == instance->stream_active_buffer) {
        goto restore_interrupts;
    }

    /* 单字节就绪标志在 Cortex-M0+ 上原子写入；DAC ISR 只读取该标志。 */
    instance->stream_buffer_ready[buffer_index] = true;
    result = true;

restore_interrupts:
    if (interrupt_state == 0U) {
        __enable_irq();
    }
    return result;
}

/* 检查 DAC 实例是否已经完成注册且硬件映射有效。 */
static bool BSPDACIsValid(const BSPDACInstance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->channel >= BSP_DAC_CHANNEL_OUTPUT_0) &&
           (instance->channel < BSP_DAC_CHANNEL_COUNT) &&
           (instance->regs != NULL);
}

static bool BSPDACConvertSampleRate(BSP_DAC_Sample_Rate_e sample_rate,
    DL_DAC12_SAMPLES_PER_SECOND *driverlib_rate)
{
    if (driverlib_rate == NULL) {
        return false;
    }

    switch (sample_rate) {
        case BSP_DAC_SAMPLE_RATE_500_HZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_500;
            return true;
        case BSP_DAC_SAMPLE_RATE_1_KHZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_1K;
            return true;
        case BSP_DAC_SAMPLE_RATE_2_KHZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_2K;
            return true;
        case BSP_DAC_SAMPLE_RATE_4_KHZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_4K;
            return true;
        case BSP_DAC_SAMPLE_RATE_8_KHZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_8K;
            return true;
        case BSP_DAC_SAMPLE_RATE_16_KHZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_16K;
            return true;
        case BSP_DAC_SAMPLE_RATE_100_KHZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_100K;
            return true;
        case BSP_DAC_SAMPLE_RATE_200_KHZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_200K;
            return true;
        case BSP_DAC_SAMPLE_RATE_500_KHZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_500K;
            return true;
        case BSP_DAC_SAMPLE_RATE_1_MHZ:
            *driverlib_rate = DL_DAC12_SAMPLES_PER_SECOND_1M;
            return true;
        default:
            return false;
    }
}

static void BSPDACClearStreamingState(BSPDACInstance *instance)
{
    if (instance == NULL) {
        return;
    }

    instance->stream_buffers[0] = NULL;
    instance->stream_buffers[1] = NULL;
    instance->stream_sample_count = 0U;
    instance->stream_active_buffer = 0U;
    instance->stream_buffer_ready[0] = false;
    instance->stream_buffer_ready[1] = false;
    instance->stream_refill_callback = NULL;
    instance->stream_context = NULL;
    instance->streaming = false;
}

/* 该函数不获取 RTOS 锁，供普通接口和 DAC ISR 共用。 */
static void BSPDACStopWaveformHardware(BSPDACInstance *instance)
{
    if ((instance == NULL) || (instance->regs == NULL)) {
        return;
    }

    instance->waveform_running = false;
    DL_DAC12_disableSampleTimeGenerator(instance->regs);
    DL_DAC12_disableDMATrigger(instance->regs);
    DL_DMA_disableChannel(DMA, DMA_DAC_OUTPUT_CHAN_ID);
    DL_DMA_disableInterrupt(DMA,
        DL_DMA_FULL_CH_INTERRUPT_EARLY_CHANNEL0);
    DL_DMA_clearInterruptStatus(DMA,
        DL_DMA_INTERRUPT_CHANNEL0 |
            DL_DMA_FULL_CH_INTERRUPT_EARLY_CHANNEL0);
    DL_DAC12_disableFIFO(instance->regs);
    DL_DAC12_clearInterruptStatus(
        instance->regs, DL_DAC12_INTERRUPT_DMA_DONE |
                            DL_DAC12_INTERRUPT_FIFO_UNDERRUN);
    NVIC_DisableIRQ(DAC12_INT_IRQN);
    NVIC_ClearPendingIRQ(DAC12_INT_IRQN);
    BSPDACClearStreamingState(instance);
}

/*
 * 普通查找表由DMA重复模式自动循环。连续DDS的2048点DMA表也由硬件自动
 * 循环：DMA半程事件释放前半区，DAC DMA_DONE事件释放后半区。
 */
void DAC12_IRQHandler(void)
{
    BSPDACInstance *instance =
        &dac_instances[BSP_DAC_CHANNEL_OUTPUT_0];
    DL_DAC12_IIDX interrupt_index =
        DL_DAC12_getPendingInterrupt(DAC0);

    if (!instance->registered || !instance->waveform_running) {
        return;
    }

    /* 欠载后停止 Sample Timer 和 DMA，避免继续输出不可预测的残缺波形。 */
    if (interrupt_index == DL_DAC12_IIDX_FIFO_UNDERRUN) {
        ++instance->fifo_underrun_count;
        BSPDACStopWaveformHardware(instance);
        DL_DAC12_disable(instance->regs);
        return;
    }
    if (interrupt_index != DL_DAC12_IIDX_DMA_DONE) {
        return;
    }

    if (instance->streaming) {
        /* 完整2048点传输结束，硬件已自动从前半区重新开始。 */
        BSPDACAdvanceStreamingBuffer(instance, 1U);
    }
}

/* DMA_CH0走到双缓冲区中点后，后半区继续输出，前半区可以安全回填。 */
void BSPDACHandleDMAEarlyInterrupt(void)
{
    BSPDACInstance *instance =
        &dac_instances[BSP_DAC_CHANNEL_OUTPUT_0];

    if (instance->registered && instance->waveform_running &&
        instance->streaming) {
        BSPDACAdvanceStreamingBuffer(instance, 0U);
    }
}

static void BSPDACAdvanceStreamingBuffer(
    BSPDACInstance *instance, uint8_t completed_buffer)
{
    uint8_t next_buffer;
    uint16_t *completed_samples;
    uint16_t *next_samples;
    BSP_DAC_Waveform_Refill_Callback refill_callback;

    if ((instance == NULL) || (completed_buffer > 1U) ||
        (instance->stream_active_buffer != completed_buffer)) {
        if (instance != NULL) {
            ++instance->stream_refill_miss_count;
            BSPDACStopWaveformHardware(instance);
            DL_DAC12_disable(instance->regs);
        }
        return;
    }

    next_buffer = (uint8_t)(completed_buffer ^ 1U);
    completed_samples = instance->stream_buffers[completed_buffer];
    next_samples = instance->stream_buffers[next_buffer];
    refill_callback = instance->stream_refill_callback;
    if ((completed_samples == NULL) || (next_samples == NULL) ||
        (instance->stream_sample_count < 2U) ||
        (refill_callback == NULL) ||
        !instance->stream_buffer_ready[next_buffer]) {
        ++instance->stream_refill_miss_count;
        BSPDACStopWaveformHardware(instance);
        DL_DAC12_disable(instance->regs);
        return;
    }

    instance->stream_buffer_ready[next_buffer] = false;
    instance->stream_active_buffer = next_buffer;
    refill_callback(completed_samples,
        instance->stream_sample_count, instance->stream_context);
}

#endif /* APP_ENABLE_WAVEFORM_OUTPUT_DAC */
