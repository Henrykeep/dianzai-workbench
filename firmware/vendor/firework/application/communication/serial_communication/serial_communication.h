/**
 * @file serial_communication.h
 * @brief Application 层串口初始化、收发和 UART2/UART3 样本订阅接口。
 *
 * UART0 主要用于调试，UART1～UART3 的收发能力由 app_config.h 决定。
 */
#ifndef SERIAL_COMMUNICATION_H
#define SERIAL_COMMUNICATION_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** UART2 样本订阅回调；在 UART2 接收任务上下文执行。 */
typedef void (*SerialCommunicationUART2SampleCallback_t)(
    int16_t sample, void *context);

/** UART3 样本订阅回调；在 UART3 接收任务上下文执行。 */
typedef void (*SerialCommunicationUART3SampleCallback_t)(
    int16_t sample, void *context);

/** UART3 文本行观察者；返回 true 表示该行已消费，不再进入旧的文本解析。 */
typedef bool (*SerialCommunicationUART3LineCallback_t)(
    const uint8_t *data, size_t size, void *context);

/** UART3 可向上位机请求并转换为本地 128 点显示的数据类型。 */
typedef enum {
    /* 十条 LCD 请求：响应为 start、128 个数字、end。 */
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A1 = 0,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A3,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_B1,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_B3,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_1,
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_3,
    SERIAL_COMMUNICATION_UART3_DATA_LSPECT_A,
    SERIAL_COMMUNICATION_UART3_DATA_LSPECT_B,
    SERIAL_COMMUNICATION_UART3_DATA_LAFC,
    SERIAL_COMMUNICATION_UART3_DATA_LPFC,
    /* 六条完整波形请求：上位机返回 800 个裸数字，本地压缩为 128 点。 */
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_A1,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_A3,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_B1,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_B3,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_1,
    SERIAL_COMMUNICATION_UART3_DATA_WAVE_3,
    /* 模型频谱为 800 点，ADC0 原始频谱为 1024 点；本地均压缩为 128 点。 */
    SERIAL_COMMUNICATION_UART3_DATA_SPECT_A,
    SERIAL_COMMUNICATION_UART3_DATA_SPECT_B,
    SERIAL_COMMUNICATION_UART3_DATA_SPECTRUM,
    /* 原始幅频和相频曲线各返回 496 个裸数字。 */
    SERIAL_COMMUNICATION_UART3_DATA_AFC,
    SERIAL_COMMUNICATION_UART3_DATA_PFC,
    SERIAL_COMMUNICATION_UART3_DATA_COUNT
} SerialCommunicationUART3DataType_e;

/** UART3 的前置采集和 start + 128 点 + end 请求事务状态。 */
typedef enum {
    SERIAL_COMMUNICATION_UART3_TRANSACTION_IDLE = 0,
    /* 等待 sep1/sep2 模型建立完成。 */
    SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL,
    /* 等待 sweep1 扫频完成。 */
    SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_SWEEP,
    /* 已发送最终查询命令，正在接收并校验数字响应。 */
    SERIAL_COMMUNICATION_UART3_TRANSACTION_COLLECTING,
    SERIAL_COMMUNICATION_UART3_TRANSACTION_COMPLETE,
    /* 上位机明确返回 error 或错误提示。 */
    SERIAL_COMMUNICATION_UART3_TRANSACTION_REMOTE_ERROR,
    /* 帧标志、数值格式、点数或本地发布不符合协议。 */
    SERIAL_COMMUNICATION_UART3_TRANSACTION_PROTOCOL_ERROR,
    /* 准备或收数超过对应本地截止时间。 */
    SERIAL_COMMUNICATION_UART3_TRANSACTION_TIMEOUT
} SerialCommunicationUART3TransactionStatus_e;

/** UART3 外部频谱事务状态。 */
typedef enum {
    SERIAL_COMMUNICATION_UART3_SPECTRUM_IDLE = 0,
    SERIAL_COMMUNICATION_UART3_SPECTRUM_COLLECTING,
    SERIAL_COMMUNICATION_UART3_SPECTRUM_COMPLETE,
    SERIAL_COMMUNICATION_UART3_SPECTRUM_ERROR
} SerialCommunicationUART3SpectrumStatus_e;

/** 初始化 TX-only UART0 调试串口，并通过 UART0 输出首次初始化成功提示。 */
bool SerialCommunicationUART0Init(void);

/** 初始化 UART1 并创建接收任务；APP_ENABLE_UART1=0U 时返回 false。 */
bool SerialCommunicationUART1Init(void);

/** 初始化 UART2 并创建接收任务；APP_ENABLE_UART2=0U 时返回 false。 */
bool SerialCommunicationUART2Init(void);

/** 初始化 UART3 并创建接收任务；APP_ENABLE_UART3=0U 时返回 false。 */
bool SerialCommunicationUART3Init(void);

/** 初始化 UART0 调试口，以及 app_config.h 中启用的 UART1～UART3。 */
bool SerialCommunicationInit(void);

/** 通过 UART0 轮询调试串口发送一段数据。 */
bool SerialCommunicationUART0Send(const uint8_t *data, size_t size);

/** 通过 UART1 DMA 发送一段数据。 */
bool SerialCommunicationUART1Send(const uint8_t *data, size_t size);

/** 通过 UART2 DMA 发送一段数据。 */
bool SerialCommunicationUART2Send(const uint8_t *data, size_t size);

/** 通过 UART3 DMA 发送一段数据。 */
bool SerialCommunicationUART3Send(const uint8_t *data, size_t size);

/** 通过 UART3 请求默认的 lwavea1 波形，保留给已有调用兼容。 */
bool SerialCommunicationUART3RequestWaveform(void);

/** 通过 UART3 请求默认的 lspecta 频谱，保留给已有调用兼容。 */
bool SerialCommunicationUART3RequestSpectrum(void);

/**
 * 发送指定数据命令，并启动带帧 128 点或固定长度裸数字接收事务。
 * 命令使用 CRLF 结束；上一事务尚未结束时返回 false。
 */
bool SerialCommunicationUART3RequestData(
    SerialCommunicationUART3DataType_e type);

/**
 * 先按数据类型执行 sep1、sep2 或 sweep1，准备成功后自动发送数据请求。
 * 该接口用于用户明确触发的重新测量；上一请求仍活动时返回 false。
 */
bool SerialCommunicationUART3RequestPreparedData(
    SerialCommunicationUART3DataType_e type);

/**
 * 取消当前本地 UART3 请求状态，供页面退出或切换来源时丢弃迟到响应。
 * 该操作不能中止上位机已经开始的 sep 或 sweep 运算。
 */
void SerialCommunicationUART3CancelRequest(void);

/** 返回最近一次 UART3 数据请求的完整事务状态。 */
SerialCommunicationUART3TransactionStatus_e
SerialCommunicationUART3GetTransactionStatus(void);

/** 返回最近一次 UART3 外部频谱事务状态。 */
SerialCommunicationUART3SpectrumStatus_e
SerialCommunicationUART3GetSpectrumStatus(void);

/** 返回指定串口因接收缓冲区满而累计丢弃的字节数。 */
uint32_t SerialCommunicationGetDroppedReceiveCount(
    uint8_t uart_number);

/** 返回指定串口累计的发送超时或底层发送失败次数。 */
uint32_t SerialCommunicationGetTransmitFailureCount(
    uint8_t uart_number);

/** 订阅通过 AA + int16 大端 + 55 校验后的 UART2 样本；UART2 关闭时失败。 */
bool SerialCommunicationUART2SubscribeSample(
    SerialCommunicationUART2SampleCallback_t callback, void *context);

/**
 * 取消一个完全匹配 callback/context 的 UART2 样本订阅。
 * @warning UART2 任务可能已经取得回调快照，因此返回后最多还会回调一次；context
 * 必须保持有效，直到调用方确认当前样本分发结束。
 */
bool SerialCommunicationUART2UnsubscribeSample(
    SerialCommunicationUART2SampleCallback_t callback, void *context);

/** 订阅 UART3 二进制帧或 ASCII 电压行解析出的样本；UART3 关闭时失败。 */
bool SerialCommunicationUART3SubscribeSample(
    SerialCommunicationUART3SampleCallback_t callback, void *context);

/** 取消一个完全匹配 callback/context 的 UART3 样本订阅。 */
bool SerialCommunicationUART3UnsubscribeSample(
    SerialCommunicationUART3SampleCallback_t callback, void *context);

/** 注册 UART3 文本行观察者。 */
bool SerialCommunicationUART3SubscribeLine(
    SerialCommunicationUART3LineCallback_t callback, void *context);

/** 移除完全匹配的 UART3 文本行观察者。 */
bool SerialCommunicationUART3UnsubscribeLine(
    SerialCommunicationUART3LineCallback_t callback, void *context);

#endif
