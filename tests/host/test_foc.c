/* 磁编码器 + FOC：两个模块 2.0.0 起已停用（原实现参照过 GPL 代码，见 docs/参考来源.md 待净室重写清单）。
 * 这里只验证停用是“诚实”的：返回 DZ_ENOTSUP、零输出、不驱动电机。 */
#include <string.h>
#include "tt.h"
#include "as5600.h"
#include "foc.h"

TEST(as5600_disabled)
{
    as5600_t e; as5600_cfg_t c = { 0 }; uint8_t st = 9;
    CHECK(as5600_selftest() == DZ_ENOTSUP);
    CHECK(as5600_init(&e, &c) == DZ_ENOTSUP);
    CHECK(as5600_check_magnet(&e, &st) == DZ_ENOTSUP && st == 0u);
    CHECK(as5600_update(&e, 1000) == DZ_ENOTSUP && as5600_angle(&e) == 0.0f && as5600_velocity(&e) == 0.0f);
    CHECK(as5600_set_zero_here(&e) == DZ_ENOTSUP);
}

TEST(foc_disabled)
{
    foc_t f; foc_cfg_t c; float du[3] = { 1, 1, 1 }; uint16_t o[3] = { 1, 1, 1 };
    memset(&c, 0, sizeof c); c.pole_pairs = 7; c.vbus = 12.0f; c.v_limit = 6.0f;
    CHECK(foc_selftest() == DZ_ENOTSUP);
    CHECK(foc_init(&f, &c) == DZ_ENOTSUP && f.state == FOC_FAULT);
    CHECK(foc_align_step(&f, 0.1f, 1e-3f, du) == DZ_ENOTSUP && du[0] == 0.0f && du[1] == 0.0f && du[2] == 0.0f);
    du[0] = 1; CHECK(foc_pos_step(&f, 1.0f, 0.0f, 0.0f, 1e-3f, du) == DZ_ENOTSUP && du[0] == 0.0f);
    du[0] = 1; CHECK(foc_velocity_step(&f, 1.0f, 0.0f, 0.0f, 1e-3f, du) == DZ_ENOTSUP && du[0] == 0.0f);
    du[0] = 1; foc_openloop_step(&f, 5.0f, 3.0f, 1e-3f, du); CHECK(du[0] == 0.0f);
    foc_duty_to_pal(du, o); CHECK(o[0] == 0u && o[1] == 0u && o[2] == 0u);
}

void suite_foc(void)
{
    RUN(as5600_disabled); RUN(foc_disabled);
}
