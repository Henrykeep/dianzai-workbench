/**
 * @file adc_justfloat.h
 * @brief 将测量窗口转换为 VOFA+ JustFloat 帧并通过 UART2 发送。
 *
 * 发送任务只消费已经完成的测量结果，不直接参与 ADC 采样时序。
 */
#ifndef ADC_JUSTFLOAT_H
#define ADC_JUSTFLOAT_H

#include <stdbool.h>
#include <stddef.h>

/** UART2 JustFloat 发送任务可选择的数据来源。ADC 来源均取单次测量最后 128 点。 */
typedef enum {
    ADC_SAMPLING_UART2_SOURCE_PA27 = 0,
    ADC_SAMPLING_UART2_SOURCE_PA21,
    ADC_SAMPLING_UART2_SOURCE_CUSTOM,
    ADC_SAMPLING_UART2_SOURCE_COUNT
} ADCSamplingUART2Source_e;

/** 兼容旧接口名称的运行期枚举别名；启动编译配置使用数值 0U/1U。 */
#define ADC_JUSTFLOAT_SOURCE_PA27 \
    ADC_SAMPLING_UART2_SOURCE_PA27
#define ADC_JUSTFLOAT_SOURCE_PA21 \
    ADC_SAMPLING_UART2_SOURCE_PA21
#define ADC_JUSTFLOAT_SOURCE_CUSTOM \
    ADC_SAMPLING_UART2_SOURCE_CUSTOM

/** 自定义 JustFloat 浮点样本批量读取回调。 */
typedef bool (*ADCSamplingUART2CustomSourceRead_t)(float *samples,
    size_t capacity, size_t *sample_count, void *context);

/** 订阅完整窗口测量结果，并创建 UART2 JustFloat 静态发送任务。 */
bool ADCJustFloatInit(void);

/** 选择 PA27、PA21 或已注册的自定义数据源。 */
bool ADCSamplingUART2SetSource(ADCSamplingUART2Source_e source);

/** 返回当前 UART2 JustFloat 数据源。 */
ADCSamplingUART2Source_e ADCSamplingUART2GetSource(void);

/** 注册并立即选择自定义浮点数据源。 */
/*
 * 回调可能已被发送任务快照并正在锁外执行；替换来源后，旧 context 至少应保持
 * 到一个发送等待周期结束。需要严格回收确认时，由调用方自行增加引用计数/握手。
 */
bool ADCSamplingUART2SetCustomSource(
    ADCSamplingUART2CustomSourceRead_t read, void *context);

/** 返回发送任务是否已创建，且当前数据源已启用。 */
bool ADCJustFloatIsReady(void);

#endif
