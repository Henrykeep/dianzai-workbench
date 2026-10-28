#include <limits.h>
#include "tt.h"
#include "board_gen.h"
#include "host_sim.h"
#include "motor_dc.h"
#include "encoder.h"

static motor_dc_cfg_t mcfg(void)
{
    motor_dc_cfg_t c = motor_dc_cfg_default();
    c.pwm = RES_PWM_MOTOR_A; c.in1 = RES_GPIO_MOTOR_A_IN1; c.in2 = RES_GPIO_MOTOR_A_IN2;
    return c;
}
static void fresh(void) { host_sim_reset(); pal_init(); }

TEST(motor_invalid_cfg)
{
    fresh();
    motor_dc_t m; motor_dc_cfg_t c;
    c = mcfg(); c.in2 = PAL_ID_NONE;      CHECK(motor_dc_init(&m, &c) == DZ_EINVAL);
    c = mcfg(); c.mode = MOTOR_DC_PWM_DIR; CHECK(motor_dc_init(&m, &c) == DZ_EINVAL); /* DIR 模式 in2 必须为 NONE */
    c = mcfg(); c.deadband = 0.6f;        CHECK(motor_dc_init(&m, &c) == DZ_EINVAL);
    c = mcfg(); c.max_duty = 0.0f;        CHECK(motor_dc_init(&m, &c) == DZ_EINVAL);
    c = mcfg(); c.deadband = 0.3f; c.max_duty = 0.3f; CHECK(motor_dc_init(&m, &c) == DZ_EINVAL);
    c = mcfg(); c.pwm = 7;                CHECK(motor_dc_init(&m, &c) == DZ_ENODEV); /* 板上不存在的 ID */
    motor_dc_t z = {0};
    CHECK(motor_dc_set(&z, 0.5f) == DZ_ESTATE);
}

TEST(motor_direction_change_order)
{
    fresh();
    motor_dc_t m; motor_dc_cfg_t c = mcfg();
    CHECK(motor_dc_init(&m, &c) == DZ_OK);
    motor_dc_set(&m, 0.5f);
    host_sim_events(0, 0);
    CHECK(motor_dc_set(&m, -0.5f) == DZ_OK);
    host_sim_ev_t ev[8]; unsigned n = host_sim_events(ev, 8);
    /* 必须：PWM=0 -> IN1 -> IN2 -> PWM=5000 */
    CHECK(n == 4);
    CHECK(ev[0].type == HS_EV_PWM && ev[0].value == 0);
    CHECK(ev[1].type == HS_EV_GPIO && ev[2].type == HS_EV_GPIO);
    CHECK(ev[3].type == HS_EV_PWM && ev[3].value == 5000);
    CHECK(!host_sim_gpio_level(RES_GPIO_MOTOR_A_IN1) && host_sim_gpio_level(RES_GPIO_MOTOR_A_IN2));
    /* 同方向改占空比不碰方向脚 */
    motor_dc_set(&m, -0.2f);
    n = host_sim_events(ev, 8);
    CHECK(n == 1 && ev[0].type == HS_EV_PWM);
}

TEST(motor_deadband_maxduty_invert_nan)
{
    fresh();
    motor_dc_t m; motor_dc_cfg_t c = mcfg();
    c.deadband = 0.1f; c.max_duty = 0.8f;
    motor_dc_init(&m, &c);
    motor_dc_set(&m, 0.001f); CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_A) >= 1000);
    motor_dc_set(&m, 1.0f);   CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_A) == 8000);
    motor_dc_set(&m, 3.0f);   CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_A) == 8000);
    motor_dc_set(&m, 0.0f);   CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_A) == 0);
    motor_dc_set(&m, NAN);    CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_A) == 0);
    c = mcfg(); c.invert = true;
    motor_dc_init(&m, &c);
    motor_dc_set(&m, 0.5f);
    CHECK(!host_sim_gpio_level(RES_GPIO_MOTOR_A_IN1) && host_sim_gpio_level(RES_GPIO_MOTOR_A_IN2));
    CHECK_NEAR(motor_dc_get_cmd(&m), 0.5f, 1e-6);        /* 读回的是逻辑指令，不是物理方向 */
}

TEST(motor_brake_coast_and_fault)
{
    fresh();
    motor_dc_t m; motor_dc_cfg_t c = mcfg();
    motor_dc_init(&m, &c);
    motor_dc_set(&m, 0.5f);
    motor_dc_stop(&m, MOTOR_DC_BRAKE);
    CHECK(host_sim_gpio_level(RES_GPIO_MOTOR_A_IN1) && host_sim_gpio_level(RES_GPIO_MOTOR_A_IN2));
    CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_A) == 0);
    motor_dc_stop(&m, MOTOR_DC_COAST);
    CHECK(!host_sim_gpio_level(RES_GPIO_MOTOR_A_IN1) && !host_sim_gpio_level(RES_GPIO_MOTOR_A_IN2));
    host_sim_fail_next(HS_FAIL_PWM, 1);
    CHECK(motor_dc_set(&m, 0.5f) == DZ_EIO);              /* 底层错误原样上报 */
    CHECK(motor_dc_set(&m, 0.5f) == DZ_OK);
    CHECK(motor_dc_selftest(&m, 0.3f, 10) == DZ_OK);
    CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_A) == 0);       /* 自检结束后电机停 */
}

TEST(motor_dir_mode)
{
    fresh();
    motor_dc_t m; motor_dc_cfg_t c = mcfg();
    c.mode = MOTOR_DC_PWM_DIR; c.in2 = PAL_ID_NONE;
    CHECK(motor_dc_init(&m, &c) == DZ_OK);
    motor_dc_set(&m, -0.4f);
    CHECK(!host_sim_gpio_level(RES_GPIO_MOTOR_A_IN1));
    motor_dc_set(&m, 0.4f);
    CHECK(host_sim_gpio_level(RES_GPIO_MOTOR_A_IN1));
}

static encoder_cfg_t ecfg(void)
{
    encoder_cfg_t c = encoder_cfg_default();
    c.enc = RES_ENCODER_MOTOR_A; c.counts_per_rev = 1000.0f; c.dt_s = 0.001f; c.speed_lpf_hz = 0;
    return c;
}

TEST(encoder_invalid_cfg)
{
    fresh();
    encoder_t e; encoder_cfg_t c;
    c = ecfg(); c.counts_per_rev = 0; CHECK(encoder_init(&e, &c) == DZ_EINVAL);
    c = ecfg(); c.dt_s = -1;          CHECK(encoder_init(&e, &c) == DZ_EINVAL);
    c = ecfg(); c.enc = 9;            CHECK(encoder_init(&e, &c) == DZ_ENODEV);
}

TEST(encoder_speed_position_invert)
{
    fresh();
    encoder_t e; encoder_cfg_t c = ecfg();
    CHECK(encoder_init(&e, &c) == DZ_OK);
    host_sim_enc_add(RES_ENCODER_MOTOR_A, 5);
    encoder_update(&e);
    CHECK_NEAR(encoder_speed_rps(&e), 5.0, 1e-4);         /* 5 计数/ms / 1000 = 5 转/秒 */
    CHECK_NEAR(encoder_speed_rpm(&e), 300.0, 1e-2);
    CHECK_NEAR(encoder_position_rev(&e), 0.005, 1e-6);
    c.invert = true;
    encoder_init(&e, &c);
    host_sim_enc_add(RES_ENCODER_MOTOR_A, 5);
    encoder_update(&e);
    CHECK_NEAR(encoder_speed_rps(&e), -5.0, 1e-4);
    host_sim_fail_next(HS_FAIL_ENC, 1);
    CHECK(encoder_update(&e) == DZ_EIO);
}

TEST(encoder_int32_wrap)
{
    fresh();
    encoder_t e; encoder_cfg_t c = ecfg();
    host_sim_enc_add(RES_ENCODER_MOTOR_A, INT32_MAX - 2);
    encoder_init(&e, &c);
    host_sim_enc_add(RES_ENCODER_MOTOR_A, 10);            /* 跨过 INT32_MAX 回绕 */
    encoder_update(&e);
    CHECK(encoder_last_delta(&e) == 10);
    CHECK(encoder_count(&e) == 10);
    for (int i = 0; i < 1000; i++) { host_sim_enc_add(RES_ENCODER_MOTOR_A, 3000000); encoder_update(&e); }
    CHECK(encoder_count(&e) == 10 + 3000000000LL);        /* 64 位累计不溢出 */
    encoder_zero(&e);
    CHECK(encoder_count(&e) == 0);
}

TEST(encoder_lpf_and_selftest)
{
    fresh();
    encoder_t e; encoder_cfg_t c = ecfg(); c.speed_lpf_hz = 20;
    encoder_init(&e, &c);
    host_sim_enc_add(RES_ENCODER_MOTOR_A, 0); encoder_update(&e);
    host_sim_enc_add(RES_ENCODER_MOTOR_A, 5); encoder_update(&e);
    CHECK(encoder_speed_rps(&e) < 5.0f && encoder_speed_rps(&e) > 0.0f);
    encoder_init(&e, &c);
    CHECK(encoder_selftest_still(&e, 20, 2) == DZ_OK);
}

void suite_drivers(void)
{
    RUN(motor_invalid_cfg); RUN(motor_direction_change_order); RUN(motor_deadband_maxduty_invert_nan);
    RUN(motor_brake_coast_and_fault); RUN(motor_dir_mode);
    RUN(encoder_invalid_cfg); RUN(encoder_speed_position_invert); RUN(encoder_int32_wrap); RUN(encoder_lpf_and_selftest);
}
