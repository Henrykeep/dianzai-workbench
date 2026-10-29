/**
 * io 胶水 · IMU 来源（从 io_main.c 原样拆出，2026-10-29，行为不变）。
 * IMU（可选，编译期按板上资源选来源，填 io_in.imu_ax_mps2 / imu_rx_ms / imu_ok，给 ff_src=1 的加速度前馈用）：
 *   板上有 uart IMU → 收姿态模块的 dzimu 帧（RM C 型板跑 apps/imu_module）；
 *   否则有 i2c IMU   → 直接轮询 MPU6050（每 2 ms 一次，阻塞约 0.4 ms @400 kHz）；
 *   都没有           → imu_ok 恒 false，前馈自动回退为 0。
 *   安装方向用参数 imu_axis 选（0..5 = 模块 +x -x +y -y +z -z 指向车头）。
 *   去重力：imu_grav_comp=1（默认）时，uart 姿态模块路径用模块给的 roll/pitch 减掉重力分量（dzimu_linear_acc），
 *   姿态未收敛的帧视为不可用（imu_ok=0）；MPU6050 直连路径没有姿态解算，仍含重力（未处理，坡道上会偏）。
 */
#include "board_gen.h"
#include "io_parts.h"
#if defined(RES_UART_IMU)
#include "dzimu.h"
#include "dzframe.h"
#define IO_IMU_UART 1
static dzframe_parser_t IL;   /* IMU 姿态模块帧 */
#elif defined(RES_I2C_IMU)
#include "dzimu.h"
#include "mpu6050.h"
#define IO_IMU_MPU 1
static mpu6050_t MPU;
#endif

void io_imu_init(void)
{
#if defined(IO_IMU_UART)
    dzframe_parser_init(&IL);
#elif defined(IO_IMU_MPU)
    {   /* IMU 起不来不算致命：imu_ok 保持 false，前馈回退为 0 */
        mpu6050_cfg_t mc = mpu6050_cfg_default(RES_I2C_IMU);
        if (mpu6050_init(&MPU, &mc) == DZ_OK) (void)mpu6050_calib_gyro(&MPU, 200u, 1u);
    }
#endif
}

void io_imu_read(uint32_t now, const params_t *p)
{
#if defined(IO_IMU_UART)
    uint8_t buf[64]; uint16_t got = 0, i;
    if (pal_uart_read(RES_UART_IMU, buf, sizeof buf, &got) == DZ_OK) {
        dzframe_t f; dzimu_sample_t s;
        for (i = 0; i < got; i++)
            if (dzframe_feed(&IL, buf[i], &f) && dzimu_decode(&f, &s)) {
                float lin[3];
                bool att = dzimu_linear_acc(&s, lin);
                io_state()->io_in.imu_ok = (s.status & DZIMU_ST_ACC_OK) && !(s.status & DZIMU_ST_ACC_SAT) && (att || !p->imu_grav_comp);
                if (io_state()->io_in.imu_ok) {
                    io_state()->io_in.imu_ax_mps2 = dzimu_axis(p->imu_grav_comp ? lin : s.acc, p->imu_axis);
                    io_state()->io_in.imu_rx_ms = now;
                }
            }
    }
#elif defined(IO_IMU_MPU)
    mpu6050_data_t d;
    if (!MPU.ok || now % 2u) return;
    io_state()->io_in.imu_ok = mpu6050_read(&MPU, &d) == DZ_OK && !d.acc_sat;
    if (io_state()->io_in.imu_ok) { io_state()->io_in.imu_ax_mps2 = dzimu_axis(d.acc, p->imu_axis); io_state()->io_in.imu_rx_ms = now; }
#else
    (void)now; (void)p;
    io_state()->io_in.imu_ok = false;
#endif
}
