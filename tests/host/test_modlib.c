/* 模块库（v0.5.0）：servo、buzzer、battery、ssd1306 传输、hcsr04、line_sensor、stepper、st77xx、bt_serial、motor_2pwm。
 * 每个驱动都用 host-sim 的“假芯片”跑：PWM/GPIO/ADC/UART/I2C/SPI 都是 host_sim 提供的。 */
#include <string.h>
#include "tt.h"
#include "board_gen.h"
#include "host_sim.h"
#include "servo.h"
#include "buzzer.h"
#include "battery.h"

static void fresh(void) { host_sim_reset(); pal_init(); }

TEST(servo_pwm)
{
    fresh();
    CHECK(servo_selftest() == DZ_OK);
    servo_t s; servo_cfg_t c = servo_cfg_default(RES_PWM_SERVO_X);
    c.lim_lo_deg = -60.0f; c.lim_hi_deg = 60.0f;
    CHECK(servo_init(&s, &c) == DZ_OK);
    /* 50 Hz → 周期 20000 us，1500 us = 7.5% = 750/10000 */
    CHECK(host_sim_pwm_duty(RES_PWM_SERVO_X) == 750u);
    CHECK(servo_set_deg(&s, 90.0f) == DZ_OK);            /* 被限位到 60° */
    CHECK(s.pulse_us == 2167u);
    CHECK(servo_set_deg(&s, 0.0f / 0.0f) == DZ_EINVAL);
    c.slew_dps = 100.0f; CHECK(servo_init(&s, &c) == DZ_OK);
    CHECK(servo_set_deg(&s, 50.0f) == DZ_OK);
    CHECK(s.pulse_us == 1500u);
    for (int i = 0; i < 10; i++) CHECK(servo_tick(&s, 0.02f) == DZ_OK);
    CHECK_NEAR(s.angle, 20.0f, 1e-3f);
    for (int i = 0; i < 40; i++) (void)servo_tick(&s, 0.02f);
    CHECK_NEAR(s.angle, 50.0f, 1e-3f);
    c.min_us = 2600; CHECK(servo_init(&s, &c) == DZ_EINVAL);
    servo_t z = {0}; CHECK(servo_set_deg(&z, 1.0f) == DZ_ESTATE);
    c = servo_cfg_default(7); CHECK(servo_init(&s, &c) != DZ_OK);
}

TEST(buzzer_patterns)
{
    fresh();
    CHECK(buzzer_selftest() == DZ_OK);
    buzzer_t b;
    CHECK(buzzer_init(&b, PAL_ID_NONE, RES_PWM_BUZZER_PWM) == DZ_OK);
    CHECK(buzzer_play(&b, &BUZZER_LOWBAT, 1000) == DZ_OK);
    CHECK(host_sim_pwm_duty(RES_PWM_BUZZER_PWM) == PAL_DUTY_MAX / 2u);
    CHECK(buzzer_tick(&b, 1100) == DZ_OK);
    CHECK(host_sim_pwm_duty(RES_PWM_BUZZER_PWM) == 0u);
    CHECK(buzzer_tick(&b, 4000) == DZ_OK);                 /* 循环回到“响” */
    CHECK(host_sim_pwm_duty(RES_PWM_BUZZER_PWM) == PAL_DUTY_MAX / 2u);
    CHECK(buzzer_play(&b, &BUZZER_BEEP, 4010) == DZ_EBUSY); /* 低电量优先级更高 */
    CHECK(buzzer_play(&b, &BUZZER_ALARM, 4010) == DZ_OK);
    CHECK(buzzer_stop(&b) == DZ_OK && !buzzer_busy(&b));
    CHECK(host_sim_pwm_duty(RES_PWM_BUZZER_PWM) == 0u);
    /* 长时间不 tick 不会卡死 */
    CHECK(buzzer_play(&b, &BUZZER_ALARM, 0) == DZ_OK);
    CHECK(buzzer_tick(&b, 100000) == DZ_OK);
    /* 有源蜂鸣器：GPIO */
    CHECK(buzzer_init(&b, RES_GPIO_BUZZER, PAL_ID_NONE) == DZ_OK);
    CHECK(buzzer_play(&b, &BUZZER_ERROR, 0) == DZ_OK);
    CHECK(host_sim_gpio_level(RES_GPIO_BUZZER));
    (void)buzzer_tick(&b, 300); CHECK(!host_sim_gpio_level(RES_GPIO_BUZZER));
    (void)buzzer_tick(&b, 2000); CHECK(!buzzer_busy(&b));
    static const uint16_t odd[] = { 10, 10, 10 };
    buzzer_pattern_t bad = { odd, 3, 0, 1 };
    CHECK(buzzer_play(&b, &bad, 0) == DZ_EINVAL);
    bad.repeat = 1; CHECK(buzzer_play(&b, &bad, 0) == DZ_OK);
}

static uint16_t raw_for(float mv_pack, float div) { return (uint16_t)(mv_pack / div / 3300.0f * 4095.0f + 0.5f); }

TEST(battery_lowvolt)
{
    fresh();
    CHECK(battery_selftest() == DZ_OK);
    battery_t b; battery_cfg_t c = battery_cfg_default(RES_ADC_VBAT);
    c.div_num = 11; c.div_den = 1;
    CHECK(battery_init(&b, &c) == DZ_OK);
    host_sim_adc_set(RES_ADC_VBAT, raw_for(8200.0f, 11.0f));
    uint32_t t = 0;
    CHECK(battery_update(&b, t) == DZ_OK);
    CHECK(battery_state(&b) == BAT_OK);
    CHECK_NEAR(battery_mv(&b), 8200.0f, 10.0f);
    int pc = battery_percent(&b); CHECK(pc >= 90 && pc <= 94); /* 4.1 V/节 */
    /* 电机启动瞬间压降 300 ms：不报警 */
    host_sim_adc_set(RES_ADC_VBAT, raw_for(6500.0f, 11.0f));
    for (int i = 0; i < 6; i++) { t += 50; (void)battery_update(&b, t); }
    host_sim_adc_set(RES_ADC_VBAT, raw_for(8200.0f, 11.0f));
    for (int i = 0; i < 60; i++) { t += 50; (void)battery_update(&b, t); }
    CHECK(battery_state(&b) == BAT_OK);
    /* 持续 6.9 V → LOW */
    host_sim_adc_set(RES_ADC_VBAT, raw_for(6900.0f, 11.0f));
    for (int i = 0; i < 80; i++) { t += 50; (void)battery_update(&b, t); }
    CHECK(battery_state(&b) == BAT_LOW);
    /* 回到 7.05 V（在滞回带内）仍是 LOW */
    host_sim_adc_set(RES_ADC_VBAT, raw_for(7050.0f, 11.0f));
    for (int i = 0; i < 80; i++) { t += 50; (void)battery_update(&b, t); }
    CHECK(battery_state(&b) == BAT_LOW);
    host_sim_adc_set(RES_ADC_VBAT, raw_for(6400.0f, 11.0f));
    for (int i = 0; i < 80; i++) { t += 50; (void)battery_update(&b, t); }
    CHECK(battery_state(&b) == BAT_CRIT);
    CHECK(strcmp(battery_state_name(BAT_CRIT), "CRIT") == 0);
    /* 拔掉电池：立即 NONE */
    host_sim_adc_set(RES_ADC_VBAT, 0);
    c.lpf_tau_s = 0.0f; CHECK(battery_init(&b, &c) == DZ_OK);
    CHECK(battery_update(&b, 0) == DZ_OK && battery_state(&b) == BAT_NONE);
    CHECK(battery_percent(&b) == -1);
    c.crit_mv = 8000; CHECK(battery_init(&b, &c) == DZ_EINVAL);
    c = battery_cfg_default(RES_ADC_VBAT); c.div_num = 3; CHECK(battery_init(&b, &c) == DZ_EINVAL);
}

void suite_modlib(void)
{
    RUN(servo_pwm); RUN(buzzer_patterns); RUN(battery_lowvolt);
}
