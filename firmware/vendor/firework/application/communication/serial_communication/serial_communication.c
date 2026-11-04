/*
 * Application 串口层把底层串口驱动包装成统一的初始化、发送和接收任务。
 * UART2 支持 AA + 大端 int16 + 55 样本帧；UART3 默认按 CR/LF 结尾的
 * ASCII 电压行解析并向订阅者分发，也可通过 app_config.h 重新启用二进制帧。
 */
#include "application/communication/serial_communication/serial_communication.h"

#include <stdint.h>
#include <string.h>

#include "FreeRTOS.h"
#include "task.h"

#include "application/app_config.h"
#include "application/task/task_manager.h"
#if APP_ENABLE_UART3_SPECTRUM != 0U
#include "modules/fft/fft_analysis.h"
#endif
#include "modules/serial/serial.h"

/* 各串口协议的固定缓冲容量、帧标记和 UART3 分阶段超时参数。 */
#define SERIAL_RECEIVE_BUFFER_SIZE     (64U)
#define SERIAL_PROTOCOL_HEADER_1       (0xAAU)
#define SERIAL_PROTOCOL_HEADER_2       (0x55U)
#define SERIAL_PROTOCOL_MAX_PAYLOAD    (32U)
#define SERIAL_UART3_STRING_BUFFER_SIZE (512U)
#define SERIAL_UART2_DMA_RX_SIZE         (2U)
#define SERIAL_UART2_FRAME_START          (0xAAU)
#define SERIAL_UART2_FRAME_END            (0x55U)
#define SERIAL_UART2_SAMPLE_SUBSCRIBER_COUNT (4U)
#define SERIAL_UART3_FRAME_START          (0xAAU)
#define SERIAL_UART3_FRAME_END            (0x55U)
#define SERIAL_UART3_SAMPLE_SUBSCRIBER_COUNT (4U)
#define SERIAL_UART3_LINE_SUBSCRIBER_COUNT   (2U)
#define SERIAL_UART3_TRANSACTION_POINT_COUNT (128U)
#define SERIAL_UART3_TRANSACTION_TIMEOUT_MS  (2000UL)
#define SERIAL_UART3_RAW_TRANSACTION_TIMEOUT_MS (15000UL)
#define SERIAL_UART3_MODEL_PREPARE_TIMEOUT_MS (5000UL)
#define SERIAL_UART3_SWEEP_PREPARE_TIMEOUT_MS (30000UL)
#define SERIAL_UART3_RECEIVE_POLL_MS          (50UL)

/*
 * UART0 调试输出总开关：
 * 1U：启用 UART0 注册和调试信息发送。
 * 0U：关闭所有模块的 UART0 输出，但不影响 UART1～UART3 的业务收发。
 */
#define SERIAL_UART0_DEBUG_OUTPUT_ENABLED APP_ENABLE_UART0_DEBUG

/*
 * serial_communication 模块调试信息开关：
 * 1U：输出 UART0～UART3 初始化成功、UART1 RX、UART3 STRING 等提示。
 * 0U：只关闭本文件产生的提示，不影响其他模块使用 UART0。
 */
#define SERIAL_COMMUNICATION_DEBUG_OUTPUT_ENABLED (1U)

/* UART1 自定义帧协议的逐字节解析阶段。 */
typedef enum {
    SERIAL_PROTOCOL_WAIT_HEADER_1 = 0,
    SERIAL_PROTOCOL_WAIT_HEADER_2,
    SERIAL_PROTOCOL_READ_LENGTH,
    SERIAL_PROTOCOL_READ_COMMAND,
    SERIAL_PROTOCOL_READ_PAYLOAD,
    SERIAL_PROTOCOL_READ_CHECKSUM
} SerialProtocolState_e;

/* UART1 解析器跨多次 SerialReceive() 调用保留半包状态。 */
typedef struct {
    SerialProtocolState_e state;
    uint8_t payload_length;
    uint8_t payload_index;
    uint8_t command;
    uint8_t checksum;
    uint8_t payload[SERIAL_PROTOCOL_MAX_PAYLOAD];
} SerialProtocolParser;

/* UART3 文本按 CR、LF 或 NUL 分行；溢出后丢弃到下一个行结束符。 */
typedef struct {
    uint8_t data[SERIAL_UART3_STRING_BUFFER_SIZE];
    size_t length;
    bool overflowed;
} SerialStringParser;

/* UART2 固定 AA + int16 大端 + 55 帧的解析阶段。 */
typedef enum {
    SERIAL_UART2_WAIT_START = 0,
    SERIAL_UART2_READ_HIGH_BYTE,
    SERIAL_UART2_READ_LOW_BYTE,
    SERIAL_UART2_WAIT_END
} SerialUART2FrameState_e;

/* UART2 帧解析器只需暂存一个 16 位样本。 */
typedef struct {
    SerialUART2FrameState_e state;
    uint8_t sample_bytes[SERIAL_UART2_DMA_RX_SIZE];
} SerialUART2FrameParser;

/* UART3 可选二进制波形帧与 UART2 使用相同的四阶段解析方式。 */
typedef enum {
    SERIAL_UART3_WAIT_START = 0,
    SERIAL_UART3_READ_HIGH_BYTE,
    SERIAL_UART3_READ_LOW_BYTE,
    SERIAL_UART3_WAIT_END
} SerialUART3FrameState_e;

/* UART3 二进制帧解析器只在启用对应兼容开关时参与收包。 */
typedef struct {
    SerialUART3FrameState_e state;
    uint8_t sample_bytes[2];
} SerialUART3FrameParser;

/* UART3 数值事务在等待帧头、收点和等待帧尾之间推进。 */
typedef enum {
    SERIAL_UART3_TRANSACTION_WAIT_START = 0,
    SERIAL_UART3_TRANSACTION_READ_POINTS,
    SERIAL_UART3_TRANSACTION_WAIT_END,
    SERIAL_UART3_TRANSACTION_INACTIVE
} SerialUART3TransactionParserState_e;

/* 最终数据请求前可能需要上位机先建立模型或完成扫频。 */
typedef enum {
    SERIAL_UART3_PREPARATION_NONE = 0,
    SERIAL_UART3_PREPARATION_SEP1,
    SERIAL_UART3_PREPARATION_SEP2,
    SERIAL_UART3_PREPARATION_SWEEP1
} SerialUART3Preparation_e;

/* 订阅槽同时保存回调及其不透明上下文，二者共同标识一项订阅。 */
typedef struct {
    SerialCommunicationUART2SampleCallback_t callback;
    void *context;
} SerialUART2SampleSubscriber;

/* UART3 样本订阅与文本行订阅使用独立槽位，互不占用容量。 */
typedef struct {
    SerialCommunicationUART3SampleCallback_t callback;
    void *context;
} SerialUART3SampleSubscriber;

/* 文本观察者返回消费标志，用于阻止同一行继续进入兼容解析器。 */
typedef struct {
    SerialCommunicationUART3LineCallback_t callback;
    void *context;
} SerialUART3LineSubscriber;

static SerialInstance *serial_devices[SERIAL_DEVICE_COUNT];
#if APP_ENABLE_UART1 != 0U
static bool uart1_receive_task_created;
#endif
#if APP_ENABLE_UART2 != 0U
static bool uart2_receive_task_created;
#endif
#if APP_ENABLE_UART3 != 0U
static bool uart3_receive_task_created;
#endif
#if APP_ENABLE_UART1 != 0U
static SerialProtocolParser uart1_protocol_parser;
#endif
#if APP_ENABLE_UART2 != 0U
static SerialUART2FrameParser uart2_frame_parser;
#endif
#if APP_ENABLE_UART3 != 0U
/*
 * UART3 接收任务推进下列事务状态；页面任务通过临界区读取、取消或发起事务。
 * parser_state 描述行解析位置，status 描述对外可见生命周期，二者不可混用。
 */
static SerialStringParser uart3_string_parser;
static SerialUART3FrameParser uart3_frame_parser;
static volatile SerialUART3TransactionParserState_e
    uart3_transaction_parser_state = SERIAL_UART3_TRANSACTION_INACTIVE;
static volatile SerialCommunicationUART3TransactionStatus_e
    uart3_transaction_status = SERIAL_COMMUNICATION_UART3_TRANSACTION_IDLE;
static SerialCommunicationUART3DataType_e uart3_transaction_type =
    SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A1;
static SerialUART3Preparation_e uart3_preparation =
    SERIAL_UART3_PREPARATION_NONE;
/* 保存有符号 fixed-5 的原始32位表示；频谱类型保证所有值非负。 */
static uint32_t uart3_transaction_points[
    SERIAL_UART3_TRANSACTION_POINT_COUNT];
static size_t uart3_transaction_point_count;
/* 使用绝对 Tick 截止时间，Tick 回绕由有符号差值比较处理。 */
static TickType_t uart3_transaction_deadline;
#if APP_ENABLE_UART3_SPECTRUM != 0U
static uint32_t uart3_spectrum_source_sequence;
#endif
#endif
#if APP_ENABLE_UART2 != 0U
static SerialUART2SampleSubscriber uart2_sample_subscribers[
    SERIAL_UART2_SAMPLE_SUBSCRIBER_COUNT];
#endif
#if APP_ENABLE_UART3 != 0U
static SerialUART3SampleSubscriber uart3_sample_subscribers[
    SERIAL_UART3_SAMPLE_SUBSCRIBER_COUNT];
static SerialUART3LineSubscriber uart3_line_subscribers[
    SERIAL_UART3_LINE_SUBSCRIBER_COUNT];
#endif
static uint32_t serial_transmit_failure_counts[SERIAL_DEVICE_COUNT];

static bool SerialCommunicationDeviceInit(Serial_Device_e device);
static bool SerialCommunicationDeviceSend(
    Serial_Device_e device, const uint8_t *data, size_t size);
static void SerialCommunicationDebugSend(
    const uint8_t *data, size_t size);
#if APP_ENABLE_UART1 != 0U
static void SerialCommunicationUART1ReceiveTask(void *argument);
static void SerialCommunicationUART1ProcessReceivedData(
    const uint8_t *data, size_t size);
#endif
#if APP_ENABLE_UART2 != 0U
static void SerialCommunicationUART2ReceiveTask(void *argument);
static void SerialCommunicationUART2ProcessReceivedData(
    const uint8_t *data, size_t size);
#endif
#if APP_ENABLE_UART3 != 0U
static void SerialCommunicationUART3ReceiveTask(void *argument);
static void SerialCommunicationUART3ProcessReceivedData(
    const uint8_t *data, size_t size);
#endif
#if APP_ENABLE_UART2 != 0U
static void SerialCommunicationUART2FrameConsumeByte(uint8_t data);
static void SerialCommunicationUART2HandleSample(const uint8_t *data);
#endif
#if APP_ENABLE_UART3 != 0U
static void SerialCommunicationUART3ConsumeByte(uint8_t data);
static void SerialCommunicationUART3FrameConsumeByte(uint8_t data);
static void SerialCommunicationUART3PublishSample(int16_t sample);
#if APP_ENABLE_UART3_ASCII_WAVEFORM != 0U
static bool SerialCommunicationUART3ParseVoltageMillivolts(
    const uint8_t *data, size_t size, int16_t *sample);
#endif
static bool SerialCommunicationUART3ParseSignedFixed5(
    const uint8_t *data, size_t size, int32_t *fixed_5);
static bool SerialCommunicationUART3StartDataTransaction(
    SerialCommunicationUART3DataType_e type, bool already_reserved);
static bool SerialCommunicationUART3HandlePreparationString(
    const uint8_t *data, size_t size);
static bool SerialCommunicationUART3TransactionIsActive(
    SerialCommunicationUART3TransactionStatus_e status);
static SerialUART3Preparation_e SerialCommunicationUART3PreparationForType(
    SerialCommunicationUART3DataType_e type);
static bool SerialCommunicationUART3StringEquals(
    const uint8_t *data, size_t size, const char *expected);
static bool SerialCommunicationUART3StringStartsWith(
    const uint8_t *data, size_t size, const char *prefix);
static bool SerialCommunicationUART3StringContains(
    const uint8_t *data, size_t size, const char *fragment);
static bool SerialCommunicationUART3HandleTransactionString(
    const uint8_t *data, size_t size);
static void SerialCommunicationUART3CheckTransactionTimeout(void);
static void SerialCommunicationUART3SetTransactionError(
    SerialCommunicationUART3TransactionStatus_e status);
static bool SerialCommunicationUART3CompleteTransaction(void);
static bool SerialCommunicationUART3DataTypeIsSpectrum(
    SerialCommunicationUART3DataType_e type);
static bool SerialCommunicationUART3DataTypeIsFramed(
    SerialCommunicationUART3DataType_e type);
static size_t SerialCommunicationUART3DataSourcePointCount(
    SerialCommunicationUART3DataType_e type);
static void SerialCommunicationUART3StoreTransactionPoint(
    int32_t fixed_5);
static bool SerialCommunicationUART3PublishLine(
    const uint8_t *data, size_t size);
static void SerialCommunicationUART3PublishFixed5Sample(uint32_t raw_sample);
static void SerialCommunicationUART3HandleString(
    const uint8_t *data, size_t size);
#endif
#if APP_ENABLE_UART1 != 0U
static void SerialCommunicationUART1ProtocolConsumeByte(uint8_t data);
static void SerialCommunicationUART1HandleFrame(
    uint8_t command, const uint8_t *payload, uint8_t payload_length);
static bool SerialCommunicationUART1SendFrame(
    uint8_t command, const uint8_t *payload, uint8_t payload_length);
static void SerialCommunicationUART1ProtocolReset(void);
#endif

/* 初始化 UART0 调试串口，并在首次注册成功后输出提示。 */
bool SerialCommunicationUART0Init(void)
{
    static const uint8_t init_message[] = "UART0 INIT OK\r\n";

    if (SERIAL_UART0_DEBUG_OUTPUT_ENABLED == 0U) {
        return true;
    }

    if (serial_devices[SERIAL_DEVICE_DEBUG] != NULL) {
        return true;
    }

    if (!SerialCommunicationDeviceInit(SERIAL_DEVICE_DEBUG)) {
        return false;
    }

    /* UART0 使用轮询发送，不依赖调度器或 DMA 完成中断。 */
    SerialCommunicationDebugSend(
        init_message, sizeof(init_message) - 1U);
    return true;
}

/* 初始化 UART1，并创建 UART1 的数据接收任务。 */
bool SerialCommunicationUART1Init(void)
{
#if APP_ENABLE_UART1 == 0U
    return false;
#else
    static const uint8_t init_message[] = "UART1 INIT OK\r\n";

    if (!SerialCommunicationDeviceInit(SERIAL_DEVICE_UART1)) {
        return false;
    }

    if (uart1_receive_task_created) {
        return true;
    }

    if (ApplicationTaskCreate(APPLICATION_TASK_SERIAL_UART1_RX,
            SerialCommunicationUART1ReceiveTask, NULL) == NULL) {
        return false;
    }

    uart1_receive_task_created = true;
    SerialCommunicationDebugSend(
        init_message, sizeof(init_message) - 1U);
    return true;
#endif
}

/* 初始化 UART2，并创建 UART2 的数据接收任务。 */
bool SerialCommunicationUART2Init(void)
{
#if APP_ENABLE_UART2 == 0U
    return false;
#else
    static const uint8_t init_message[] = "UART2 INIT OK\r\n";

    if (!SerialCommunicationDeviceInit(SERIAL_DEVICE_UART2)) {
        return false;
    }

    if (uart2_receive_task_created) {
        return true;
    }

    if (ApplicationTaskCreate(APPLICATION_TASK_SERIAL_UART2_RX,
            SerialCommunicationUART2ReceiveTask, NULL) == NULL) {
        return false;
    }

    uart2_receive_task_created = true;
    SerialCommunicationDebugSend(
        init_message, sizeof(init_message) - 1U);
    return true;
#endif
}

/* 初始化 UART3，并创建 UART3 的数据接收任务。 */
bool SerialCommunicationUART3Init(void)
{
#if APP_ENABLE_UART3 == 0U
    return false;
#else
    static const uint8_t init_message[] = "UART3 INIT OK\r\n";

    if (!SerialCommunicationDeviceInit(SERIAL_DEVICE_UART3)) {
        return false;
    }

    if (uart3_receive_task_created) {
        return true;
    }

    if (ApplicationTaskCreate(APPLICATION_TASK_SERIAL_UART3_RX,
            SerialCommunicationUART3ReceiveTask, NULL) == NULL) {
        return false;
    }

    uart3_receive_task_created = true;
    SerialCommunicationDebugSend(
        init_message, sizeof(init_message) - 1U);
    return true;
#endif
}

/* 先处理 UART0，再按编译开关初始化 UART1～UART3。 */
bool SerialCommunicationInit(void)
{
    if (!SerialCommunicationUART0Init()) {
        return false;
    }
#if APP_ENABLE_UART1 != 0U
    if (!SerialCommunicationUART1Init()) {
        return false;
    }
#endif
#if APP_ENABLE_UART2 != 0U
    if (!SerialCommunicationUART2Init()) {
        return false;
    }
#endif
#if APP_ENABLE_UART3 != 0U
    if (!SerialCommunicationUART3Init()) {
        return false;
    }
#endif

    return true;
}

/* 通过 UART0 发送指定长度的调试数据。 */
bool SerialCommunicationUART0Send(const uint8_t *data, size_t size)
{
    /* 关闭调试输出时静默丢弃数据，不让调用方误认为发送失败。 */
    if (SERIAL_UART0_DEBUG_OUTPUT_ENABLED == 0U) {
        (void)data;
        (void)size;
        return true;
    }

    return SerialCommunicationDeviceSend(
        SERIAL_DEVICE_DEBUG, data, size);
}

/* 通过 UART1 发送指定长度的数据。 */
bool SerialCommunicationUART1Send(const uint8_t *data, size_t size)
{
    return SerialCommunicationDeviceSend(
        SERIAL_DEVICE_UART1, data, size);
}

/* 通过 UART2 发送指定长度的数据。 */
bool SerialCommunicationUART2Send(const uint8_t *data, size_t size)
{
    return SerialCommunicationDeviceSend(
        SERIAL_DEVICE_UART2, data, size);
}

/* 通过 UART3 发送指定长度的数据。 */
bool SerialCommunicationUART3Send(const uint8_t *data, size_t size)
{
    return SerialCommunicationDeviceSend(
        SERIAL_DEVICE_UART3, data, size);
}

/* 请求默认的 A 通道基波波形；具体事务由通用请求函数管理。 */
bool SerialCommunicationUART3RequestWaveform(void)
{
#if APP_ENABLE_UART3_WAVEFORM_REQUEST == 0U
    return false;
#else
    return SerialCommunicationUART3RequestData(
        SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A1);
#endif
}

/* 请求默认的 A 通道模型频谱。 */
bool SerialCommunicationUART3RequestSpectrum(void)
{
#if APP_ENABLE_UART3_SPECTRUM == 0U
    return false;
#else
    return SerialCommunicationUART3RequestData(
        SERIAL_COMMUNICATION_UART3_DATA_LSPECT_A);
#endif
}

/* 发送最终数据命令；l 前缀使用帧格式，其余命令接收固定长度裸数字流。 */
#if APP_ENABLE_UART3 != 0U
static bool SerialCommunicationUART3StartDataTransaction(
    SerialCommunicationUART3DataType_e type, bool already_reserved)
{
    static const uint8_t *const requests[
        SERIAL_COMMUNICATION_UART3_DATA_COUNT] = {
        (const uint8_t *)"lwavea1\r\n",
        (const uint8_t *)"lwavea3\r\n",
        (const uint8_t *)"lwaveb1\r\n",
        (const uint8_t *)"lwaveb3\r\n",
        (const uint8_t *)"lwave1\r\n",
        (const uint8_t *)"lwave3\r\n",
        (const uint8_t *)"lspecta\r\n",
        (const uint8_t *)"lspectb\r\n",
        (const uint8_t *)"lafc\r\n",
        (const uint8_t *)"lpfc\r\n",
        (const uint8_t *)"wavea1\r\n",
        (const uint8_t *)"wavea3\r\n",
        (const uint8_t *)"waveb1\r\n",
        (const uint8_t *)"waveb3\r\n",
        (const uint8_t *)"wave1\r\n",
        (const uint8_t *)"wave3\r\n",
        (const uint8_t *)"specta\r\n",
        (const uint8_t *)"spectb\r\n",
        (const uint8_t *)"spectrum\r\n",
        (const uint8_t *)"afc\r\n",
        (const uint8_t *)"pfc\r\n"
    };
    static const uint8_t request_sizes[
        SERIAL_COMMUNICATION_UART3_DATA_COUNT] = {
        9U, 9U, 9U, 9U, 8U, 8U, 9U, 9U, 6U, 6U,
        8U, 8U, 8U, 8U, 7U, 7U, 8U, 8U, 10U, 5U, 5U
    };
    bool transaction_busy = false;

    if ((type < SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A1) ||
        (type >= SERIAL_COMMUNICATION_UART3_DATA_COUNT)) {
        return false;
    }
#if APP_ENABLE_UART3_SPECTRUM == 0U
    if (SerialCommunicationUART3DataTypeIsSpectrum(type)) {
        return false;
    }
#endif
#if APP_ENABLE_UART3_WAVEFORM_REQUEST == 0U
    if (!SerialCommunicationUART3DataTypeIsSpectrum(type)) {
        return false;
    }
#endif

    taskENTER_CRITICAL();
    if (already_reserved) {
        transaction_busy =
            ((uart3_transaction_status !=
                 SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL) &&
             (uart3_transaction_status !=
                 SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_SWEEP)) ||
            (uart3_transaction_type != type);
    } else {
        transaction_busy = SerialCommunicationUART3TransactionIsActive(
            uart3_transaction_status);
    }
    if (!transaction_busy) {
        uart3_transaction_type = type;
        uart3_preparation = SERIAL_UART3_PREPARATION_NONE;
        uart3_transaction_point_count = 0U;
        uart3_transaction_parser_state =
            SerialCommunicationUART3DataTypeIsFramed(type)
                ? SERIAL_UART3_TRANSACTION_WAIT_START
                : SERIAL_UART3_TRANSACTION_READ_POINTS;
        uart3_transaction_status =
            SERIAL_COMMUNICATION_UART3_TRANSACTION_COLLECTING;
        uart3_transaction_deadline = xTaskGetTickCount() +
            pdMS_TO_TICKS(
                SerialCommunicationUART3DataTypeIsFramed(type)
                    ? SERIAL_UART3_TRANSACTION_TIMEOUT_MS
                    : SERIAL_UART3_RAW_TRANSACTION_TIMEOUT_MS);
        memset(uart3_transaction_points, 0,
               sizeof(uart3_transaction_points));
    }
    taskEXIT_CRITICAL();
    if (transaction_busy) {
        return false;
    }

    if (!SerialCommunicationUART3Send(
            requests[type], request_sizes[type])) {
        SerialCommunicationUART3SetTransactionError(
            SERIAL_COMMUNICATION_UART3_TRANSACTION_PROTOCOL_ERROR);
        return false;
    }
    return true;
}
#endif

/* 直接查询上位机中已经存在的数据，不触发 sep 或 sweep。 */
bool SerialCommunicationUART3RequestData(
    SerialCommunicationUART3DataType_e type)
{
#if APP_ENABLE_UART3 == 0U
    (void)type;
    return false;
#else
    return SerialCommunicationUART3StartDataTransaction(type, false);
#endif
}

/* 先触发模型采集或扫频，看到完成标志后再自动发送最终查询命令。 */
bool SerialCommunicationUART3RequestPreparedData(
    SerialCommunicationUART3DataType_e type)
{
#if APP_ENABLE_UART3 == 0U
    (void)type;
    return false;
#else
    static const uint8_t sep1_request[] = "sep1\r\n";
    static const uint8_t sep2_request[] = "sep2\r\n";
    static const uint8_t sweep1_request[] = "sweep1\r\n";
    const uint8_t *request;
    size_t request_size;
    TickType_t timeout_ticks;
    SerialUART3Preparation_e preparation =
        SerialCommunicationUART3PreparationForType(type);
    bool transaction_busy;

    if (preparation == SERIAL_UART3_PREPARATION_NONE) {
        return false;
    }
#if APP_ENABLE_UART3_SPECTRUM == 0U
    if (SerialCommunicationUART3DataTypeIsSpectrum(type)) {
        return false;
    }
#endif
#if APP_ENABLE_UART3_WAVEFORM_REQUEST == 0U
    if (!SerialCommunicationUART3DataTypeIsSpectrum(type)) {
        return false;
    }
#endif

    switch (preparation) {
        case SERIAL_UART3_PREPARATION_SEP1:
            request = sep1_request;
            request_size = sizeof(sep1_request) - 1U;
            timeout_ticks =
                pdMS_TO_TICKS(SERIAL_UART3_MODEL_PREPARE_TIMEOUT_MS);
            break;
        case SERIAL_UART3_PREPARATION_SEP2:
            request = sep2_request;
            request_size = sizeof(sep2_request) - 1U;
            timeout_ticks =
                pdMS_TO_TICKS(SERIAL_UART3_MODEL_PREPARE_TIMEOUT_MS);
            break;
        case SERIAL_UART3_PREPARATION_SWEEP1:
            request = sweep1_request;
            request_size = sizeof(sweep1_request) - 1U;
            timeout_ticks =
                pdMS_TO_TICKS(SERIAL_UART3_SWEEP_PREPARE_TIMEOUT_MS);
            break;
        case SERIAL_UART3_PREPARATION_NONE:
        default:
            return false;
    }

    taskENTER_CRITICAL();
    transaction_busy = SerialCommunicationUART3TransactionIsActive(
        uart3_transaction_status);
    if (!transaction_busy) {
        uart3_transaction_type = type;
        uart3_preparation = preparation;
        uart3_transaction_point_count = 0U;
        uart3_transaction_parser_state =
            SERIAL_UART3_TRANSACTION_INACTIVE;
        uart3_transaction_status =
            (preparation == SERIAL_UART3_PREPARATION_SWEEP1)
                ? SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_SWEEP
                : SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL;
        uart3_transaction_deadline = xTaskGetTickCount() + timeout_ticks;
    }
    taskEXIT_CRITICAL();
    if (transaction_busy) {
        return false;
    }

    if (!SerialCommunicationUART3Send(request, request_size)) {
        SerialCommunicationUART3SetTransactionError(
            SERIAL_COMMUNICATION_UART3_TRANSACTION_PROTOCOL_ERROR);
        return false;
    }
    return true;
#endif
}

void SerialCommunicationUART3CancelRequest(void)
{
#if APP_ENABLE_UART3 != 0U
    taskENTER_CRITICAL();
    uart3_preparation = SERIAL_UART3_PREPARATION_NONE;
    uart3_transaction_parser_state = SERIAL_UART3_TRANSACTION_INACTIVE;
    uart3_transaction_point_count = 0U;
    uart3_transaction_status =
        SERIAL_COMMUNICATION_UART3_TRANSACTION_IDLE;
    taskEXIT_CRITICAL();
#endif
}

SerialCommunicationUART3TransactionStatus_e
SerialCommunicationUART3GetTransactionStatus(void)
{
#if APP_ENABLE_UART3 != 0U
    SerialCommunicationUART3TransactionStatus_e status;

    taskENTER_CRITICAL();
    status = uart3_transaction_status;
    taskEXIT_CRITICAL();
    return status;
#else
    return SERIAL_COMMUNICATION_UART3_TRANSACTION_IDLE;
#endif
}

SerialCommunicationUART3SpectrumStatus_e
SerialCommunicationUART3GetSpectrumStatus(void)
{
#if APP_ENABLE_UART3_SPECTRUM != 0U
    SerialCommunicationUART3TransactionStatus_e status =
        SerialCommunicationUART3GetTransactionStatus();

    switch (status) {
        case SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL:
        case SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_SWEEP:
        case SERIAL_COMMUNICATION_UART3_TRANSACTION_COLLECTING:
            return SERIAL_COMMUNICATION_UART3_SPECTRUM_COLLECTING;
        case SERIAL_COMMUNICATION_UART3_TRANSACTION_COMPLETE:
            return SERIAL_COMMUNICATION_UART3_SPECTRUM_COMPLETE;
        case SERIAL_COMMUNICATION_UART3_TRANSACTION_REMOTE_ERROR:
        case SERIAL_COMMUNICATION_UART3_TRANSACTION_PROTOCOL_ERROR:
        case SERIAL_COMMUNICATION_UART3_TRANSACTION_TIMEOUT:
            return SERIAL_COMMUNICATION_UART3_SPECTRUM_ERROR;
        case SERIAL_COMMUNICATION_UART3_TRANSACTION_IDLE:
        default:
            return SERIAL_COMMUNICATION_UART3_SPECTRUM_IDLE;
    }
#else
    return SERIAL_COMMUNICATION_UART3_SPECTRUM_IDLE;
#endif
}

uint32_t SerialCommunicationGetDroppedReceiveCount(
    uint8_t uart_number)
{
    Serial_Device_e device;

    if ((uart_number < 1U) || (uart_number > 3U)) {
        return 0UL;
    }
    device = (Serial_Device_e)uart_number;
    return (serial_devices[device] != NULL)
               ? SerialGetDroppedReceiveCount(serial_devices[device])
               : 0UL;
}

uint32_t SerialCommunicationGetTransmitFailureCount(
    uint8_t uart_number)
{
    Serial_Device_e device;

    if (uart_number > 3U) {
        return 0UL;
    }
    device = (Serial_Device_e)uart_number;
    return serial_transmit_failure_counts[device];
}

bool SerialCommunicationUART2SubscribeSample(
    SerialCommunicationUART2SampleCallback_t callback, void *context)
{
#if APP_ENABLE_UART2 != 0U
    size_t index;
    bool result = false;

    if (callback == NULL) {
        return false;
    }

    taskENTER_CRITICAL();
    for (index = 0U;
         index < SERIAL_UART2_SAMPLE_SUBSCRIBER_COUNT; ++index) {
        SerialUART2SampleSubscriber *subscriber =
            &uart2_sample_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            result = true;
            break;
        }
        if (subscriber->callback == NULL) {
            subscriber->context = context;
            subscriber->callback = callback;
            result = true;
            break;
        }
    }
    taskEXIT_CRITICAL();
    return result;
#else
    (void)callback;
    (void)context;
    return false;
#endif
}

bool SerialCommunicationUART2UnsubscribeSample(
    SerialCommunicationUART2SampleCallback_t callback, void *context)
{
#if APP_ENABLE_UART2 != 0U
    size_t index;
    bool result = false;

    if (callback == NULL) {
        return false;
    }

    taskENTER_CRITICAL();
    for (index = 0U;
         index < SERIAL_UART2_SAMPLE_SUBSCRIBER_COUNT; ++index) {
        SerialUART2SampleSubscriber *subscriber =
            &uart2_sample_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            subscriber->callback = NULL;
            subscriber->context = NULL;
            result = true;
            break;
        }
    }
    taskEXIT_CRITICAL();
    return result;
#else
    (void)callback;
    (void)context;
    return false;
#endif
}

bool SerialCommunicationUART3SubscribeSample(
    SerialCommunicationUART3SampleCallback_t callback, void *context)
{
#if APP_ENABLE_UART3 != 0U
    size_t index;
    bool result = false;

    if (callback == NULL) {
        return false;
    }

    taskENTER_CRITICAL();
    for (index = 0U;
         index < SERIAL_UART3_SAMPLE_SUBSCRIBER_COUNT; ++index) {
        SerialUART3SampleSubscriber *subscriber =
            &uart3_sample_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            result = true;
            break;
        }
        if (subscriber->callback == NULL) {
            subscriber->context = context;
            subscriber->callback = callback;
            result = true;
            break;
        }
    }
    taskEXIT_CRITICAL();
    return result;
#else
    (void)callback;
    (void)context;
    return false;
#endif
}

bool SerialCommunicationUART3UnsubscribeSample(
    SerialCommunicationUART3SampleCallback_t callback, void *context)
{
#if APP_ENABLE_UART3 != 0U
    size_t index;
    bool result = false;

    if (callback == NULL) {
        return false;
    }

    taskENTER_CRITICAL();
    for (index = 0U;
         index < SERIAL_UART3_SAMPLE_SUBSCRIBER_COUNT; ++index) {
        SerialUART3SampleSubscriber *subscriber =
            &uart3_sample_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            subscriber->callback = NULL;
            subscriber->context = NULL;
            result = true;
            break;
        }
    }
    taskEXIT_CRITICAL();
    return result;
#else
    (void)callback;
    (void)context;
    return false;
#endif
}

bool SerialCommunicationUART3SubscribeLine(
    SerialCommunicationUART3LineCallback_t callback, void *context)
{
#if APP_ENABLE_UART3 != 0U
    size_t index;
    bool result = false;

    if (callback == NULL) {
        return false;
    }
    taskENTER_CRITICAL();
    for (index = 0U; index < SERIAL_UART3_LINE_SUBSCRIBER_COUNT; ++index) {
        SerialUART3LineSubscriber *subscriber =
            &uart3_line_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            result = true;
            break;
        }
        if (subscriber->callback == NULL) {
            subscriber->context = context;
            subscriber->callback = callback;
            result = true;
            break;
        }
    }
    taskEXIT_CRITICAL();
    return result;
#else
    (void)callback;
    (void)context;
    return false;
#endif
}

bool SerialCommunicationUART3UnsubscribeLine(
    SerialCommunicationUART3LineCallback_t callback, void *context)
{
#if APP_ENABLE_UART3 != 0U
    size_t index;
    bool result = false;

    if (callback == NULL) {
        return false;
    }
    taskENTER_CRITICAL();
    for (index = 0U; index < SERIAL_UART3_LINE_SUBSCRIBER_COUNT; ++index) {
        SerialUART3LineSubscriber *subscriber =
            &uart3_line_subscribers[index];

        if ((subscriber->callback == callback) &&
            (subscriber->context == context)) {
            subscriber->callback = NULL;
            subscriber->context = NULL;
            result = true;
            break;
        }
    }
    taskEXIT_CRITICAL();
    return result;
#else
    (void)callback;
    (void)context;
    return false;
#endif
}

/* 注册指定串口设备，并保存底层串口实例。 */
static bool SerialCommunicationDeviceInit(Serial_Device_e device)
{
    if ((device < SERIAL_DEVICE_DEBUG) || (device >= SERIAL_DEVICE_COUNT)) {
        return false;
    }

    if (serial_devices[device] != NULL) {
        return true;
    }

    serial_devices[device] = SerialRegister(device);
    return serial_devices[device] != NULL;
}

/* 检查发送参数和设备状态，然后调用串口模块发送数据。 */
static bool SerialCommunicationDeviceSend(
    Serial_Device_e device, const uint8_t *data, size_t size)
{
    bool result;

    if ((device < SERIAL_DEVICE_DEBUG) || (device >= SERIAL_DEVICE_COUNT) ||
        (serial_devices[device] == NULL) || (data == NULL) || (size == 0U)) {
        return false;
    }

    result = SerialSend(serial_devices[device], data, size);
    if (!result) {
        ++serial_transmit_failure_counts[device];
    }
    return result;
}

/* 根据本模块调试开关决定是否通过 UART0 输出提示信息。 */
static void SerialCommunicationDebugSend(
    const uint8_t *data, size_t size)
{
    if (SERIAL_COMMUNICATION_DEBUG_OUTPUT_ENABLED != 0U) {
        (void)SerialCommunicationUART0Send(data, size);
    }
}

/* UART1 接收任务：等待接收数据并交给 UART1 协议解析函数。 */
#if APP_ENABLE_UART1 != 0U
static void SerialCommunicationUART1ReceiveTask(void *argument)
{
    /* 接收缓冲区位于任务自己的静态栈中，不与其他 UART 任务共享。 */
    uint8_t receive_buffer[SERIAL_RECEIVE_BUFFER_SIZE];

    (void)argument;

    for (;;) {
        /* 永久阻塞等待数据，空闲时任务不会占用 CPU。 */
        size_t received_size = SerialReceive(
            serial_devices[SERIAL_DEVICE_UART1], receive_buffer,
            sizeof(receive_buffer), SERIAL_WAIT_FOREVER_MS);

        /* 按实际接收长度逐字节送入状态机，半包和粘包由解析器跨批次处理。 */
        if (received_size > 0U) {
            SerialCommunicationUART1ProcessReceivedData(
                receive_buffer, received_size);
        }
    }
}
#endif

/* UART2 接收任务：每次等待 DMA 送来的一个完整双字节采样值。 */
#if APP_ENABLE_UART2 != 0U
static void SerialCommunicationUART2ReceiveTask(void *argument)
{
    /* UART2 DMA 每次向任务提交一个 16 位采样值，即两个字节。 */
    uint8_t receive_buffer[SERIAL_UART2_DMA_RX_SIZE];

    (void)argument;

    for (;;) {
        /* 阻塞等待 DMA 接收完成，由底层串口服务唤醒本任务。 */
        size_t received_size = SerialReceive(
            serial_devices[SERIAL_DEVICE_UART2], receive_buffer,
            sizeof(receive_buffer), SERIAL_WAIT_FOREVER_MS);

        /* DMA 数据必须完整到达，异常长度直接丢弃，避免采样帧发生字节错位。 */
        if (received_size == sizeof(receive_buffer)) {
            SerialCommunicationUART2ProcessReceivedData(
                receive_buffer, received_size);
        }
    }
}
#endif

/* UART3 接收任务：定期唤醒以同时处理字符串和请求事务超时。 */
#if APP_ENABLE_UART3 != 0U
static void SerialCommunicationUART3ReceiveTask(void *argument)
{
    /* UART3 字符串允许分多次到达，解析状态由模块静态对象保存。 */
    uint8_t receive_buffer[SERIAL_RECEIVE_BUFFER_SIZE];

    (void)argument;

    for (;;) {
        /* 有界等待使没有新字节时也能及时结束超时事务。 */
        size_t received_size = SerialReceive(
            serial_devices[SERIAL_DEVICE_UART3], receive_buffer,
            sizeof(receive_buffer), SERIAL_UART3_RECEIVE_POLL_MS);

        /* 将本次收到的字节追加到字符串解析器，跨批次数据由解析状态保留。 */
        if (received_size > 0U) {
            SerialCommunicationUART3ProcessReceivedData(
                receive_buffer, received_size);
        }
        SerialCommunicationUART3CheckTransactionTimeout();
    }
}
#endif

/* 逐字节处理 UART1 数据，使协议解析支持半包和粘包。 */
#if APP_ENABLE_UART1 != 0U
static void SerialCommunicationUART1ProcessReceivedData(
    const uint8_t *data, size_t size)
{
    size_t index;

    for (index = 0U; index < size; ++index) {
        SerialCommunicationUART1ProtocolConsumeByte(data[index]);
    }
}
#endif

/* 将 UART2 DMA 数据逐字节送入带开始和结束标志的帧解析器。 */
#if APP_ENABLE_UART2 != 0U
static void SerialCommunicationUART2ProcessReceivedData(
    const uint8_t *data, size_t size)
{
    size_t index;

    if (data == NULL) {
        return;
    }

    for (index = 0U; index < size; ++index) {
        SerialCommunicationUART2FrameConsumeByte(data[index]);
    }
}
#endif

/* 将 UART3 收到的数据逐字节送入字符串解析器。 */
#if APP_ENABLE_UART3 != 0U
static void SerialCommunicationUART3ProcessReceivedData(
    const uint8_t *data, size_t size)
{
    size_t index;

    /* UART3 逐字节组成字符串，支持半包和粘包。 */
    for (index = 0U; index < size; ++index) {
        SerialCommunicationUART3ConsumeByte(data[index]);
    }
}
#endif

/* 解析 UART2 的 AA + 双字节采样 + 55 帧，并在错误后重新寻找帧头。 */
#if APP_ENABLE_UART2 != 0U
static void SerialCommunicationUART2FrameConsumeByte(uint8_t data)
{
    switch (uart2_frame_parser.state) {
        case SERIAL_UART2_WAIT_START:
            if (data == SERIAL_UART2_FRAME_START) {
                uart2_frame_parser.state = SERIAL_UART2_READ_HIGH_BYTE;
            }
            break;

        case SERIAL_UART2_READ_HIGH_BYTE:
            uart2_frame_parser.sample_bytes[0] = data;
            uart2_frame_parser.state = SERIAL_UART2_READ_LOW_BYTE;
            break;

        case SERIAL_UART2_READ_LOW_BYTE:
            uart2_frame_parser.sample_bytes[1] = data;
            uart2_frame_parser.state = SERIAL_UART2_WAIT_END;
            break;

        case SERIAL_UART2_WAIT_END:
            if (data == SERIAL_UART2_FRAME_END) {
                SerialCommunicationUART2HandleSample(
                    uart2_frame_parser.sample_bytes);
                uart2_frame_parser.state = SERIAL_UART2_WAIT_START;
            } else if (data == SERIAL_UART2_FRAME_START) {
                /* 当前结束标志错误，但该字节可以作为下一帧的开始标志。 */
                uart2_frame_parser.state = SERIAL_UART2_READ_HIGH_BYTE;
            } else {
                uart2_frame_parser.state = SERIAL_UART2_WAIT_START;
            }
            break;

        default:
            uart2_frame_parser.state = SERIAL_UART2_WAIT_START;
            break;
    }
}

/* 将通过帧头帧尾校验的双字节大端数据发布给已注册消费者。 */
static void SerialCommunicationUART2HandleSample(const uint8_t *data)
{
    int16_t sample = (int16_t)(((uint16_t)data[0] << 8U) |
                               (uint16_t)data[1]);
    size_t index;

    for (index = 0U;
         index < SERIAL_UART2_SAMPLE_SUBSCRIBER_COUNT; ++index) {
        SerialCommunicationUART2SampleCallback_t callback;
        void *context;

        taskENTER_CRITICAL();
        callback = uart2_sample_subscribers[index].callback;
        context = uart2_sample_subscribers[index].context;
        taskEXIT_CRITICAL();
        if (callback != NULL) {
            callback(sample, context);
        }
    }
}
#endif

/*
 * UART3 在空闲状态收到 0xAA 时切换为波形帧解析；其他字节继续组成字符串。
 * 二进制帧解析期间即使样本字节等于 CR/LF，也不会误结束字符串。
 */
#if APP_ENABLE_UART3 != 0U
static void SerialCommunicationUART3ConsumeByte(uint8_t data)
{
    static const uint8_t too_long_message[] = "UART3 STRING TOO LONG\r\n";

    if ((APP_ENABLE_UART3_BINARY_WAVEFORM != 0U) &&
        ((uart3_frame_parser.state != SERIAL_UART3_WAIT_START) ||
         (data == SERIAL_UART3_FRAME_START))) {
        if (uart3_frame_parser.state == SERIAL_UART3_WAIT_START) {
            /* 二进制帧开始时丢弃尚未以 CR/LF 结束的不完整字符串。 */
            uart3_string_parser.length = 0U;
            uart3_string_parser.overflowed = false;
        }
        SerialCommunicationUART3FrameConsumeByte(data);
        return;
    }

    if ((data == 0U) || (data == '\r') || (data == '\n')) {
        if (uart3_string_parser.overflowed) {
            /* sep/sweep 会输出较长进度日志；准备期间静默丢弃，避免刷屏。 */
            if (!SerialCommunicationUART3TransactionIsActive(
                    uart3_transaction_status)) {
                SerialCommunicationDebugSend(
                    too_long_message, sizeof(too_long_message) - 1U);
            }
        } else if (uart3_string_parser.length > 0U) {
            SerialCommunicationUART3HandleString(
                uart3_string_parser.data, uart3_string_parser.length);
        }

        uart3_string_parser.length     = 0U;
        uart3_string_parser.overflowed = false;
        return;
    }

    if (uart3_string_parser.overflowed) {
        return;
    }

    if (uart3_string_parser.length >= SERIAL_UART3_STRING_BUFFER_SIZE) {
        uart3_string_parser.overflowed = true;
        return;
    }

    uart3_string_parser.data[uart3_string_parser.length] = data;
    ++uart3_string_parser.length;
}

/* 解析 UART3 的 AA + int16 大端 + 55 波形样本帧。 */
static void SerialCommunicationUART3FrameConsumeByte(uint8_t data)
{
    switch (uart3_frame_parser.state) {
        case SERIAL_UART3_WAIT_START:
            if (data == SERIAL_UART3_FRAME_START) {
                uart3_frame_parser.state = SERIAL_UART3_READ_HIGH_BYTE;
            }
            break;

        case SERIAL_UART3_READ_HIGH_BYTE:
            uart3_frame_parser.sample_bytes[0] = data;
            uart3_frame_parser.state = SERIAL_UART3_READ_LOW_BYTE;
            break;

        case SERIAL_UART3_READ_LOW_BYTE:
            uart3_frame_parser.sample_bytes[1] = data;
            uart3_frame_parser.state = SERIAL_UART3_WAIT_END;
            break;

        case SERIAL_UART3_WAIT_END:
            if (data == SERIAL_UART3_FRAME_END) {
                int16_t sample = (int16_t)(
                    ((uint16_t)uart3_frame_parser.sample_bytes[0] << 8U) |
                    (uint16_t)uart3_frame_parser.sample_bytes[1]);
                SerialCommunicationUART3PublishSample(sample);
                uart3_frame_parser.state = SERIAL_UART3_WAIT_START;
            } else if (data == SERIAL_UART3_FRAME_START) {
                /* 结束标志错误时把当前字节复用为下一帧帧头。 */
                uart3_frame_parser.state = SERIAL_UART3_READ_HIGH_BYTE;
            } else {
                uart3_frame_parser.state = SERIAL_UART3_WAIT_START;
            }
            break;

        default:
            uart3_frame_parser.state = SERIAL_UART3_WAIT_START;
            break;
    }
}

/* 将已校验并完成单位转换的 UART3 样本发布给订阅者。 */
static void SerialCommunicationUART3PublishSample(int16_t sample)
{
    size_t index;

    for (index = 0U;
         index < SERIAL_UART3_SAMPLE_SUBSCRIBER_COUNT; ++index) {
        SerialCommunicationUART3SampleCallback_t callback;
        void *context;

        taskENTER_CRITICAL();
        callback = uart3_sample_subscribers[index].callback;
        context = uart3_sample_subscribers[index].context;
        taskEXIT_CRITICAL();
        if (callback != NULL) {
            callback(sample, context);
        }
    }
}

/*
 * 按参考主控协议解析一行十进制电压，不使用 float/sscanf。
 * 输入最多保留 5 位小数，输出统一换算为有符号毫伏供波形页显示。
 */
#if APP_ENABLE_UART3_ASCII_WAVEFORM != 0U
static bool SerialCommunicationUART3ParseVoltageMillivolts(
    const uint8_t *data, size_t size, int16_t *sample)
{
    size_t index = 0U;
    bool negative = false;
    bool have_digit = false;
    uint32_t whole = 0U;
    uint32_t fraction = 0U;
    uint8_t fraction_digits = 0U;
    uint32_t fixed_5;
    uint32_t millivolts;

    if ((data == NULL) || (sample == NULL) || (size == 0U)) {
        return false;
    }

    while ((index < size) &&
           ((data[index] == (uint8_t)' ') ||
            (data[index] == (uint8_t)'\t'))) {
        ++index;
    }
    if ((index < size) &&
        ((data[index] == (uint8_t)'+') ||
         (data[index] == (uint8_t)'-'))) {
        negative = data[index] == (uint8_t)'-';
        ++index;
    }

    while ((index < size) && (data[index] >= (uint8_t)'0') &&
           (data[index] <= (uint8_t)'9')) {
        uint32_t digit = (uint32_t)(data[index] - (uint8_t)'0');

        if (whole > ((UINT32_MAX - digit) / 10U)) {
            return false;
        }
        whole = (whole * 10U) + digit;
        have_digit = true;
        ++index;
    }

    if ((index < size) && (data[index] == (uint8_t)'.')) {
        ++index;
        while ((index < size) && (data[index] >= (uint8_t)'0') &&
               (data[index] <= (uint8_t)'9')) {
            if (fraction_digits < 5U) {
                fraction = (fraction * 10U) +
                    (uint32_t)(data[index] - (uint8_t)'0');
                ++fraction_digits;
            }
            have_digit = true;
            ++index;
        }
    }

    while ((index < size) &&
           ((data[index] == (uint8_t)' ') ||
            (data[index] == (uint8_t)'\t'))) {
        ++index;
    }
    if (!have_digit || (index != size)) {
        return false;
    }
    while (fraction_digits < 5U) {
        fraction *= 10U;
        ++fraction_digits;
    }
    if (whole > ((UINT32_MAX - fraction) / 100000U)) {
        return false;
    }

    fixed_5 = (whole * 100000U) + fraction;
    millivolts = (fixed_5 + 50U) / 100U;
    if ((!negative && (millivolts > (uint32_t)INT16_MAX)) ||
        (negative && (millivolts > ((uint32_t)INT16_MAX + 1U)))) {
        return false;
    }

    *sample = negative
                  ? ((millivolts == ((uint32_t)INT16_MAX + 1U))
                        ? INT16_MIN
                        : (int16_t)-(int16_t)millivolts)
                  : (int16_t)millivolts;
    return true;
}
#endif

/* 解析普通十进制数，并统一换算成保留 5 位小数的有符号整数。 */
static bool SerialCommunicationUART3ParseSignedFixed5(
    const uint8_t *data, size_t size, int32_t *fixed_5)
{
    size_t index = 0U;
    bool negative = false;
    bool have_digit = false;
    uint64_t whole = 0ULL;
    uint64_t fraction = 0ULL;
    uint8_t fraction_digits = 0U;
    uint64_t magnitude;

    if ((data == NULL) || (fixed_5 == NULL) || (size == 0U)) {
        return false;
    }
    while ((index < size) &&
           ((data[index] == (uint8_t)' ') ||
            (data[index] == (uint8_t)'\t'))) {
        ++index;
    }
    if ((index < size) &&
        ((data[index] == (uint8_t)'+') ||
         (data[index] == (uint8_t)'-'))) {
        negative = data[index] == (uint8_t)'-';
        ++index;
    }

    while ((index < size) && (data[index] >= (uint8_t)'0') &&
           (data[index] <= (uint8_t)'9')) {
        uint64_t digit = (uint64_t)(data[index] - (uint8_t)'0');

        if (whole > ((UINT64_MAX - digit) / 10ULL)) {
            return false;
        }
        whole = (whole * 10ULL) + digit;
        have_digit = true;
        ++index;
    }
    if ((index < size) && (data[index] == (uint8_t)'.')) {
        ++index;
        while ((index < size) && (data[index] >= (uint8_t)'0') &&
               (data[index] <= (uint8_t)'9')) {
            if (fraction_digits < 5U) {
                fraction = (fraction * 10ULL) +
                    (uint64_t)(data[index] - (uint8_t)'0');
                ++fraction_digits;
            }
            have_digit = true;
            ++index;
        }
    }
    while ((index < size) &&
           ((data[index] == (uint8_t)' ') ||
            (data[index] == (uint8_t)'\t'))) {
        ++index;
    }
    if (!have_digit || (index != size)) {
        return false;
    }
    while (fraction_digits < 5U) {
        fraction *= 10ULL;
        ++fraction_digits;
    }
    if (whole > ((UINT64_MAX - fraction) / 100000ULL)) {
        return false;
    }
    magnitude = (whole * 100000ULL) + fraction;
    if ((!negative && (magnitude > (uint64_t)INT32_MAX)) ||
        (negative && (magnitude > ((uint64_t)INT32_MAX + 1ULL)))) {
        return false;
    }
    if (negative) {
        *fixed_5 = (magnitude == ((uint64_t)INT32_MAX + 1ULL))
                       ? INT32_MIN
                       : -(int32_t)magnitude;
    } else {
        *fixed_5 = (int32_t)magnitude;
    }
    return true;
}

/* 只有三个进行中状态会占用事务槽；完成和错误状态允许启动下一次请求。 */
static bool SerialCommunicationUART3TransactionIsActive(
    SerialCommunicationUART3TransactionStatus_e status)
{
    return (status ==
               SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL) ||
           (status ==
               SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_SWEEP) ||
           (status == SERIAL_COMMUNICATION_UART3_TRANSACTION_COLLECTING);
}

/* A 单路查询只需 sep1；涉及 B/合并模型时用 sep2；曲线响应依赖 sweep1。 */
static SerialUART3Preparation_e SerialCommunicationUART3PreparationForType(
    SerialCommunicationUART3DataType_e type)
{
    switch (type) {
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A1:
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_A3:
        case SERIAL_COMMUNICATION_UART3_DATA_LSPECT_A:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_A1:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_A3:
        case SERIAL_COMMUNICATION_UART3_DATA_SPECT_A:
        case SERIAL_COMMUNICATION_UART3_DATA_SPECTRUM:
            return SERIAL_UART3_PREPARATION_SEP1;

        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_B1:
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_B3:
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_1:
        case SERIAL_COMMUNICATION_UART3_DATA_LWAVE_3:
        case SERIAL_COMMUNICATION_UART3_DATA_LSPECT_B:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_B1:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_B3:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_1:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_3:
        case SERIAL_COMMUNICATION_UART3_DATA_SPECT_B:
            return SERIAL_UART3_PREPARATION_SEP2;

        case SERIAL_COMMUNICATION_UART3_DATA_LAFC:
        case SERIAL_COMMUNICATION_UART3_DATA_LPFC:
        case SERIAL_COMMUNICATION_UART3_DATA_AFC:
        case SERIAL_COMMUNICATION_UART3_DATA_PFC:
            return SERIAL_UART3_PREPARATION_SWEEP1;

        case SERIAL_COMMUNICATION_UART3_DATA_COUNT:
        default:
            return SERIAL_UART3_PREPARATION_NONE;
    }
}

static bool SerialCommunicationUART3StringEquals(
    const uint8_t *data, size_t size, const char *expected)
{
    size_t expected_size = strlen(expected);

    return (size == expected_size) &&
           (memcmp(data, expected, expected_size) == 0);
}

static bool SerialCommunicationUART3StringStartsWith(
    const uint8_t *data, size_t size, const char *prefix)
{
    size_t prefix_size = strlen(prefix);

    return (size >= prefix_size) &&
           (memcmp(data, prefix, prefix_size) == 0);
}

static bool SerialCommunicationUART3StringContains(
    const uint8_t *data, size_t size, const char *fragment)
{
    size_t fragment_size = strlen(fragment);
    size_t index;

    if ((fragment_size == 0U) || (fragment_size > size)) {
        return false;
    }
    for (index = 0U; index <= size - fragment_size; ++index) {
        if (memcmp(&data[index], fragment, fragment_size) == 0) {
            return true;
        }
    }
    return false;
}

/* 准备阶段只识别 READY/DONE 和错误行，其余采样进度日志全部吞掉。 */
static bool SerialCommunicationUART3HandlePreparationString(
    const uint8_t *data, size_t size)
{
    SerialCommunicationUART3TransactionStatus_e status;
    SerialUART3Preparation_e preparation;
    SerialCommunicationUART3DataType_e type;
    bool ready = false;

    taskENTER_CRITICAL();
    status = uart3_transaction_status;
    preparation = uart3_preparation;
    type = uart3_transaction_type;
    taskEXIT_CRITICAL();

    if ((status !=
            SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL) &&
        (status !=
            SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_SWEEP)) {
        return false;
    }

    if (SerialCommunicationUART3StringEquals(data, size, "error") ||
        SerialCommunicationUART3StringContains(data, size, "ERROR") ||
        SerialCommunicationUART3StringContains(data, size, "TIMEOUT")) {
        SerialCommunicationUART3SetTransactionError(
            SERIAL_COMMUNICATION_UART3_TRANSACTION_REMOTE_ERROR);
        return true;
    }

    if (status ==
        SERIAL_COMMUNICATION_UART3_TRANSACTION_PREPARING_MODEL) {
        bool a_ready =
            SerialCommunicationUART3StringEquals(
                data, size, "MODEL HIGH A READY") ||
            SerialCommunicationUART3StringEquals(
                data, size, "MODEL FILTER A READY");
        bool ab_ready =
            SerialCommunicationUART3StringEquals(
                data, size, "MODEL HIGH AB READY") ||
            SerialCommunicationUART3StringEquals(
                data, size, "MODEL FILTER AB READY");

        if ((preparation == SERIAL_UART3_PREPARATION_SEP2) && a_ready) {
            SerialCommunicationUART3SetTransactionError(
                SERIAL_COMMUNICATION_UART3_TRANSACTION_REMOTE_ERROR);
            return true;
        }
        ready = (preparation == SERIAL_UART3_PREPARATION_SEP1)
                    ? (a_ready || ab_ready)
                    : ((preparation == SERIAL_UART3_PREPARATION_SEP2) &&
                          ab_ready);
    } else if (preparation == SERIAL_UART3_PREPARATION_SWEEP1) {
        ready = SerialCommunicationUART3StringStartsWith(
            data, size, "SWEEP DONE");
    }

    if (ready) {
        /* 取消或切换请求可能与迟到 READY/DONE 并发；失败时保持新状态。 */
        (void)SerialCommunicationUART3StartDataTransaction(type, true);
    }
    return true;
}

/* 频谱响应发布到 FFTAnalysis；其他响应发布为波形样本。 */
static bool SerialCommunicationUART3DataTypeIsSpectrum(
    SerialCommunicationUART3DataType_e type)
{
    return (type == SERIAL_COMMUNICATION_UART3_DATA_LSPECT_A) ||
           (type == SERIAL_COMMUNICATION_UART3_DATA_LSPECT_B) ||
           (type == SERIAL_COMMUNICATION_UART3_DATA_SPECT_A) ||
           (type == SERIAL_COMMUNICATION_UART3_DATA_SPECT_B) ||
           (type == SERIAL_COMMUNICATION_UART3_DATA_SPECTRUM);
}

/* l 前缀的十种 LCD 命令使用 start/end 帧，其余命令返回裸数字行。 */
static bool SerialCommunicationUART3DataTypeIsFramed(
    SerialCommunicationUART3DataType_e type)
{
    return type <= SERIAL_COMMUNICATION_UART3_DATA_LPFC;
}

/* 返回上位机原始响应点数；裸数据在接收期间压缩到本地 128 点。 */
static size_t SerialCommunicationUART3DataSourcePointCount(
    SerialCommunicationUART3DataType_e type)
{
    switch (type) {
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_A1:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_A3:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_B1:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_B3:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_1:
        case SERIAL_COMMUNICATION_UART3_DATA_WAVE_3:
        case SERIAL_COMMUNICATION_UART3_DATA_SPECT_A:
        case SERIAL_COMMUNICATION_UART3_DATA_SPECT_B:
            return 800U;
        case SERIAL_COMMUNICATION_UART3_DATA_SPECTRUM:
            return 1024U;
        case SERIAL_COMMUNICATION_UART3_DATA_AFC:
        case SERIAL_COMMUNICATION_UART3_DATA_PFC:
            return 496U;
        default:
            return SERIAL_UART3_TRANSACTION_POINT_COUNT;
    }
}

/* 固定长度裸数据压缩为 LCD 使用的 128 点；频谱每桶保留峰值。 */
static void SerialCommunicationUART3StoreTransactionPoint(int32_t fixed_5)
{
    size_t source_count =
        SerialCommunicationUART3DataSourcePointCount(uart3_transaction_type);
    size_t output_index =
        (uart3_transaction_point_count *
         SERIAL_UART3_TRANSACTION_POINT_COUNT) / source_count;
    uint32_t raw_fixed_5;

    if (output_index >= SERIAL_UART3_TRANSACTION_POINT_COUNT) {
        output_index = SERIAL_UART3_TRANSACTION_POINT_COUNT - 1U;
    }
    memcpy(&raw_fixed_5, &fixed_5, sizeof(raw_fixed_5));
    if (SerialCommunicationUART3DataTypeIsSpectrum(
            uart3_transaction_type)) {
        int32_t previous;

        memcpy(&previous, &uart3_transaction_points[output_index],
               sizeof(previous));
        if (fixed_5 > previous) {
            uart3_transaction_points[output_index] = raw_fixed_5;
        }
    } else {
        uart3_transaction_points[output_index] = raw_fixed_5;
    }
}

/*
 * 在临界区内只取得回调快照，实际回调在锁外执行；任一观察者消费该行后，
 * 旧 ASCII 波形和 HELLO/PING 解析都不再处理它。
 */
static bool SerialCommunicationUART3PublishLine(
    const uint8_t *data, size_t size)
{
    size_t index;
    bool consumed = false;

    for (index = 0U; index < SERIAL_UART3_LINE_SUBSCRIBER_COUNT; ++index) {
        SerialCommunicationUART3LineCallback_t callback;
        void *context;

        taskENTER_CRITICAL();
        callback = uart3_line_subscribers[index].callback;
        context = uart3_line_subscribers[index].context;
        taskEXIT_CRITICAL();
        if ((callback != NULL) && callback(data, size, context)) {
            consumed = true;
        }
    }
    return consumed;
}

/* 统一终止解析并保存具体错误原因，供页面区分远端、协议和超时错误。 */
static void SerialCommunicationUART3SetTransactionError(
    SerialCommunicationUART3TransactionStatus_e status)
{
    taskENTER_CRITICAL();
    uart3_preparation = SERIAL_UART3_PREPARATION_NONE;
    uart3_transaction_parser_state = SERIAL_UART3_TRANSACTION_INACTIVE;
    uart3_transaction_point_count = 0U;
    uart3_transaction_status = status;
    taskEXIT_CRITICAL();
}

/* RX 任务定期检查绝对截止时间，避免页面永远停留在 WAIT。 */
static void SerialCommunicationUART3CheckTransactionTimeout(void)
{
    TickType_t now = xTaskGetTickCount();
    bool timed_out;

    taskENTER_CRITICAL();
    timed_out =
        SerialCommunicationUART3TransactionIsActive(
            uart3_transaction_status) &&
        ((int32_t)(now - uart3_transaction_deadline) >= 0);
    if (timed_out) {
        uart3_preparation = SERIAL_UART3_PREPARATION_NONE;
        uart3_transaction_parser_state = SERIAL_UART3_TRANSACTION_INACTIVE;
        uart3_transaction_point_count = 0U;
        uart3_transaction_status =
            SERIAL_COMMUNICATION_UART3_TRANSACTION_TIMEOUT;
    }
    taskEXIT_CRITICAL();
}

/* 将 fixed-5 数据换算为 milli-unit，并沿用现有 UART3 样本订阅接口。 */
static void SerialCommunicationUART3PublishFixed5Sample(uint32_t raw_sample)
{
    int32_t fixed_5;
    int64_t rounded;
    int16_t sample;

    memcpy(&fixed_5, &raw_sample, sizeof(fixed_5));
    rounded = (fixed_5 >= 0)
                  ? (((int64_t)fixed_5 + 50LL) / 100LL)
                  : -(((-(int64_t)fixed_5) + 50LL) / 100LL);
    if (rounded > INT16_MAX) {
        sample = INT16_MAX;
    } else if (rounded < INT16_MIN) {
        sample = INT16_MIN;
    } else {
        sample = (int16_t)rounded;
    }
    SerialCommunicationUART3PublishSample(sample);
}

/* end 到达且点数正确后，才一次性发布完整事务。 */
static bool SerialCommunicationUART3CompleteTransaction(void)
{
    size_t index;

    if (SerialCommunicationUART3DataTypeIsSpectrum(
            uart3_transaction_type)) {
#if APP_ENABLE_UART3_SPECTRUM != 0U
        ++uart3_spectrum_source_sequence;
        if (!FFTAnalysisPublishExternalSpectrum(
                FFT_ANALYSIS_INPUT_UART3,
                uart3_transaction_points,
                SERIAL_UART3_TRANSACTION_POINT_COUNT,
                NULL, 0U,
                APP_UART3_SPECTRUM_MAX_FREQUENCY_HZ,
                uart3_spectrum_source_sequence)) {
            return false;
        }
#else
        return false;
#endif
    } else {
        for (index = 0U;
             index < SERIAL_UART3_TRANSACTION_POINT_COUNT; ++index) {
            SerialCommunicationUART3PublishFixed5Sample(
                uart3_transaction_points[index]);
        }
    }

    taskENTER_CRITICAL();
    uart3_preparation = SERIAL_UART3_PREPARATION_NONE;
    uart3_transaction_parser_state = SERIAL_UART3_TRANSACTION_INACTIVE;
    uart3_transaction_status =
        SERIAL_COMMUNICATION_UART3_TRANSACTION_COMPLETE;
    taskEXIT_CRITICAL();
    return true;
}

/* 消费带 start/end 的 128 点帧，或固定长度的裸数字响应。 */
static bool SerialCommunicationUART3HandleTransactionString(
    const uint8_t *data, size_t size)
{
    static const uint8_t start_marker[] = "start";
    static const uint8_t end_marker[] = "end";
    static const uint8_t error_marker[] = "error";
    int32_t fixed_5;
    bool is_start = (size == sizeof(start_marker) - 1U) &&
        (memcmp(data, start_marker, size) == 0);
    bool is_end = (size == sizeof(end_marker) - 1U) &&
        (memcmp(data, end_marker, size) == 0);
    bool is_error = (size == sizeof(error_marker) - 1U) &&
        (memcmp(data, error_marker, size) == 0);
    bool framed = SerialCommunicationUART3DataTypeIsFramed(
        uart3_transaction_type);
    size_t expected_count =
        SerialCommunicationUART3DataSourcePointCount(uart3_transaction_type);

    if (uart3_transaction_status ==
        SERIAL_COMMUNICATION_UART3_TRANSACTION_IDLE) {
        return false;
    }
    if (uart3_transaction_status !=
        SERIAL_COMMUNICATION_UART3_TRANSACTION_COLLECTING) {
        /* 已完成或失败事务后的迟到文本必须丢弃，不能落入旧的逐行采样路径。 */
        return true;
    }
    if (is_error || SerialCommunicationUART3StringContains(
                        data, size, "ERROR")) {
        SerialCommunicationUART3SetTransactionError(
            SERIAL_COMMUNICATION_UART3_TRANSACTION_REMOTE_ERROR);
        return true;
    }

    switch (uart3_transaction_parser_state) {
        case SERIAL_UART3_TRANSACTION_WAIT_START:
            if (is_start) {
                uart3_transaction_point_count = 0U;
                uart3_transaction_parser_state =
                    SERIAL_UART3_TRANSACTION_READ_POINTS;
            }
            /* start 之前的其他日志不属于响应帧，直接忽略。 */
            return true;

        case SERIAL_UART3_TRANSACTION_READ_POINTS:
            if (framed && is_start) {
                /* 重复 start 作为新帧起点，丢弃此前未完成的点。 */
                uart3_transaction_point_count = 0U;
                return true;
            }
            if ((framed && is_end) ||
                !SerialCommunicationUART3ParseSignedFixed5(
                    data, size, &fixed_5) ||
                (SerialCommunicationUART3DataTypeIsSpectrum(
                     uart3_transaction_type) && (fixed_5 < 0))) {
                SerialCommunicationUART3SetTransactionError(
                    framed
                        ? SERIAL_COMMUNICATION_UART3_TRANSACTION_PROTOCOL_ERROR
                        : SERIAL_COMMUNICATION_UART3_TRANSACTION_REMOTE_ERROR);
                return true;
            }
            SerialCommunicationUART3StoreTransactionPoint(fixed_5);
            ++uart3_transaction_point_count;
            if (uart3_transaction_point_count >= expected_count) {
                if (framed) {
                    uart3_transaction_parser_state =
                        SERIAL_UART3_TRANSACTION_WAIT_END;
                } else if (!SerialCommunicationUART3CompleteTransaction()) {
                    SerialCommunicationUART3SetTransactionError(
                        SERIAL_COMMUNICATION_UART3_TRANSACTION_PROTOCOL_ERROR);
                }
            }
            return true;

        case SERIAL_UART3_TRANSACTION_WAIT_END:
            if (is_end) {
                if (!SerialCommunicationUART3CompleteTransaction()) {
                    SerialCommunicationUART3SetTransactionError(
                        SERIAL_COMMUNICATION_UART3_TRANSACTION_PROTOCOL_ERROR);
                }
            } else {
                SerialCommunicationUART3SetTransactionError(
                    SERIAL_COMMUNICATION_UART3_TRANSACTION_PROTOCOL_ERROR);
            }
            return true;

        case SERIAL_UART3_TRANSACTION_INACTIVE:
        default:
            return false;
    }
}

/* 判断 UART3 的完整字符串命令，并通过 UART0 输出处理结果。 */
static void SerialCommunicationUART3HandleString(
    const uint8_t *data, size_t size)
{
#if APP_ENABLE_UART3_TEXT_COMMAND != 0U
    static const uint8_t hello_command[] = "HELLO";
    static const uint8_t ping_command[] = "PING";
    static const uint8_t hello_message[] = "UART3 STRING HELLO\r\n";
    static const uint8_t ping_message[] = "UART3 STRING PING\r\n";
    static const uint8_t unknown_message[] = "UART3 STRING UNKNOWN\r\n";
    const uint8_t *message;
    size_t message_size;
#endif
#if APP_ENABLE_UART3_ASCII_WAVEFORM != 0U
    int16_t sample;
#endif

    /*
     * 路由顺序不可交换：事务控制行优先，其次是页面文本观察者，最后才把
     * 普通数字解释为旧式逐点波形，避免命令响应被错误发布为采样值。
     */
    if (SerialCommunicationUART3HandlePreparationString(data, size) ||
        SerialCommunicationUART3HandleTransactionString(data, size)) {
        return;
    }
    if (SerialCommunicationUART3PublishLine(data, size)) {
        return;
    }

#if APP_ENABLE_UART3_ASCII_WAVEFORM != 0U
    if (SerialCommunicationUART3ParseVoltageMillivolts(
            data, size, &sample)) {
        SerialCommunicationUART3PublishSample(sample);
        return;
    }
#endif

#if APP_ENABLE_UART3_TEXT_COMMAND != 0U
    if ((size == sizeof(hello_command) - 1U) &&
        (memcmp(data, hello_command, size) == 0)) {
        message      = hello_message;
        message_size = sizeof(hello_message) - 1U;
    } else if ((size == sizeof(ping_command) - 1U) &&
               (memcmp(data, ping_command, size) == 0)) {
        message      = ping_message;
        message_size = sizeof(ping_message) - 1U;
    } else {
        message      = unknown_message;
        message_size = sizeof(unknown_message) - 1U;
    }

    SerialCommunicationDebugSend(message, message_size);
#else
    (void)data;
    (void)size;
#endif
}
#endif

/* 使用状态机解析 UART1 协议中的一个接收字节。 */
#if APP_ENABLE_UART1 != 0U
static void SerialCommunicationUART1ProtocolConsumeByte(uint8_t data)
{
    switch (uart1_protocol_parser.state) {
        case SERIAL_PROTOCOL_WAIT_HEADER_1:
            if (data == SERIAL_PROTOCOL_HEADER_1) {
                uart1_protocol_parser.state =
                    SERIAL_PROTOCOL_WAIT_HEADER_2;
            }
            break;

        case SERIAL_PROTOCOL_WAIT_HEADER_2:
            if (data == SERIAL_PROTOCOL_HEADER_2) {
                uart1_protocol_parser.state = SERIAL_PROTOCOL_READ_LENGTH;
            } else if (data != SERIAL_PROTOCOL_HEADER_1) {
                SerialCommunicationUART1ProtocolReset();
            }
            break;

        case SERIAL_PROTOCOL_READ_LENGTH:
            if (data > SERIAL_PROTOCOL_MAX_PAYLOAD) {
                SerialCommunicationUART1ProtocolReset();
                break;
            }

            uart1_protocol_parser.payload_length = data;
            uart1_protocol_parser.payload_index  = 0U;
            uart1_protocol_parser.checksum       = data;
            uart1_protocol_parser.state = SERIAL_PROTOCOL_READ_COMMAND;
            break;

        case SERIAL_PROTOCOL_READ_COMMAND:
            uart1_protocol_parser.command = data;
            uart1_protocol_parser.checksum += data;
            uart1_protocol_parser.state =
                (uart1_protocol_parser.payload_length == 0U)
                    ? SERIAL_PROTOCOL_READ_CHECKSUM
                    : SERIAL_PROTOCOL_READ_PAYLOAD;
            break;

        case SERIAL_PROTOCOL_READ_PAYLOAD:
            uart1_protocol_parser.payload[uart1_protocol_parser.payload_index] =
                data;
            ++uart1_protocol_parser.payload_index;
            uart1_protocol_parser.checksum += data;

            if (uart1_protocol_parser.payload_index >=
                uart1_protocol_parser.payload_length) {
                uart1_protocol_parser.state =
                    SERIAL_PROTOCOL_READ_CHECKSUM;
            }
            break;

        case SERIAL_PROTOCOL_READ_CHECKSUM:
            if (data == uart1_protocol_parser.checksum) {
                SerialCommunicationUART1HandleFrame(
                    uart1_protocol_parser.command,
                    uart1_protocol_parser.payload,
                    uart1_protocol_parser.payload_length);
            }
            SerialCommunicationUART1ProtocolReset();
            break;

        default:
            SerialCommunicationUART1ProtocolReset();
            break;
    }
}

/* 处理校验通过的 UART1 完整协议帧，并发送对应响应。 */
static void SerialCommunicationUART1HandleFrame(
    uint8_t command, const uint8_t *payload, uint8_t payload_length)
{
    static const uint8_t receive_message[] = "UART1 RX\r\n";
    static const uint8_t pong[] = {'P', 'O', 'N', 'G'};

    /* 仅在完整帧校验通过后输出一次接收提示。 */
    SerialCommunicationDebugSend(
        receive_message, sizeof(receive_message) - 1U);

    switch (command) {
        case 0x01U:
            /* PING 命令：返回命令 0x81 和 ASCII 数据 PONG。 */
            (void)SerialCommunicationUART1SendFrame(
                0x81U, pong, sizeof(pong));
            break;

        case 0x02U:
            /* ECHO 命令：使用响应命令 0x82 原样返回负载。 */
            (void)SerialCommunicationUART1SendFrame(
                0x82U, payload, payload_length);
            break;

        default:
            /* 未知命令：响应 0xFF，并在负载中返回原始命令值。 */
            (void)SerialCommunicationUART1SendFrame(
                0xFFU, &command, sizeof(command));
            break;
    }
}

/* 按 UART1 协议格式组装响应帧、计算校验和并发送。 */
static bool SerialCommunicationUART1SendFrame(
    uint8_t command, const uint8_t *payload, uint8_t payload_length)
{
    uint8_t frame[SERIAL_PROTOCOL_MAX_PAYLOAD + 5U];
    uint8_t checksum;
    uint8_t index;

    if ((payload_length > SERIAL_PROTOCOL_MAX_PAYLOAD) ||
        ((payload_length > 0U) && (payload == NULL))) {
        return false;
    }

    frame[0] = SERIAL_PROTOCOL_HEADER_1;
    frame[1] = SERIAL_PROTOCOL_HEADER_2;
    frame[2] = payload_length;
    frame[3] = command;
    checksum = (uint8_t)(payload_length + command);

    for (index = 0U; index < payload_length; ++index) {
        frame[4U + index] = payload[index];
        checksum += payload[index];
    }

    frame[4U + payload_length] = checksum;
    return SerialCommunicationUART1Send(
        frame, (size_t)payload_length + 5U);
}

/* 清空 UART1 协议解析状态，重新等待帧头。 */
static void SerialCommunicationUART1ProtocolReset(void)
{
    uart1_protocol_parser.state          = SERIAL_PROTOCOL_WAIT_HEADER_1;
    uart1_protocol_parser.payload_length = 0U;
    uart1_protocol_parser.payload_index  = 0U;
    uart1_protocol_parser.command        = 0U;
    uart1_protocol_parser.checksum       = 0U;
}
#endif
