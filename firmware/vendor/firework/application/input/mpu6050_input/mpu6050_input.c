/*
 * MPU6050 输入层把传感器初始化和周期读取放进独立任务。
 * 传感器暂时未连接时允许后台重试，其他 Application 不必阻塞在 I2C 初始化上。
 */
#include "application/input/mpu6050_input/mpu6050_input.h"

#include <stddef.h>

#include "FreeRTOS.h"
#include "task.h"

#include "application/app_config.h"
#include "application/task/task_manager.h"

#define MPU6050_INPUT_RETRY_PERIOD_MS (500U)

#if APP_ENABLE_MPU6050_INPUT != 0U
/* 最新样本和统计由读取任务写入，公开快照接口在临界区内成组复制。 */
static MPU6050Instance *mpu6050_input_device;
MPU6050Sample mpu6050_input_latest_sample;
MPU6050DmpSample mpu6050_input_latest_dmp_sample;
static volatile uint32_t mpu6050_input_successful_read_count;
static volatile uint32_t mpu6050_input_read_error_count;
static volatile bool mpu6050_input_sample_valid;
static volatile bool mpu6050_input_dmp_sample_valid;
static volatile bool mpu6050_input_sensor_initialized;
static bool mpu6050_input_task_created;
static bool mpu6050_input_ready;

static void MPU6050InputTask(void *argument);
#endif

bool MPU6050InputInit(void)
{
#if APP_ENABLE_MPU6050_INPUT != 0U
    static const MPU6050Config config = {
        .i2c_address = MPU6050_I2C_ADDRESS_AD0_LOW,
        /* DLPF=44 Hz 时内部采样率为 1 kHz，分频 9 后为 100 Hz。 */
        .sample_rate_divider = 9U,
        .accel_range = MPU6050_ACCEL_RANGE_2G,
        .gyro_range = MPU6050_GYRO_RANGE_250_DPS,
        .dlpf_config = MPU6050_DLPF_CONFIG_44_HZ,
        .clock_source = MPU6050_CLOCK_PLL_X_GYRO,
        .enable_dmp = (APP_ENABLE_MPU6050_DMP != 0U),
        .dmp_sample_rate_hz = APP_MPU6050_DMP_RATE_HZ
    };

    if (mpu6050_input_ready) {
        return true;
    }

    mpu6050_input_device = MPU6050Register(&config);
    if (mpu6050_input_device == NULL) {
        return false;
    }

    mpu6050_input_latest_sample = (MPU6050Sample){0};
    mpu6050_input_latest_dmp_sample = (MPU6050DmpSample){0};
    mpu6050_input_successful_read_count = 0U;
    mpu6050_input_read_error_count = 0U;
    mpu6050_input_sample_valid = false;
    mpu6050_input_dmp_sample_valid = false;
    mpu6050_input_sensor_initialized = false;

    if (!mpu6050_input_task_created &&
        (ApplicationTaskCreate(APPLICATION_TASK_MPU6050_INPUT,
             MPU6050InputTask, NULL) == NULL)) {
        return false;
    }

    mpu6050_input_task_created = true;
    mpu6050_input_ready = true;
    return true;
#else
    return false;
#endif
}

bool MPU6050InputGetSample(MPU6050Sample *sample)
{
#if APP_ENABLE_MPU6050_INPUT != 0U
    if ((sample == NULL) || !mpu6050_input_ready ||
        !mpu6050_input_sample_valid) {
        return false;
    }

    taskENTER_CRITICAL();
    *sample = mpu6050_input_latest_sample;
    taskEXIT_CRITICAL();
    return true;
#else
    (void)sample;
    return false;
#endif
}

bool MPU6050InputGetDmpSample(MPU6050DmpSample *sample)
{
#if APP_ENABLE_MPU6050_INPUT != 0U
    if ((sample == NULL) || !mpu6050_input_ready ||
        !mpu6050_input_dmp_sample_valid) {
        return false;
    }

    taskENTER_CRITICAL();
    *sample = mpu6050_input_latest_dmp_sample;
    taskEXIT_CRITICAL();
    return true;
#else
    (void)sample;
    return false;
#endif
}

bool MPU6050InputGetStatus(MPU6050InputStatus *status)
{
#if APP_ENABLE_MPU6050_INPUT != 0U
    if ((status == NULL) || !mpu6050_input_ready) {
        return false;
    }

    taskENTER_CRITICAL();
    status->sample = mpu6050_input_latest_sample;
    status->dmp_sample = mpu6050_input_latest_dmp_sample;
    status->successful_read_count = mpu6050_input_successful_read_count;
    status->read_error_count = mpu6050_input_read_error_count;
    status->sample_valid = mpu6050_input_sample_valid;
    status->dmp_sample_valid = mpu6050_input_dmp_sample_valid;
    status->sensor_initialized = mpu6050_input_sensor_initialized;
#if APP_ENABLE_MPU6050_DMP != 0U
    status->dmp_enabled = MPU6050IsDmpEnabled(mpu6050_input_device);
#else
    status->dmp_enabled = false;
#endif
    taskEXIT_CRITICAL();
    status->ready = true;
    return true;
#else
    (void)status;
    return false;
#endif
}

bool MPU6050InputIsReady(void)
{
#if APP_ENABLE_MPU6050_INPUT != 0U
    return mpu6050_input_ready;
#else
    return false;
#endif
}

uint32_t MPU6050InputGetMinimumFreeStackWords(void)
{
#if APP_ENABLE_MPU6050_INPUT != 0U
    return ApplicationTaskGetMinimumFreeStackWords(
        APPLICATION_TASK_MPU6050_INPUT);
#else
    return 0U;
#endif
}

#if APP_ENABLE_MPU6050_INPUT != 0U
static void MPU6050InputTask(void *argument)
{
    MPU6050Sample sample;
#if APP_ENABLE_MPU6050_DMP != 0U
    MPU6050DmpSample dmp_sample;
#endif
    TickType_t delay_ticks = pdMS_TO_TICKS(APP_MPU6050_INPUT_PERIOD_MS);
    TickType_t retry_ticks = pdMS_TO_TICKS(MPU6050_INPUT_RETRY_PERIOD_MS);

    (void)argument;
    /* 将配置中的毫秒周期转换为 Tick，并保证低分辨率 Tick 下仍会阻塞。 */
    if (delay_ticks == 0U) {
        delay_ticks = 1U;
    }
    if (retry_ticks == 0U) {
        retry_ticks = 1U;
    }

    for (;;) {
        /* 初始化失败时按较长周期重试，读取成功后按正常采样周期运行。 */
        /*
         * 传感器可能未上电或暂时断线。硬件初始化放在任务中重试，避免一个
         * 可选输入阻止整个 FreeRTOS 调度器启动。
         */
        if (!mpu6050_input_sensor_initialized) {
            if (MPU6050Initialize(mpu6050_input_device)
#if APP_ENABLE_MPU6050_DMP != 0U
                && MPU6050DmpInitialize(mpu6050_input_device)
#endif
            ) {
                taskENTER_CRITICAL();
                mpu6050_input_sensor_initialized = true;
                taskEXIT_CRITICAL();
            } else {
                taskENTER_CRITICAL();
                mpu6050_input_read_error_count++;
                taskEXIT_CRITICAL();
                vTaskDelay(retry_ticks);
                continue;
            }
        }

#if APP_ENABLE_MPU6050_DMP != 0U
        if (MPU6050IsDmpEnabled(mpu6050_input_device)) {
            /* DMP 输出由 FIFO 提供；未到下一个 FIFO 周期时保留上一帧。 */
            if (MPU6050ReadDmp(mpu6050_input_device, &dmp_sample)) {
                taskENTER_CRITICAL();
                mpu6050_input_latest_dmp_sample = dmp_sample;
                mpu6050_input_latest_sample = dmp_sample.sample;
                mpu6050_input_successful_read_count++;
                mpu6050_input_sample_valid = true;
                mpu6050_input_dmp_sample_valid = true;
                taskEXIT_CRITICAL();
            } else {
                taskENTER_CRITICAL();
                mpu6050_input_read_error_count++;
                taskEXIT_CRITICAL();
            }
        } else if (MPU6050Read(mpu6050_input_device, &sample)) {
#else
        if (MPU6050Read(mpu6050_input_device, &sample)) {
#endif
            taskENTER_CRITICAL();
            mpu6050_input_latest_sample = sample;
            mpu6050_input_successful_read_count++;
            mpu6050_input_sample_valid = true;
            taskEXIT_CRITICAL();
        } else {
            taskENTER_CRITICAL();
            mpu6050_input_read_error_count++;
            /* 基础寄存器读取失败时，下一轮重新检查 WHO_AM_I。 */
            mpu6050_input_sensor_initialized = false;
            taskEXIT_CRITICAL();
            vTaskDelay(retry_ticks);
            continue;
        }
        vTaskDelay(delay_ticks);
    }
}
#endif
