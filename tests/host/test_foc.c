/* 磁编码器 + FOC：假 AS5600 挂 host-sim I2C；FOC 用测试里的简化 PMSM 模型闭环。 */
#include <string.h>
#include "tt.h"
#include "board_gen.h"
#include "host_sim.h"
#include "as5600.h"
#include "foc.h"
#include <math.h>

typedef struct { uint16_t raw; uint8_t status; int reads; } fake_as_t;
static dz_err_t as_cb(void *ctx, uint8_t addr7, uint8_t reg, uint8_t *buf, uint16_t n, bool write)
{
    fake_as_t *f = ctx;
    if (addr7 != AS5600_ADDR || write) return DZ_EIO;
    for (uint16_t i = 0; i < n; i++) {
        uint8_t r = (uint8_t)(reg + i), v = 0;
        if (r == 0x0B) v = f->status;
        else if (r == 0x0C) v = (uint8_t)(f->raw >> 8);
        else if (r == 0x0D) v = (uint8_t)f->raw;
        buf[i] = v;
    }
    f->reads++;
    return DZ_OK;
}

TEST(as5600_fake)
{
    host_sim_reset(); pal_init();
    CHECK(as5600_selftest() == DZ_OK);
    fake_as_t f = { 4000, 0x20, 0 };
    host_sim_i2c_attach(RES_I2C_IMU, as_cb, &f);
    as5600_t e; as5600_cfg_t c = { RES_I2C_IMU, 1, 0.0f };
    CHECK(as5600_init(&e, &c) == DZ_OK);
    CHECK(as5600_check_magnet(&e, NULL) == DZ_OK);
    f.status = 0x00; CHECK(as5600_check_magnet(&e, NULL) == DZ_ENODEV);
    f.status = 0x30; CHECK(as5600_check_magnet(&e, NULL) == DZ_EFAIL);
    f.status = 0x20;
    CHECK(as5600_update(&e, 0) == DZ_OK);
    CHECK_NEAR(as5600_angle(&e), 4000 * 6.28318530718 / 4096, 1e-4);
    /* 正转跨零：4000 → 100（+196 计数） */
    f.raw = 100; CHECK(as5600_update(&e, 1000) == DZ_OK);
    CHECK(e.turns == 1);
    CHECK_NEAR(as5600_angle_multi(&e), (4096 + 100) * 6.28318530718 / 4096, 1e-4);
    CHECK_NEAR(as5600_velocity(&e), 196 * 6.28318530718 / 4096 / 1e-3, 0.5);
    /* 高位垃圾位被屏蔽 */
    f.raw = 0xF000 | 200; CHECK(as5600_update(&e, 2000) == DZ_OK && e.raw == 200);
    /* 反转跨零回去 */
    f.raw = 4090; CHECK(as5600_update(&e, 3000) == DZ_OK && e.turns == 0);
    /* 零点 + 反向 */
    CHECK(as5600_set_zero_here(&e) == DZ_OK && as5600_angle_multi(&e) == 0.0f);
    f.raw = 4000; CHECK(as5600_update(&e, 4000) == DZ_OK);
    CHECK_NEAR(as5600_angle_multi(&e), -90 * 6.28318530718 / 4096, 1e-4);
    c.dir = -1; CHECK(as5600_init(&e, &c) == DZ_OK);
    f.raw = 1000; CHECK(as5600_update(&e, 0) == DZ_OK);
    f.raw = 900; CHECK(as5600_update(&e, 1000) == DZ_OK);
    CHECK(as5600_velocity(&e) > 0.0f);                   /* 反向：计数减 = 正转 */
    /* 速度低通 */
    c.dir = 1; c.vel_tau_s = 0.01f; CHECK(as5600_init(&e, &c) == DZ_OK);
    f.raw = 0; (void)as5600_update(&e, 0);
    f.raw = 41; (void)as5600_update(&e, 1000);
    CHECK(as5600_velocity(&e) > 0.0f && as5600_velocity(&e) < 41 * 6.2832f / 4096 / 1e-3f * 0.2f);
    /* I2C 失败 */
    host_sim_fail_next(HS_FAIL_I2C, 1);
    CHECK(as5600_update(&e, 2000) != DZ_OK && e.errors == 1);
    c.dir = 0; CHECK(as5600_init(&e, &c) == DZ_EINVAL);
    host_sim_i2c_attach(RES_I2C_IMU, NULL, NULL);
}


/* ---------- 简化 PMSM：iq = (vq - ke·ωe)/R，转矩 = kt·iq，J dω = T - b·ω ---------- */
typedef struct { int pp; float off_e, th, w, R, ke, kt, J, b, vbus, load; } motor_t;
static void motor_step(motor_t *m, const float du[3], float dt)
{
    float mean = (du[0] + du[1] + du[2]) / 3.0f;
    float va = (du[0] - mean) * m->vbus, vb = (du[1] - mean) * m->vbus, vc = (du[2] - mean) * m->vbus;
    float al = (2.0f * va - vb - vc) / 3.0f, be = (vb - vc) / 1.7320508f, d, q;
    foc_park(al, be, m->pp * m->th + m->off_e, &d, &q);
    float iq = (q - m->ke * m->pp * m->w) / m->R;
    m->w += (m->kt * iq - m->b * m->w - m->load) / m->J * dt;
    m->th += m->w * dt;
}
static motor_t motor_new(void) { motor_t m = { 7, 1.234f, 0.3f, 0, 2.0f, 0.01f, 0.05f, 2e-5f, 2e-4f, 12.0f, 0 }; return m; }
static const foc_cfg_t FCFG = { 7, 12.0f, 6.0f, 3.0f, 0.3f, 2.0f, 4.0f, 0.06f };

TEST(foc_transforms)
{
    CHECK(foc_selftest() == DZ_OK);
    float al, be, d, q, du[3];
    foc_clarke(1.0f, -0.5f, &al, &be);                    /* ia=1, ib=ic=-0.5 → α=1, β=0 */
    CHECK_NEAR(al, 1.0, 1e-5); CHECK_NEAR(be, 0.0, 1e-5);
    foc_park(0.0f, 1.0f, 1.5707963f, &d, &q); CHECK_NEAR(d, 1.0, 1e-5); CHECK_NEAR(q, 0.0, 1e-5);
    /* SVPWM：最大不失真圆幅值 vbus/√3，线电压正弦，占空比 0..1 */
    float vmax = 12.0f / 1.7320508f;
    for (int k = 0; k < 360; k += 7) {
        float th = k * 3.14159265f / 180.0f;
        foc_svpwm(vmax * cosf(th), vmax * sinf(th), 12.0f, du);
        for (int i = 0; i < 3; i++) CHECK(du[i] >= -1e-6f && du[i] <= 1.0f + 1e-6f);
        float vab = (du[0] - du[1]) * 12.0f;
        CHECK_NEAR(vab, vmax * 1.7320508f * cosf(th + 0.5235988f), 1e-3);
    }
    foc_svpwm(100.0f, 0.0f, 12.0f, du);                    /* 超限缩回 */
    CHECK(du[0] <= 1.0f && du[1] >= 0.0f);
    foc_t f; foc_cfg_t c = FCFG; c.pole_pairs = 0; CHECK(foc_init(&f, &c) == DZ_EINVAL);
    CHECK(foc_init(&f, &FCFG) == DZ_OK && f.cfg.v_limit <= vmax);
    CHECK(foc_angle_step(&f, 1.0f, 0.0f, 0.0f, 1e-4f, du) == DZ_ESTATE);
}

TEST(foc_openloop)
{
    motor_t m = motor_new(); foc_t f; float du[3];
    CHECK(foc_init(&f, &FCFG) == DZ_OK);
    float dt = 1e-4f, vel = 0.0f;
    for (int i = 0; i < 40000; i++) {                       /* 4 s 内从 0 斜坡到 20 rad/s */
        vel = i < 20000 ? 20.0f * i / 20000 : 20.0f;
        foc_openloop_step(&f, vel, 2.0f, dt, du); motor_step(&m, du, dt);
    }
    CHECK_NEAR(m.w, 20.0, 0.5);                            /* 同步跟上 */
}

static void run_align(motor_t *m, foc_t *f, int sens_dir, dz_err_t *res)
{
    float du[3]; dz_err_t r = DZ_EBUSY;
    for (int i = 0; i < 200000 && r == DZ_EBUSY; i++) { r = foc_align_step(f, sens_dir * m->th, 1e-4f, du); motor_step(m, du, 1e-4f); }
    *res = r;
}

TEST(foc_align_and_hold)
{
    for (int sd = -1; sd <= 1; sd += 2) {
        motor_t m = motor_new(); foc_t f; dz_err_t r; float du[3];
        CHECK(foc_init(&f, &FCFG) == DZ_OK);
        run_align(&m, &f, sd, &r);
        CHECK(r == DZ_OK && f.state == FOC_READY);
        CHECK(f.dir == sd);
        CHECK_NEAR(f.pp_est, 7.0, 0.5);
        /* 零点：传感器电角度与真实电角度一致（模 2π） */
        float err = foc_norm_angle(foc_elec_angle(&f, sd * m.th) - foc_norm_angle(m.pp * m.th + m.off_e) + 3.14159265f) - 3.14159265f;
        CHECK_NEAR(err, 0.0, 0.05);
        /* 角度闭环：走到 +2 rad（传感器坐标），带恒定负载 */
        float tgt = sd * m.th + 2.0f; m.load = 0.002f;
        for (int i = 0; i < 30000; i++) { (void)foc_angle_step(&f, tgt, sd * m.th, sd * m.w, 1e-4f, du); motor_step(&m, du, 1e-4f); }
        CHECK_NEAR(sd * m.th, tgt, 0.02);
        CHECK_NEAR(m.w, 0.0, 0.1);
    }
}

TEST(foc_align_faults)
{
    motor_t m = motor_new(); foc_t f; dz_err_t r; foc_cfg_t c = FCFG;
    c.pole_pairs = 14; CHECK(foc_init(&f, &c) == DZ_OK);     /* 配错极对数 */
    run_align(&m, &f, 1, &r);
    CHECK(r == DZ_EFAIL && f.state == FOC_FAULT); CHECK_NEAR(f.pp_est, 7.0, 0.5);
    m = motor_new(); m.kt = 0.0f;                            /* 电机没接：不转 */
    CHECK(foc_init(&f, &FCFG) == DZ_OK); run_align(&m, &f, 1, &r);
    CHECK(r == DZ_EFAIL);
    CHECK(foc_set_calibration(&f, 1.0f, 2) == DZ_EINVAL);
    CHECK(foc_set_calibration(&f, -1.0f, -1) == DZ_OK && f.state == FOC_READY && f.zero_e > 0.0f);
}

/* 端到端：假 AS5600 读电机角 → 对齐 → 角度闭环 */
TEST(foc_with_as5600)
{
    host_sim_reset(); pal_init();
    fake_as_t fa = { 0, 0x20, 0 };
    host_sim_i2c_attach(RES_I2C_IMU, as_cb, &fa);
    motor_t m = motor_new(); foc_t f; as5600_t e; float du[3];
    as5600_cfg_t ec = { RES_I2C_IMU, -1, 0.002f };           /* 磁铁装反 */
    CHECK(as5600_init(&e, &ec) == DZ_OK && foc_init(&f, &FCFG) == DZ_OK);
    uint32_t t = 0; dz_err_t r = DZ_EBUSY;
    #define SENSE() do { float a = foc_norm_angle(m.th); fa.raw = (uint16_t)(a / 6.2831853f * 4096) & 0xFFF; as5600_update(&e, t); t += 100; } while (0)
    for (int i = 0; i < 200000 && r == DZ_EBUSY; i++) { SENSE(); r = foc_align_step(&f, as5600_angle_multi(&e), 1e-4f, du); motor_step(&m, du, 1e-4f); }
    CHECK(r == DZ_OK && f.dir == -1);
    float tgt = as5600_angle_multi(&e) - 7.0f;               /* 超过一圈 */
    for (int i = 0; i < 40000; i++) { SENSE(); foc_angle_step(&f, tgt, as5600_angle_multi(&e), as5600_velocity(&e), 1e-4f, du); motor_step(&m, du, 1e-4f); }
    CHECK_NEAR(as5600_angle_multi(&e), tgt, 0.01);
    CHECK(e.errors == 0);
    host_sim_i2c_attach(RES_I2C_IMU, NULL, NULL);
}

void suite_foc(void)
{
    RUN(as5600_fake); RUN(foc_transforms); RUN(foc_openloop); RUN(foc_align_and_hold); RUN(foc_align_faults); RUN(foc_with_as5600);
}
