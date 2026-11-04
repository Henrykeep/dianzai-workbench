/**
 * @file mpu6050.h
 * @brief MPU6050 基础采样、定点单位换算和可选 DMP 姿态读取接口。
 */
#ifndef MPU6050_H
#define MPU6050_H

#include <stdbool.h>
#include <stdint.h>

/* AD0 引脚分别接低电平或高电平时对应的 7 位 I2C 地址。 */
#define MPU6050_I2C_ADDRESS_AD0_LOW  (0x68U)
#define MPU6050_I2C_ADDRESS_AD0_HIGH (0x69U)

/** 加速度计满量程选择。 */
typedef enum {
    MPU6050_ACCEL_RANGE_2G = 0,
    MPU6050_ACCEL_RANGE_4G,
    MPU6050_ACCEL_RANGE_8G,
    MPU6050_ACCEL_RANGE_16G,
    MPU6050_ACCEL_RANGE_COUNT
} MPU6050AccelRange_e;

/** 陀螺仪满量程选择。 */
typedef enum {
    MPU6050_GYRO_RANGE_250_DPS = 0,
    MPU6050_GYRO_RANGE_500_DPS,
    MPU6050_GYRO_RANGE_1000_DPS,
    MPU6050_GYRO_RANGE_2000_DPS,
    MPU6050_GYRO_RANGE_COUNT
} MPU6050GyroRange_e;

/**
 * 数字低通滤波器配置；名称采用加速度计的近似带宽。
 * CONFIG_260_HZ 对应 DLPF_CFG=0，其余依次对应1～6。
 */
typedef enum {
    MPU6050_DLPF_CONFIG_260_HZ = 0,
    MPU6050_DLPF_CONFIG_184_HZ,
    MPU6050_DLPF_CONFIG_94_HZ,
    MPU6050_DLPF_CONFIG_44_HZ,
    MPU6050_DLPF_CONFIG_21_HZ,
    MPU6050_DLPF_CONFIG_10_HZ,
    MPU6050_DLPF_CONFIG_5_HZ,
    MPU6050_DLPF_CONFIG_COUNT
} MPU6050DLPFConfig_e;

/** PWR_MGMT_1 的时钟源选择。 */
typedef enum {
    MPU6050_CLOCK_INTERNAL_8MHZ = 0,
    MPU6050_CLOCK_PLL_X_GYRO,
    MPU6050_CLOCK_PLL_Y_GYRO,
    MPU6050_CLOCK_PLL_Z_GYRO,
    MPU6050_CLOCK_SOURCE_COUNT
} MPU6050ClockSource_e;

/** MPU6050 注册和初始化配置。 */
typedef struct {
    /* 7 位 I2C 地址，只接受上面的 AD0_LOW 或 AD0_HIGH。 */
    uint8_t i2c_address;
    /* 采样分频寄存器值；输出率为陀螺仪基准率除以 (divider + 1)。 */
    uint8_t sample_rate_divider;
    MPU6050AccelRange_e accel_range;
    MPU6050GyroRange_e gyro_range;
    MPU6050DLPFConfig_e dlpf_config;
    MPU6050ClockSource_e clock_source;
    /* 启用外部 InvenSense DMP；false 时保持基础寄存器读取路径。 */
    bool enable_dmp;
    /* DMP FIFO 输出频率，0 表示使用驱动默认值。 */
    uint16_t dmp_sample_rate_hz;
} MPU6050Config;

/** 14字节连续输出寄存器对应的原始有符号数据。 */
typedef struct {
    int16_t accel_x;
    int16_t accel_y;
    int16_t accel_z;
    int16_t temperature;
    int16_t gyro_x;
    int16_t gyro_y;
    int16_t gyro_z;
} MPU6050RawSample;

/** 不使用浮点的工程单位数据。 */
typedef struct {
    int32_t accel_x_millig;
    int32_t accel_y_millig;
    int32_t accel_z_millig;
    int32_t temperature_millicelsius;
    int32_t gyro_x_millidegrees_per_second;
    int32_t gyro_y_millidegrees_per_second;
    int32_t gyro_z_millidegrees_per_second;
} MPU6050Sample;

/** DMP 输出的四元数、原始六轴数据和姿态角。 */
typedef struct {
    /* 与基础读取接口相同的工程单位数据。 */
    MPU6050Sample sample;
    /* DMP 四元数为 Q30 格式，1.0 对应 1073741824。 */
    int32_t quaternion_w_q30;
    int32_t quaternion_x_q30;
    int32_t quaternion_y_q30;
    int32_t quaternion_z_q30;
    /* 姿态角单位为 0.001 度；使用定点 CORDIC 计算。 */
    int32_t pitch_millidegrees;
    int32_t roll_millidegrees;
    int32_t yaw_millidegrees;
    /* DMP FIFO 给出的采样时间戳，单位为毫秒。 */
    uint32_t timestamp_ms;
    /* InvenSense 驱动返回的 INV_* 有效数据位图。 */
    uint16_t sensor_flags;
} MPU6050DmpSample;

/** MPU6050 不透明实例；当前工程将其绑定到独立的 I2C1 总线。 */
typedef struct MPU6050Instance MPU6050Instance;

/** 注册 MPU6050 配置并绑定独立的 PB2(SCL)/PB3(SDA) I2C1 总线。 */
MPU6050Instance *MPU6050Register(const MPU6050Config *config);

/** 检查 WHO_AM_I、复位芯片并写入基础量程、DLPF和采样分频配置。 */
bool MPU6050Initialize(MPU6050Instance *instance);

/** 读取 WHO_AM_I；正常 MPU6050 返回 0x68。初始化前也可调用。 */
bool MPU6050ReadWhoAmI(
    MPU6050Instance *instance, uint8_t *who_am_i);

/** 一次连续读取加速度、温度和陀螺仪的14字节原始数据。 */
bool MPU6050ReadRaw(
    MPU6050Instance *instance, MPU6050RawSample *sample);

/** 读取并换算为 mg、m°C 和 mdps，不引入浮点运算。 */
bool MPU6050Read(
    MPU6050Instance *instance, MPU6050Sample *sample);

/** 初始化参考驱动中的 MPU6050 DMP；需在 MPU6050Initialize 成功后显式调用。 */
bool MPU6050DmpInitialize(MPU6050Instance *instance);

/** 轮询 DMP FIFO，读取四元数、六轴数据和姿态角。 */
bool MPU6050ReadDmp(
    MPU6050Instance *instance, MPU6050DmpSample *sample);

/** 进入或退出睡眠模式；退出时恢复配置的时钟源。 */
bool MPU6050SetSleepEnabled(
    MPU6050Instance *instance, bool enabled);

/** 返回由 DLPF 和 SMPLRT_DIV 配置决定的标称输出采样率。 */
uint16_t MPU6050GetConfiguredSampleRateHz(
    const MPU6050Instance *instance);

/** 返回实例是否已经通过 WHO_AM_I 检查并完成硬件配置。 */
bool MPU6050IsInitialized(const MPU6050Instance *instance);

/** 返回 DMP 是否已经成功加载固件并处于运行状态。 */
bool MPU6050IsDmpEnabled(const MPU6050Instance *instance);

#endif
