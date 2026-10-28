/**
 * @file app_main.c
 * @brief IMU 姿态模块：BMI088（SPI）→ 零偏标定 → 互补滤波 → UART 发 dzimu 帧（firmware/proto/dzimu）。
 *
 * 只用逻辑资源（RES_SPI_IMU_ACC / RES_SPI_IMU_GYR / RES_UART_IMU），换板只改 board.yaml。
 *  - 采样 1 kHz（主循环按 pal_micros 节拍轮询，没用定时器中断：SPI 读是阻塞的，不放中断里）
 *  - 输出 200 Hz：每 5 次采样发一帧
 *  - 开机静止 1 s 标定陀螺零偏（这段时间不要动板子）；标定失败照常输出，status 里不置 BIAS_OK
 *  - 读失败：status 清 ACC_OK/GYR_OK，继续发帧，主控侧据此降级（不用 IMU 前馈）
 * 【未验证】真 C 型板上没跑过；姿态滤波的 tau 没在真车振动下调过。
 */
#include <math.h>
#include "board_gen.h"
#include "app.h"
#include "pal.h"
#include "bmi088.h"
#include "attitude.h"
#include "dzimu.h"

#define SAMPLE_US   1000u
#define OUT_DIV     5u
#define CALIB_N     1000u
#define RAD2DEG     57.29577951f

static bmi088_t s_imu;
static attitude_t s_att;
static uint8_t s_status, s_seq;
static uint32_t s_next_us, s_n;

dz_err_t app_init(void)
{
    bmi088_cfg_t c = bmi088_cfg_default(RES_SPI_IMU_ACC, RES_SPI_IMU_GYR);
    dz_err_t e = bmi088_init(&s_imu, &c);
    attitude_init(&s_att, 0.5f, 0.15f);
    if (e == DZ_OK) {
        s_status = DZIMU_ST_ACC_OK | DZIMU_ST_GYR_OK;
        if (bmi088_calib_gyro(&s_imu, CALIB_N, 1u) == DZ_OK) s_status |= DZIMU_ST_BIAS_OK;
    }
    s_next_us = pal_micros();
    return DZ_OK;   /* IMU 起不来也不进故障：照常发帧（status=0），主控能看到原因 */
}

void app_loop(void)
{
    uint32_t now = pal_micros();
    if ((int32_t)(now - s_next_us) < 0) return;
    s_next_us += SAMPLE_US;
    if ((int32_t)(now - s_next_us) > (int32_t)(10u * SAMPLE_US)) s_next_us = now + SAMPLE_US;   /* 落后太多：重新对齐 */

    static bmi088_data_t d;
    if (s_imu.ok && bmi088_read(&s_imu, &d) == DZ_OK) {
        s_status |= DZIMU_ST_ACC_OK | DZIMU_ST_GYR_OK;
        if (d.acc_sat) s_status |= DZIMU_ST_ACC_SAT; else s_status &= (uint8_t)~DZIMU_ST_ACC_SAT;
        if (attitude_update(&s_att, d.acc, d.gyr, SAMPLE_US * 1e-6f) == DZ_OK && s_att.inited) s_status |= DZIMU_ST_ATT_OK;
    } else {
        s_status &= (uint8_t)~(DZIMU_ST_ACC_OK | DZIMU_ST_GYR_OK);
    }
    if (++s_n % OUT_DIV) return;
    dzimu_sample_t s = { pal_millis(), { d.acc[0], d.acc[1], d.acc[2] }, { d.gyr[0], d.gyr[1], d.gyr[2] },
                         s_att.roll * RAD2DEG, s_att.pitch * RAD2DEG, s_status };
    dzframe_t f;
    uint8_t buf[DZFRAME_MAX_FRAME];
    if (dzimu_encode(&s, s_seq++, &f)) {
        size_t n = dzframe_encode(buf, sizeof buf, &f);
        if (n) (void)pal_uart_write(RES_UART_IMU, buf, (uint16_t)n);
    }
}
