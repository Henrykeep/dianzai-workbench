/*
 * MPU6050 基础寄存器驱动：负责静态注册、初始化、原始采样和定点工程单位换算。
 * DMP 固件加载与姿态解算位于 mpu6050_dmp.c。
 */
#include "modules/mpu6050/mpu6050.h"

#include "FreeRTOS.h"
#include "task.h"

#include "bsp/bsp.h"
#include "modules/mpu6050/mpu6050_internal.h"

/* 基础配置和 14 字节连续采样窗口使用的 MPU6050 寄存器地址。 */
#define MPU6050_REGISTER_SMPLRT_DIV    (0x19U)
#define MPU6050_REGISTER_CONFIG        (0x1AU)
#define MPU6050_REGISTER_GYRO_CONFIG   (0x1BU)
#define MPU6050_REGISTER_ACCEL_CONFIG  (0x1CU)
#define MPU6050_REGISTER_ACCEL_XOUT_H  (0x3BU)
#define MPU6050_REGISTER_PWR_MGMT_1    (0x6BU)
#define MPU6050_REGISTER_PWR_MGMT_2    (0x6CU)
#define MPU6050_REGISTER_WHO_AM_I      (0x75U)

/* 芯片标识、寄存器位域和复位等待时间。 */
#define MPU6050_WHO_AM_I_VALUE         (0x68U)
#define MPU6050_DEVICE_RESET_BIT       (0x80U)
#define MPU6050_SLEEP_BIT              (0x40U)
#define MPU6050_CLOCK_SOURCE_MASK      (0x07U)
#define MPU6050_CONFIG_FIELD_MASK      (0x07U)
#define MPU6050_FULL_SCALE_SHIFT       (3U)
#define MPU6050_FULL_SCALE_MASK        (0x18U)
#define MPU6050_BURST_SAMPLE_SIZE      (14U)
#define MPU6050_RESET_DELAY_MS         (100U)

/* 当前框架只挂载一个 MPU6050，保持静态分配。 */
static MPU6050Instance mpu6050_instance;

static bool MPU6050ConfigIsValid(const MPU6050Config *config);
static void MPU6050DelayMilliseconds(uint32_t milliseconds);

MPU6050Instance *MPU6050Register(const MPU6050Config *config)
{
    if (!MPU6050ConfigIsValid(config)) {
        return NULL;
    }
    if (mpu6050_instance.registered) {
        return (mpu6050_instance.config.i2c_address ==
                    config->i2c_address)
                   ? &mpu6050_instance
                   : NULL;
    }

    /* I2C_DEVICE_MPU6050 映射到独立的 I2C1，不与 OLED 共用引脚。 */
    mpu6050_instance.i2c = I2CRegister(I2C_DEVICE_MPU6050);
    if (mpu6050_instance.i2c == NULL) {
        return NULL;
    }
    mpu6050_instance.config = *config;
    mpu6050_instance.registered = true;
    mpu6050_instance.initialized = false;
    mpu6050_instance.dmp_enabled = false;
    return &mpu6050_instance;
}

bool MPU6050Initialize(MPU6050Instance *instance)
{
    uint8_t who_am_i;
    uint8_t clock_source;

    if (!MPU6050InternalIsRegistered(instance) ||
        !MPU6050ReadWhoAmI(instance, &who_am_i) ||
        (who_am_i != MPU6050_WHO_AM_I_VALUE)) {
        return false;
    }

    instance->initialized = false;
    instance->dmp_enabled = false;

    /* 先软复位并等待器件重新响应，再一次性写入全部基础运行参数。 */
    if (!MPU6050InternalWriteRegister(instance,
            MPU6050_REGISTER_PWR_MGMT_1,
            MPU6050_DEVICE_RESET_BIT)) {
        return false;
    }
    MPU6050DelayMilliseconds(MPU6050_RESET_DELAY_MS);

    clock_source = (uint8_t)instance->config.clock_source &
                   MPU6050_CLOCK_SOURCE_MASK;
    if (!MPU6050InternalWriteRegister(instance,
            MPU6050_REGISTER_PWR_MGMT_1, clock_source) ||
        !MPU6050InternalWriteRegister(instance,
            MPU6050_REGISTER_PWR_MGMT_2, 0U) ||
        !MPU6050InternalWriteRegister(instance, MPU6050_REGISTER_CONFIG,
            (uint8_t)instance->config.dlpf_config &
                MPU6050_CONFIG_FIELD_MASK) ||
        !MPU6050InternalWriteRegister(instance,
            MPU6050_REGISTER_SMPLRT_DIV,
            instance->config.sample_rate_divider) ||
        !MPU6050InternalWriteRegister(instance,
            MPU6050_REGISTER_GYRO_CONFIG,
            ((uint8_t)instance->config.gyro_range <<
                MPU6050_FULL_SCALE_SHIFT) & MPU6050_FULL_SCALE_MASK) ||
        !MPU6050InternalWriteRegister(instance,
            MPU6050_REGISTER_ACCEL_CONFIG,
            ((uint8_t)instance->config.accel_range <<
                MPU6050_FULL_SCALE_SHIFT) & MPU6050_FULL_SCALE_MASK)) {
        return false;
    }

    instance->initialized = true;
    return true;
}

static void MPU6050DelayMilliseconds(uint32_t milliseconds)
{
    /* 调度器运行后让出 CPU；启动调度器之前只能使用 BSP 忙等待。 */
    if (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING) {
        TickType_t ticks = pdMS_TO_TICKS(milliseconds);

        if (ticks == 0U) {
            ticks = 1U;
        }
        vTaskDelay(ticks);
    } else {
        BSPDelayMilliseconds(milliseconds);
    }
}

bool MPU6050ReadWhoAmI(
    MPU6050Instance *instance, uint8_t *who_am_i)
{
    return MPU6050InternalIsRegistered(instance) &&
           (who_am_i != NULL) &&
           MPU6050InternalReadRegisters(instance,
               MPU6050_REGISTER_WHO_AM_I, who_am_i, 1U);
}

bool MPU6050ReadRaw(
    MPU6050Instance *instance, MPU6050RawSample *sample)
{
    uint8_t data[MPU6050_BURST_SAMPLE_SIZE];

    if (!MPU6050IsInitialized(instance) || (sample == NULL) ||
        !MPU6050InternalReadRegisters(instance,
            MPU6050_REGISTER_ACCEL_XOUT_H, data, sizeof(data))) {
        return false;
    }

    sample->accel_x = MPU6050InternalDecodeSigned16(data[0], data[1]);
    sample->accel_y = MPU6050InternalDecodeSigned16(data[2], data[3]);
    sample->accel_z = MPU6050InternalDecodeSigned16(data[4], data[5]);
    sample->temperature = MPU6050InternalDecodeSigned16(data[6], data[7]);
    sample->gyro_x = MPU6050InternalDecodeSigned16(data[8], data[9]);
    sample->gyro_y = MPU6050InternalDecodeSigned16(data[10], data[11]);
    sample->gyro_z = MPU6050InternalDecodeSigned16(data[12], data[13]);
    return true;
}

bool MPU6050Read(
    MPU6050Instance *instance, MPU6050Sample *sample)
{
    MPU6050RawSample raw;

    if ((sample == NULL) || !MPU6050ReadRaw(instance, &raw)) {
        return false;
    }

    /* 温度公式来自数据手册：温度(°C) = raw / 340 + 36.53。 */
    sample->accel_x_millig = MPU6050InternalConvertAcceleration(
        raw.accel_x, instance->config.accel_range);
    sample->accel_y_millig = MPU6050InternalConvertAcceleration(
        raw.accel_y, instance->config.accel_range);
    sample->accel_z_millig = MPU6050InternalConvertAcceleration(
        raw.accel_z, instance->config.accel_range);
    sample->temperature_millicelsius =
        MPU6050InternalDivideRoundedSigned(
            (int32_t)raw.temperature * 1000L, 340L) + 36530L;
    sample->gyro_x_millidegrees_per_second =
        MPU6050InternalConvertGyroscope(
            raw.gyro_x, instance->config.gyro_range);
    sample->gyro_y_millidegrees_per_second =
        MPU6050InternalConvertGyroscope(
            raw.gyro_y, instance->config.gyro_range);
    sample->gyro_z_millidegrees_per_second =
        MPU6050InternalConvertGyroscope(
            raw.gyro_z, instance->config.gyro_range);
    return true;
}

bool MPU6050SetSleepEnabled(
    MPU6050Instance *instance, bool enabled)
{
    uint8_t power_management;

    /* DMP 管理自身的电源与 FIFO 状态，运行期间不允许直接切换睡眠位。 */
    if (!MPU6050IsInitialized(instance) ||
        instance->dmp_enabled ||
        !MPU6050InternalReadRegisters(instance,
            MPU6050_REGISTER_PWR_MGMT_1, &power_management, 1U)) {
        return false;
    }

    if (enabled) {
        power_management |= MPU6050_SLEEP_BIT;
    } else {
        power_management = (power_management &
                               (uint8_t)~(MPU6050_SLEEP_BIT |
                                          MPU6050_CLOCK_SOURCE_MASK)) |
                           ((uint8_t)instance->config.clock_source &
                               MPU6050_CLOCK_SOURCE_MASK);
    }
    return MPU6050InternalWriteRegister(instance,
        MPU6050_REGISTER_PWR_MGMT_1, power_management);
}

uint16_t MPU6050GetConfiguredSampleRateHz(
    const MPU6050Instance *instance)
{
    uint32_t gyroscope_output_rate_hz;

    if (!MPU6050InternalIsRegistered(instance)) {
        return 0U;
    }
    if (instance->dmp_enabled) {
        uint16_t dmp_rate = instance->config.dmp_sample_rate_hz;
        return (dmp_rate == 0U) ? MPU6050_DEFAULT_DMP_RATE_HZ : dmp_rate;
    }
    /* DLPF 关闭时陀螺仪基准率为 8 kHz，否则为 1 kHz。 */
    gyroscope_output_rate_hz =
        (instance->config.dlpf_config == MPU6050_DLPF_CONFIG_260_HZ)
            ? 8000UL
            : 1000UL;
    return (uint16_t)(gyroscope_output_rate_hz /
        ((uint32_t)instance->config.sample_rate_divider + 1UL));
}

bool MPU6050IsInitialized(const MPU6050Instance *instance)
{
    return MPU6050InternalIsRegistered(instance) &&
           instance->initialized;
}

static bool MPU6050ConfigIsValid(const MPU6050Config *config)
{
    /* 枚举范围检查保证后续换算查表不会越界。 */
    return (config != NULL) &&
           ((config->i2c_address == MPU6050_I2C_ADDRESS_AD0_LOW) ||
            (config->i2c_address == MPU6050_I2C_ADDRESS_AD0_HIGH)) &&
           (config->accel_range >= MPU6050_ACCEL_RANGE_2G) &&
           (config->accel_range < MPU6050_ACCEL_RANGE_COUNT) &&
           (config->gyro_range >= MPU6050_GYRO_RANGE_250_DPS) &&
           (config->gyro_range < MPU6050_GYRO_RANGE_COUNT) &&
           (config->dlpf_config >= MPU6050_DLPF_CONFIG_260_HZ) &&
           (config->dlpf_config < MPU6050_DLPF_CONFIG_COUNT) &&
           (config->clock_source >= MPU6050_CLOCK_INTERNAL_8MHZ) &&
           (config->clock_source < MPU6050_CLOCK_SOURCE_COUNT) &&
           (config->dmp_sample_rate_hz <= MPU6050_DMP_MAX_RATE_HZ);
}

bool MPU6050InternalIsRegistered(const MPU6050Instance *instance)
{
    return (instance != NULL) && instance->registered &&
           (instance->i2c != NULL) &&
           MPU6050ConfigIsValid(&instance->config);
}

bool MPU6050InternalWriteRegister(
    MPU6050Instance *instance, uint8_t register_address,
    uint8_t value)
{
    /* MPU6050 单寄存器写事务格式为“寄存器地址 + 数据”。 */
    uint8_t data[2] = {register_address, value};

    return MPU6050InternalIsRegistered(instance) &&
           I2CWrite(instance->i2c, instance->config.i2c_address,
               data, sizeof(data));
}

bool MPU6050InternalReadRegisters(
    MPU6050Instance *instance, uint8_t register_address,
    uint8_t *data, size_t size)
{
    return MPU6050InternalIsRegistered(instance) &&
           (data != NULL) && (size > 0U) &&
           I2CWriteRead(instance->i2c,
               instance->config.i2c_address, &register_address, 1U,
               data, size);
}

int16_t MPU6050InternalDecodeSigned16(
    uint8_t high_byte, uint8_t low_byte)
{
    return (int16_t)(((uint16_t)high_byte << 8U) | low_byte);
}

int32_t MPU6050InternalDivideRoundedSigned(
    int32_t numerator, int32_t denominator)
{
    /* 正负分支使用相同舍入幅度，避免 C 语言负数截断造成方向偏差。 */
    if (numerator >= 0L) {
        return (numerator + (denominator / 2L)) / denominator;
    }
    return -(((-numerator) + (denominator / 2L)) / denominator);
}

int32_t MPU6050InternalConvertAcceleration(
    int16_t raw_value, MPU6050AccelRange_e range)
{
    /* 各量程的灵敏度单位均为 LSB/g，数组下标与公开量程枚举一致。 */
    static const int32_t sensitivity_lsb_per_g[] = {
        16384L, 8192L, 4096L, 2048L
    };

    return MPU6050InternalDivideRoundedSigned(
        (int32_t)raw_value * 1000L,
        sensitivity_lsb_per_g[range]);
}

int32_t MPU6050InternalConvertGyroscope(
    int16_t raw_value, MPU6050GyroRange_e range)
{
    /* 灵敏度扩大10倍保存：131.0、65.5、32.8、16.4 LSB/(°/s)。 */
    static const int32_t sensitivity_times_ten[] = {
        1310L, 655L, 328L, 164L
    };

    return MPU6050InternalDivideRoundedSigned(
        (int32_t)raw_value * 10000L,
        sensitivity_times_ten[range]);
}
