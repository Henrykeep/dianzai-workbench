/*
 * MPU6050 DMP 适配层：配置 InvenSense 参考驱动、读取 FIFO，并以纯定点算法
 * 把 Q30 四元数换算为毫度姿态角，避免在 Cortex-M0+ 上引入浮点运算。
 */
#include "modules/mpu6050/mpu6050.h"

#include "modules/mpu6050/inv_mpu.h"
#include "modules/mpu6050/inv_mpu_dmp_motion_driver.h"
#include "modules/mpu6050/mpu6050_internal.h"

/* 温度寄存器入口；Q30 中 1.0 对应 2^30。 */
#define MPU6050_REGISTER_TEMP_OUT_H (0x41U)
#define MPU6050_Q30_ONE             ((int64_t)1073741824LL)

/* FIFO 同时输出六轴数据和四元数，并启用陀螺仪自动校准。 */
#define MPU6050_DEFAULT_DMP_FEATURES \
    (DMP_FEATURE_6X_LP_QUAT | DMP_FEATURE_SEND_RAW_ACCEL | \
     DMP_FEATURE_SEND_CAL_GYRO | DMP_FEATURE_GYRO_CAL)

static unsigned short MPU6050DmpOrientationToScalar(
    const signed char *matrix);
static unsigned short MPU6050DmpLpfToHz(MPU6050DLPFConfig_e config);
static int64_t MPU6050DmpMultiplyQ30(int32_t left, int32_t right);
static uint64_t MPU6050DmpSqrtQ30(uint64_t value);
static int32_t MPU6050DmpAtan2Millidegrees(
    int64_t y, int64_t x);
static int32_t MPU6050DmpAsinMillidegrees(int64_t sine_q30);
static void MPU6050DmpQuaternionToAngles(
    const long *quaternion, MPU6050DmpSample *sample);

bool MPU6050DmpInitialize(MPU6050Instance *instance)
{
    unsigned short dmp_rate;
    unsigned short dmp_features = MPU6050_DEFAULT_DMP_FEATURES;
    int dmp_lpf_hz;

    /* 参考实现的 DMP 固件只支持 MPU6050，且输出基准频率为 200 Hz。 */
    if (!MPU6050InternalIsRegistered(instance) ||
        !instance->config.enable_dmp) {
        return false;
    }

    dmp_rate = instance->config.dmp_sample_rate_hz;
    if (dmp_rate == 0U)
        dmp_rate = MPU6050_DEFAULT_DMP_RATE_HZ;
    if ((dmp_rate == 0U) || (dmp_rate > MPU6050_DMP_MAX_RATE_HZ))
        return false;

    instance->initialized = false;
    instance->dmp_enabled = false;

    /* 先配置基础六轴量程和 FIFO，再加载 DMP 固件及输出特性。 */
    if ((mpu_set_address(instance->config.i2c_address) != 0) ||
        (mpu_init() != 0) ||
        (mpu_set_sensors(INV_XYZ_GYRO | INV_XYZ_ACCEL) != 0) ||
        (mpu_configure_fifo(INV_XYZ_GYRO | INV_XYZ_ACCEL) != 0) ||
        (mpu_set_gyro_fsr(
            (unsigned short)(250U << instance->config.gyro_range)) != 0) ||
        (mpu_set_accel_fsr(
            (unsigned char)(2U << instance->config.accel_range)) != 0)) {
        return false;
    }

    dmp_lpf_hz = (int)MPU6050DmpLpfToHz(instance->config.dlpf_config);
    if ((mpu_set_sample_rate(200U) != 0) ||
        (mpu_set_lpf((unsigned short)dmp_lpf_hz) != 0) ||
        (dmp_load_motion_driver_firmware() != 0) ||
        (dmp_set_orientation(MPU6050DmpOrientationToScalar(
            (const signed char[]){-1, 0, 0, 0, -1, 0, 0, 0, 1})) != 0) ||
        (dmp_enable_feature(dmp_features) != 0) ||
        (dmp_set_fifo_rate(dmp_rate) != 0) ||
        (mpu_set_dmp_state(1U) != 0) ||
        /* mpu_set_dmp_state() 恢复 200 Hz 基准速率，随后恢复配置的 DLPF。 */
        (mpu_set_lpf((unsigned short)dmp_lpf_hz) != 0)) {
        return false;
    }

    instance->dmp_enabled = true;
    instance->initialized = true;
    return true;
}

bool MPU6050ReadDmp(
    MPU6050Instance *instance, MPU6050DmpSample *sample)
{
    MPU6050DmpSample decoded = {0};
    uint8_t temperature_data[2];
    short gyro[3] = {0};
    short accel[3] = {0};
    long quaternion[4] = {0};
    unsigned long timestamp = 0UL;
    short sensor_flags = 0;
    unsigned char more = 0U;
    int result;

    if (!MPU6050IsDmpEnabled(instance) || (sample == NULL))
        return false;

    /* FIFO 积压多帧时丢弃旧帧，只向调用者发布最新的完整姿态样本。 */
    do {
        result = dmp_read_fifo(gyro, accel, quaternion, &timestamp,
            &sensor_flags, &more);
        if (result != 0)
            return false;
    } while (more != 0U);

    if (((sensor_flags & INV_WXYZ_QUAT) == 0) ||
        ((sensor_flags & INV_XYZ_ACCEL) == 0) ||
        ((sensor_flags & INV_XYZ_GYRO) == 0)) {
        return false;
    }

    /* DMP FIFO 不含温度，因此另外读取温度寄存器后再组装统一样本。 */
    if (!MPU6050InternalReadRegisters(instance, MPU6050_REGISTER_TEMP_OUT_H,
            temperature_data, sizeof(temperature_data))) {
        return false;
    }

    decoded.sample.accel_x_millig = MPU6050InternalConvertAcceleration(
        accel[0], instance->config.accel_range);
    decoded.sample.accel_y_millig = MPU6050InternalConvertAcceleration(
        accel[1], instance->config.accel_range);
    decoded.sample.accel_z_millig = MPU6050InternalConvertAcceleration(
        accel[2], instance->config.accel_range);
    decoded.sample.temperature_millicelsius =
        MPU6050InternalDivideRoundedSigned(
            (int32_t)MPU6050InternalDecodeSigned16(
                temperature_data[0], temperature_data[1]) * 1000L,
            340L) + 36530L;
    decoded.sample.gyro_x_millidegrees_per_second =
        MPU6050InternalConvertGyroscope(
            gyro[0], instance->config.gyro_range);
    decoded.sample.gyro_y_millidegrees_per_second =
        MPU6050InternalConvertGyroscope(
            gyro[1], instance->config.gyro_range);
    decoded.sample.gyro_z_millidegrees_per_second =
        MPU6050InternalConvertGyroscope(
            gyro[2], instance->config.gyro_range);

    decoded.quaternion_w_q30 = (int32_t)quaternion[0];
    decoded.quaternion_x_q30 = (int32_t)quaternion[1];
    decoded.quaternion_y_q30 = (int32_t)quaternion[2];
    decoded.quaternion_z_q30 = (int32_t)quaternion[3];
    decoded.timestamp_ms = (uint32_t)timestamp;
    decoded.sensor_flags = (uint16_t)sensor_flags;
    MPU6050DmpQuaternionToAngles(quaternion, &decoded);
    /* 所有字段成功解码后整体提交，失败路径不会留下半更新的输出。 */
    *sample = decoded;
    return true;
}

bool MPU6050IsDmpEnabled(const MPU6050Instance *instance)
{
    return MPU6050IsInitialized(instance) && instance->dmp_enabled;
}

/* 将 3×3 轴方向矩阵转换为 InvenSense DMP 的 9 位标量。 */
static unsigned short MPU6050DmpOrientationToScalar(
    const signed char *matrix)
{
    unsigned short scalar = 0U;
    unsigned short row_scale;
    unsigned int row;

    for (row = 0U; row < 3U; ++row) {
        if (matrix[row * 3U] > 0)
            row_scale = 0U;
        else if (matrix[row * 3U] < 0)
            row_scale = 4U;
        else if (matrix[row * 3U + 1U] > 0)
            row_scale = 1U;
        else if (matrix[row * 3U + 1U] < 0)
            row_scale = 5U;
        else if (matrix[row * 3U + 2U] > 0)
            row_scale = 2U;
        else if (matrix[row * 3U + 2U] < 0)
            row_scale = 6U;
        else
            row_scale = 7U;
        scalar |= (unsigned short)(row_scale << (row * 3U));
    }
    return scalar;
}

static unsigned short MPU6050DmpLpfToHz(MPU6050DLPFConfig_e config)
{
    /* 参考驱动接受整数带宽，取最接近公开 DLPF 枚举的 MPU6050 标称值。 */
    static const unsigned short lpf_hz[MPU6050_DLPF_CONFIG_COUNT] = {
        256U, 188U, 98U, 42U, 20U, 10U, 5U
    };

    return lpf_hz[config];
}

/* Q30 乘法；所有中间值使用 64 位，避免 Cortex-M0+ 上的 32 位溢出。 */
static int64_t MPU6050DmpMultiplyQ30(int32_t left, int32_t right)
{
    return ((int64_t)left * (int64_t)right) >> 30;
}

/* 返回 Q30 定点数平方根，输入和输出均为非负 Q30 数。 */
static uint64_t MPU6050DmpSqrtQ30(uint64_t value)
{
    uint64_t scaled_value = value << 30;
    uint64_t root = 0U;
    uint64_t bit = (uint64_t)1U << 62;

    while (bit > scaled_value)
        bit >>= 2;
    while (bit != 0U) {
        if (scaled_value >= (root + bit)) {
            scaled_value -= root + bit;
            root = (root >> 1) + bit;
        } else {
            root >>= 1;
        }
        bit >>= 2;
    }
    return root;
}

/* CORDIC 向量模式，输出范围为 -180000～180000 毫度。 */
static int32_t MPU6050DmpAtan2Millidegrees(int64_t y, int64_t x)
{
    static const int32_t atan_table_millidegrees[16] = {
        45000, 26565, 14036, 7125, 3564, 1782, 891, 446,
        223, 111, 56, 28, 14, 7, 3, 2
    };
    int64_t x_work = x;
    int64_t y_work = y;
    int64_t next_x;
    int32_t angle = 0;
    int32_t base_angle = 0;
    unsigned int index;

    if ((x_work == 0) && (y_work == 0))
        return 0;

    if (x_work < 0) {
        base_angle = (y_work >= 0) ? 180000 : -180000;
        x_work = -x_work;
        y_work = -y_work;
    }

    for (index = 0U; index < 16U; ++index) {
        if (y_work > 0) {
            next_x = x_work + (y_work >> index);
            y_work -= x_work >> index;
            angle += atan_table_millidegrees[index];
        } else {
            next_x = x_work - (y_work >> index);
            y_work += x_work >> index;
            angle -= atan_table_millidegrees[index];
        }
        x_work = next_x;
    }

    return base_angle + angle;
}

static int32_t MPU6050DmpAsinMillidegrees(int64_t sine_q30)
{
    uint64_t sine_squared;
    uint64_t cosine_squared;
    uint64_t cosine_q30;

    /* 限幅用于吸收四元数定点舍入误差，避免 1-sin^2 出现负数。 */
    if (sine_q30 > MPU6050_Q30_ONE)
        sine_q30 = MPU6050_Q30_ONE;
    else if (sine_q30 < -MPU6050_Q30_ONE)
        sine_q30 = -MPU6050_Q30_ONE;

    sine_squared = (uint64_t)((sine_q30 * sine_q30) >> 30);
    cosine_squared = (uint64_t)MPU6050_Q30_ONE - sine_squared;
    cosine_q30 = MPU6050DmpSqrtQ30(cosine_squared);
    return MPU6050DmpAtan2Millidegrees(
        sine_q30, (int64_t)cosine_q30);
}

static void MPU6050DmpQuaternionToAngles(
    const long *quaternion, MPU6050DmpSample *sample)
{
    /* 四元数顺序为 w、x、y、z；输出采用 pitch、roll、yaw 欧拉角。 */
    int32_t q0 = (int32_t)quaternion[0];
    int32_t q1 = (int32_t)quaternion[1];
    int32_t q2 = (int32_t)quaternion[2];
    int32_t q3 = (int32_t)quaternion[3];
    int64_t q0q0 = MPU6050DmpMultiplyQ30(q0, q0);
    int64_t q1q1 = MPU6050DmpMultiplyQ30(q1, q1);
    int64_t q2q2 = MPU6050DmpMultiplyQ30(q2, q2);
    int64_t q3q3 = MPU6050DmpMultiplyQ30(q3, q3);
    int64_t q0q1 = MPU6050DmpMultiplyQ30(q0, q1);
    int64_t q0q2 = MPU6050DmpMultiplyQ30(q0, q2);
    int64_t q0q3 = MPU6050DmpMultiplyQ30(q0, q3);
    int64_t q1q2 = MPU6050DmpMultiplyQ30(q1, q2);
    int64_t q1q3 = MPU6050DmpMultiplyQ30(q1, q3);
    int64_t q2q3 = MPU6050DmpMultiplyQ30(q2, q3);
    int64_t pitch_sine = 2 * (q0q2 - q1q3);
    int64_t roll_y = 2 * (q0q1 + q2q3);
    int64_t roll_x = MPU6050_Q30_ONE - 2 * (q1q1 + q2q2);
    int64_t yaw_y = 2 * (q0q3 + q1q2);
    int64_t yaw_x = q0q0 + q1q1 - q2q2 - q3q3;

    sample->pitch_millidegrees = MPU6050DmpAsinMillidegrees(pitch_sine);
    sample->roll_millidegrees = MPU6050DmpAtan2Millidegrees(
        roll_y, roll_x);
    sample->yaw_millidegrees = MPU6050DmpAtan2Millidegrees(
        yaw_y, yaw_x);
}
