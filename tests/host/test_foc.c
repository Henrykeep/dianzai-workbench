/* 磁编码器 + FOC：假 AS5600 挂 host-sim I2C；FOC 用测试里的简化 PMSM 模型闭环。 */
#include <string.h>
#include "tt.h"
#include "board_gen.h"
#include "host_sim.h"
#include "as5600.h"

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

void suite_foc(void)
{
    RUN(as5600_fake);
}
