/* 模块库（v0.5.0）：servo、buzzer、battery、ssd1306 传输、hcsr04、line_sensor、stepper、st77xx、bt_serial、motor_2pwm。
 * 每个驱动都用 host-sim 的“假芯片”跑：PWM/GPIO/ADC/UART/I2C/SPI 都是 host_sim 提供的。 */
#include <string.h>
#include "tt.h"
#include "board_gen.h"
#include "host_sim.h"
#include "servo.h"
#include "buzzer.h"
#include "battery.h"
#include "ssd1306.h"
#include "hcsr04.h"
#include "line_sensor.h"
#include "stepper.h"
#include "st77xx.h"
#include "bt_serial.h"
#include "motor_2pwm.h"

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

/* ---- 假 SSD1306：按控制字节 / D/C 电平区分命令与显存 ---- */
typedef struct { unsigned cmds, data, max_chunk; uint8_t addr; bool saw_on; } fake_oled_t;
static dz_err_t fake_oled_i2c(void *ctx, uint8_t addr7, uint8_t reg, uint8_t *buf, uint16_t n, bool write)
{
    fake_oled_t *f = ctx;
    if (!write) return DZ_EIO;
    if (addr7 != 0x3C) return DZ_EIO;                 /* 没应答 */
    f->addr = addr7; if (n > f->max_chunk) f->max_chunk = n;
    if (reg == 0x40) f->data += n;
    else if (reg == 0x00) { f->cmds += n; for (uint16_t i = 0; i < n; i++) if (buf[i] == 0xAF) f->saw_on = true; }
    else return DZ_EIO;
    return DZ_OK;
}
static dz_err_t fake_oled_spi(void *ctx, const uint8_t *tx, uint8_t *rx, uint16_t n)
{
    fake_oled_t *f = ctx; (void)rx;
    if (n > f->max_chunk) f->max_chunk = n;
    if (host_sim_gpio_level(RES_GPIO_OLED_DC)) f->data += n;
    else { f->cmds += n; for (uint16_t i = 0; i < n; i++) if (tx[i] == 0xAF) f->saw_on = true; }
    return DZ_OK;
}

TEST(ssd1306_pal_transports)
{
    fresh();
    static ssd1306_t d;
    fake_oled_t f = {0};
    host_sim_i2c_attach(RES_I2C_OLED, fake_oled_i2c, &f);
    ssd1306_i2c_t ti = { RES_I2C_OLED, 0x3C };
    CHECK(ssd1306_init(&d, ssd1306_tr_i2c, &ti, 64, false) == DZ_OK);
    CHECK(f.saw_on && f.cmds > 20);
    ssd1306_text(&d, 0, 0, "HI");
    f.data = 0; CHECK(ssd1306_flush(&d) == DZ_OK);
    CHECK(f.data == 1024u && f.max_chunk <= 16u);
    ssd1306_i2c_t bad = { RES_I2C_OLED, 0x3D };
    CHECK(ssd1306_init(&d, ssd1306_tr_i2c, &bad, 64, false) != DZ_OK);
    CHECK(ssd1306_tr_i2c(&ti, true, 0, 4) == DZ_EINVAL);

    fake_oled_t g = {0};
    host_sim_spi_attach(RES_SPI_OLED_SPI, fake_oled_spi, &g);
    ssd1306_spi_t ts = { RES_SPI_OLED_SPI, RES_GPIO_OLED_DC, PAL_ID_NONE };
    CHECK(ssd1306_spi_reset(&ts) == DZ_OK);
    CHECK(ssd1306_init(&d, ssd1306_tr_spi, &ts, 32, true) == DZ_OK);
    CHECK(g.saw_on);
    g.data = 0; CHECK(ssd1306_flush(&d) == DZ_OK);
    CHECK(g.data == 512u && g.max_chunk <= 64u);
}

/* ---- 假 HC-SR04：TRIG 后 450 us 升起 ECHO，脉宽 = 2·d/c ---- */
TEST(hcsr04_fake)
{
    fresh();
    CHECK(hcsr04_selftest() == DZ_OK);
    hcsr04_t h; hcsr04_cfg_t c = hcsr04_cfg_default(RES_GPIO_US_TRIG, RES_GPIO_US_ECHO);
    CHECK(hcsr04_init(&h, &c) == DZ_OK);
    CHECK(hcsr04_set_temp(&h, 30.0f) == DZ_OK);
    float cmm = (331.3f + 0.606f * 30.0f) * 0.001f;
    uint32_t width = (uint32_t)(2.0f * 500.0f / cmm);    /* 500 mm */
    uint32_t t_us = 1000, t_ms = 1; bool fresh_res = false;
    host_sim_gpio_set_input(RES_GPIO_US_ECHO, false);
    /* 100 us 轮询 */
    for (int k = 0; k < 400 && !fresh_res; k++) {
        uint32_t since = t_us - h.t_trig;
        bool started = h.phase == HCSR04_WAIT_RISE || h.phase == HCSR04_WAIT_FALL;
        host_sim_gpio_set_input(RES_GPIO_US_ECHO, started && since >= 450u && since < 450u + width);
        fresh_res = hcsr04_update(&h, t_ms, t_us, true);
        t_us += 100; t_ms = t_us / 1000u;
    }
    CHECK(fresh_res && hcsr04_valid(&h));
    CHECK_NEAR(hcsr04_mm(&h), 500.0f, 20.0f);           /* 轮询量化 100 us ≈ 17 mm */
    /* 中断模式：精确边沿 */
    hcsr04_t hi; CHECK(hcsr04_init(&hi, &c) == DZ_OK);
    CHECK(hcsr04_trigger(&hi, 10000) == DZ_OK);
    CHECK(hcsr04_trigger(&hi, 10001) == DZ_EBUSY);
    hcsr04_echo_edge(&hi, true, 10450); hcsr04_echo_edge(&hi, false, 10450 + 1748);
    CHECK(hcsr04_update(&hi, 20, 12300, false));
    CHECK_NEAR(hcsr04_mm(&hi), 300.0f, 1.0f);
    /* 无回波 → 超时，结果无效 */
    CHECK(hcsr04_init(&hi, &c) == DZ_OK);
    host_sim_gpio_set_input(RES_GPIO_US_ECHO, false);
    CHECK(hcsr04_trigger(&hi, 100000) == DZ_OK);
    CHECK(hcsr04_poll(&hi, 120000, true) == DZ_OK && hi.phase == HCSR04_WAIT_RISE);
    CHECK(hcsr04_poll(&hi, 126000, true) == DZ_OK && hi.phase == HCSR04_TIMEOUT);
    CHECK(hcsr04_update(&hi, 126, 126000, true) && !hcsr04_valid(&hi));
    /* 量程外（太近） */
    CHECK(hcsr04_init(&hi, &c) == DZ_OK);
    CHECK(hcsr04_trigger(&hi, 0) == DZ_OK);
    hcsr04_echo_edge(&hi, true, 400); hcsr04_echo_edge(&hi, false, 450);
    CHECK(hcsr04_update(&hi, 1, 500, false) && !hcsr04_valid(&hi));
    c.period_ms = 20; CHECK(hcsr04_init(&hi, &c) == DZ_EINVAL);
    CHECK(hcsr04_set_temp(&hi, 99.0f) == DZ_EINVAL);
}

/* ---- PAL 1.2.0 边沿中断：host-sim 的 host_sim_gpio_set_input 同步触发回调 ---- */
static int s_irq_n; static bool s_irq_lv; static uint32_t s_irq_t;
static void irq_spy(void *ctx, bool lv, uint32_t t) { (void)ctx; s_irq_n++; s_irq_lv = lv; s_irq_t = t; }
TEST(gpio_irq_and_hcsr04_irq)
{
    fresh();
    host_sim_gpio_set_input(RES_GPIO_US_ECHO, false);
    CHECK(pal_gpio_irq_attach(RES_GPIO_US_ECHO, PAL_EDGE_RISING, irq_spy, 0) == DZ_OK);
    CHECK(pal_gpio_irq_attach(RES_GPIO_US_ECHO, (pal_edge_t)0, irq_spy, 0) == DZ_EINVAL);
    CHECK(pal_gpio_irq_attach(RES_GPIO_US_ECHO, PAL_EDGE_BOTH, 0, 0) == DZ_EINVAL);
    CHECK(pal_gpio_irq_attach(BOARD_GPIO_COUNT, PAL_EDGE_BOTH, irq_spy, 0) == DZ_ENODEV);
    s_irq_n = 0;
    host_sim_gpio_set_input(RES_GPIO_US_ECHO, true);
    CHECK(s_irq_n == 1 && s_irq_lv && s_irq_t == pal_micros());
    host_sim_gpio_set_input(RES_GPIO_US_ECHO, true);  CHECK(s_irq_n == 1);   /* 电平没变不触发 */
    host_sim_gpio_set_input(RES_GPIO_US_ECHO, false); CHECK(s_irq_n == 1);   /* 只挂了上升沿 */
    CHECK(pal_gpio_irq_detach(RES_GPIO_US_ECHO) == DZ_OK);
    host_sim_gpio_set_input(RES_GPIO_US_ECHO, true);  CHECK(s_irq_n == 1);
    host_sim_gpio_set_input(RES_GPIO_US_ECHO, false);
    /* hcsr04 中断模式：回波 1800 us，中断时间戳 = 仿真时间，脉宽精确 */
    hcsr04_t h; hcsr04_cfg_t c = hcsr04_cfg_default(RES_GPIO_US_TRIG, RES_GPIO_US_ECHO);
    CHECK(hcsr04_init(&h, &c) == DZ_OK);
    CHECK(hcsr04_attach_irq(&h) == DZ_OK && h.irq);
    CHECK(!hcsr04_update(&h, pal_millis(), pal_micros(), true) && h.phase == HCSR04_WAIT_RISE);
    pal_delay_us(450); host_sim_gpio_set_input(RES_GPIO_US_ECHO, true);
    CHECK(h.phase == HCSR04_WAIT_FALL);
    pal_delay_us(1800); host_sim_gpio_set_input(RES_GPIO_US_ECHO, false);
    CHECK(h.phase == HCSR04_DONE);
    CHECK(hcsr04_update(&h, pal_millis(), pal_micros(), true) && hcsr04_valid(&h));
    CHECK_NEAR(hcsr04_mm(&h), hcsr04_width_to_mm(&h, 1800u), 0.01f);   /* 1800 us = 仿真步长整数倍 */
    CHECK(hcsr04_detach_irq(&h) == DZ_OK && !h.irq);
    host_sim_gpio_set_input(RES_GPIO_US_ECHO, true); host_sim_gpio_set_input(RES_GPIO_US_ECHO, false);
}

/* ---- 灰度：4 路模拟（假传感器 = 线在 x 处的高斯反射）+ 8 路数字 ---- */
#include <math.h>
static void line_scene(float line_x_mm, float pitch)
{
    const pal_id_t ch[4] = { RES_ADC_LINE_A0, RES_ADC_LINE_A1, RES_ADC_LINE_A2, RES_ADC_LINE_A3 };
    for (int i = 0; i < 4; i++) {
        float x = ((float)i - 1.5f) * pitch, d = (x - line_x_mm) / 10.0f;
        host_sim_adc_set(ch[i], (uint16_t)(600.0f + 2800.0f * expf(-d * d)));
    }
}

TEST(line_sensor_fake)
{
    fresh();
    CHECK(line_sensor_selftest() == DZ_OK);
    line_sensor_t l; line_cfg_t c = line_cfg_default();
    c.n = 4; c.analog = true; c.pitch_mm = 15.0f; c.cross_n = 4; c.on_thr = 0.4f;
    c.ids[0] = RES_ADC_LINE_A0; c.ids[1] = RES_ADC_LINE_A1; c.ids[2] = RES_ADC_LINE_A2; c.ids[3] = RES_ADC_LINE_A3;
    CHECK(line_init(&l, &c) == DZ_OK);
    line_result_t r;
    CHECK(line_read(&l, &r) == DZ_ESTATE);               /* 未标定 */
    CHECK(line_calib_begin(&l) == DZ_OK);
    for (float x = -40.0f; x <= 40.0f; x += 2.0f) { line_scene(x, 15.0f); CHECK(line_calib_feed(&l) == DZ_OK); }
    line_scene(200.0f, 15.0f); CHECK(line_calib_feed(&l) == DZ_OK);   /* 全白 */
    CHECK(line_calib_end(&l) == DZ_OK);
    line_scene(0.0f, 15.0f);  CHECK(line_read(&l, &r) == DZ_OK); CHECK_NEAR(r.pos_mm, 0.0f, 1.0f);
    line_scene(8.0f, 15.0f);  CHECK(line_read(&l, &r) == DZ_OK); CHECK(r.pos_mm > 4.0f && r.pos_mm < 12.0f);
    line_scene(-15.0f, 15.0f); CHECK(line_read(&l, &r) == DZ_OK); CHECK(r.pos_mm < -8.0f && !(r.flags & LINE_F_LOST));
    line_scene(-200.0f, 15.0f); CHECK(line_read(&l, &r) == DZ_OK);
    CHECK((r.flags & LINE_F_LOST) && r.pos_mm == -22.5f);                    /* 记住在左边丢的 */
    /* 动态范围不够的标定被拒 */
    CHECK(line_calib_begin(&l) == DZ_OK); line_scene(0.0f, 15.0f);
    CHECK(line_calib_feed(&l) == DZ_OK); CHECK(line_calib_end(&l) == DZ_EFAIL);

    line_cfg_t d = line_cfg_default(); d.n = 8; d.cross_n = 6; d.pitch_mm = 12.0f;
    for (int i = 0; i < 8; i++) d.ids[i] = (pal_id_t)(RES_GPIO_LINE0 + i);
    CHECK(line_init(&l, &d) == DZ_OK);
    for (int i = 0; i < 8; i++) host_sim_gpio_set_input((pal_id_t)(RES_GPIO_LINE0 + i), i == 5 || i == 6);
    CHECK(line_read(&l, &r) == DZ_OK); CHECK(r.mask == 0x60u); CHECK_NEAR(r.pos_mm, 24.0f, 1e-3f);
    for (int i = 0; i < 8; i++) host_sim_gpio_set_input((pal_id_t)(RES_GPIO_LINE0 + i), i != 0);
    CHECK(line_read(&l, &r) == DZ_OK); CHECK((r.flags & LINE_F_CROSS) && r.pos_mm == 0.0f);
    d.n = 9; CHECK(line_init(&l, &d) == DZ_EINVAL);
}

/* ---- 步进：在 host-sim 上数 STEP 上升沿、监视换向时刻的速度 ---- */
typedef struct { long edges; bool last; int dir_changes_moving; bool last_dir; uint32_t max_sps; } stp_mon_t;
static void stp_run(stepper_t *s, stp_mon_t *m, unsigned ticks)
{
    for (unsigned k = 0; k < ticks; k++) {
        stepper_tick(s);
        bool lv = host_sim_gpio_level(RES_GPIO_STEP), dv = host_sim_gpio_level(RES_GPIO_STEP_DIR);
        if (lv && !m->last) m->edges++;
        if (dv != m->last_dir && s->inc != 0u) m->dir_changes_moving++;
        m->last = lv; m->last_dir = dv;
        uint32_t v = stepper_speed_sps(s); if (v > m->max_sps) m->max_sps = v;
    }
}

TEST(stepper_ramp)
{
    fresh();
    CHECK(stepper_selftest() == DZ_OK);
    stepper_t s; stepper_cfg_t c = stepper_cfg_default(RES_GPIO_STEP, RES_GPIO_STEP_DIR, RES_GPIO_STEP_EN);
    CHECK(stepper_init(&s, &c) == DZ_OK);
    CHECK(stepper_move_to(&s, 100) == DZ_ESTATE);        /* 未使能 */
    CHECK(stepper_enable(&s, true) == DZ_OK);
    CHECK(host_sim_gpio_level(RES_GPIO_STEP_EN));        /* 逻辑有效（物理低） */
    stp_mon_t m = {0}; m.last_dir = host_sim_gpio_level(RES_GPIO_STEP_DIR);
    CHECK(stepper_move_to(&s, 3200) == DZ_OK);            /* 16 细分一圈 */
    /* 梯形：加速 0.5 s 走 1000 步，匀速 1200 步 0.3 s，减速 0.5 s，共约 1.3 s = 26000 tick */
    stp_run(&s, &m, 22000); CHECK(stepper_busy(&s));
    stp_run(&s, &m, 8000);
    CHECK(!stepper_busy(&s)); CHECK(stepper_pos(&s) == 3200); CHECK(m.edges == 3200);
    CHECK(m.max_sps <= 4000u && m.max_sps >= 3900u);
    /* 高速中途反向：必须先减速到 0 才改 DIR */
    m.edges = 0; m.max_sps = 0;
    CHECK(stepper_move_to(&s, 10000) == DZ_OK); stp_run(&s, &m, 12000);
    CHECK(stepper_speed_sps(&s) >= 3900u);
    CHECK(stepper_move_to(&s, 0) == DZ_OK); stp_run(&s, &m, 60000);
    CHECK(m.dir_changes_moving == 0);
    CHECK(stepper_pos(&s) == 0 && !stepper_busy(&s));
    /* 平滑停止 */
    CHECK(stepper_move_to(&s, 50000) == DZ_OK); stp_run(&s, &m, 20000);
    int32_t p0 = stepper_pos(&s);
    CHECK(stepper_stop(&s) == DZ_OK); stp_run(&s, &m, 30000);
    CHECK(!stepper_busy(&s)); CHECK(stepper_pos(&s) - p0 >= 990 && stepper_pos(&s) - p0 <= 1010);
    /* 急停 */
    CHECK(stepper_move_to(&s, -50000) == DZ_OK); stp_run(&s, &m, 5000);
    CHECK(stepper_halt(&s) == DZ_OK); int32_t p1 = stepper_pos(&s); stp_run(&s, &m, 100);
    CHECK(stepper_pos(&s) == p1 && !stepper_busy(&s));
    CHECK(stepper_set_pos(&s, 0) == DZ_OK && stepper_pos(&s) == 0);
    CHECK(stepper_enable(&s, false) == DZ_OK && !host_sim_gpio_level(RES_GPIO_STEP_EN));
    c.max_sps = 15000; CHECK(stepper_init(&s, &c) == DZ_EINVAL);   /* > tick/2 */
    c = stepper_cfg_default(RES_GPIO_STEP, RES_GPIO_STEP_DIR, PAL_ID_NONE); c.start_sps = 0;
    CHECK(stepper_init(&s, &c) == DZ_EINVAL);
}

/* ---- 假 ST77xx：按 D/C 电平解码命令，模拟 CASET/RASET/RAMWR 写 GRAM ---- */
typedef struct {
    uint8_t cmd, madctl, colmod; unsigned np; uint8_t p[4];
    uint16_t x0, x1, y0, y1, cx, cy; bool hi_pending; uint8_t hi;
    bool dispon, invon, slpout; unsigned swreset, ramwr_px;
    uint16_t gram[320][240];
} fake_tft_t;
static fake_tft_t g_tft;
static dz_err_t fake_tft_spi(void *ctx, const uint8_t *tx, uint8_t *rx, uint16_t n)
{
    fake_tft_t *f = ctx; (void)rx;
    bool data = host_sim_gpio_level(RES_GPIO_TFT_DC);
    for (uint16_t i = 0; i < n; i++) {
        uint8_t v = tx[i];
        if (!data) {
            f->cmd = v; f->np = 0; f->hi_pending = false;
            if (v == ST77XX_SWRESET) f->swreset++;
            if (v == ST77XX_SLPOUT) f->slpout = true;
            if (v == ST77XX_DISPON) f->dispon = true;
            if (v == ST77XX_INVON) f->invon = true;
            if (v == ST77XX_RAMWR) { f->cx = f->x0; f->cy = f->y0; }
            continue;
        }
        switch (f->cmd) {
        case ST77XX_MADCTL: f->madctl = v; break;
        case ST77XX_COLMOD: f->colmod = v; break;
        case ST77XX_CASET: case ST77XX_RASET:
            if (f->np < 4) f->p[f->np++] = v;
            if (f->np == 4) {
                uint16_t a = (uint16_t)(f->p[0] << 8 | f->p[1]), b = (uint16_t)(f->p[2] << 8 | f->p[3]);
                if (f->cmd == ST77XX_CASET) { f->x0 = a; f->x1 = b; } else { f->y0 = a; f->y1 = b; }
            }
            break;
        case ST77XX_RAMWR:
            if (!f->hi_pending) { f->hi = v; f->hi_pending = true; break; }
            f->hi_pending = false;
            if (f->cy < 320 && f->cx < 240) f->gram[f->cy][f->cx] = (uint16_t)(f->hi << 8 | v);
            f->ramwr_px++;
            if (++f->cx > f->x1) { f->cx = f->x0; f->cy++; }
            break;
        default: break;
        }
    }
    return DZ_OK;
}

TEST(st77xx_fake)
{
    fresh();
    CHECK(st77xx_selftest() == DZ_OK);
    memset(&g_tft, 0, sizeof g_tft);
    host_sim_spi_attach(RES_SPI_TFT, fake_tft_spi, &g_tft);
    st77xx_t d; st77xx_cfg_t c = st77xx_cfg_st7735_128x160(RES_SPI_TFT, RES_GPIO_TFT_DC, RES_GPIO_TFT_RST, PAL_ID_NONE);
    CHECK(st77xx_init(&d, &c) == DZ_OK);
    CHECK(g_tft.swreset == 1 && g_tft.slpout && g_tft.dispon && !g_tft.invon);
    CHECK(g_tft.colmod == 0x05 && g_tft.madctl == 0x00);
    CHECK(st77xx_width(&d) == 128 && st77xx_height(&d) == 160);
    CHECK(st77xx_fill(&d, ST77XX_BLUE) == DZ_OK);
    CHECK(g_tft.ramwr_px == 128u * 160u);
    CHECK(g_tft.gram[1][2] == ST77XX_BLUE && g_tft.gram[160][129] == ST77XX_BLUE);   /* 偏移 2/1 */
    CHECK(g_tft.gram[0][0] == 0);
    CHECK(st77xx_fill_rect(&d, -5, -5, 10, 10, ST77XX_RED) == DZ_OK);            /* 裁剪 */
    CHECK(g_tft.gram[1 + 4][2 + 4] == ST77XX_RED && g_tft.gram[1 + 5][2 + 5] == ST77XX_BLUE);
    CHECK(st77xx_pixel(&d, 127, 159, ST77XX_GREEN) == DZ_OK && g_tft.gram[160][129] == ST77XX_GREEN);
    CHECK(st77xx_pixel(&d, 128, 0, ST77XX_GREEN) == DZ_OK);                       /* 越界不写 */
    CHECK(st77xx_text(&d, 16, 16, "A", ssd1306_font8x8, ST77XX_WHITE, ST77XX_BLACK, 2) == 1);
    /* 'A' 的某列应有亮点，16×16 区域内既有白也有黑 */
    unsigned white = 0, black = 0;
    for (int y = 0; y < 16; y++) for (int x = 0; x < 16; x++) {
        uint16_t v = g_tft.gram[1 + 16 + y][2 + 16 + x];
        white += v == ST77XX_WHITE; black += v == ST77XX_BLACK;
    }
    CHECK(white > 20 && black > 20 && white + black == 256);
    CHECK(st77xx_text(&d, 121, 0, "XY", ssd1306_font8x8, 1, 0, 1) == 0);       /* 整字越界被裁 */
    CHECK(st77xx_text(&d, 0, 0, "X", 0, 1, 0, 1) < 0);
    CHECK(st77xx_set_rotation(&d, 1) == DZ_OK);
    CHECK(g_tft.madctl == 0x60 && st77xx_width(&d) == 160 && st77xx_height(&d) == 128);
    CHECK(st77xx_backlight(&d, true) == DZ_ENOTSUP);
    c = st77xx_cfg_st7789_240x240(RES_SPI_TFT, RES_GPIO_TFT_DC, PAL_ID_NONE, PAL_ID_NONE);
    c.bgr = true; c.rotation = 2;
    CHECK(st77xx_init(&d, &c) == DZ_OK && g_tft.invon && g_tft.madctl == 0xC8);
    c.width = 400; CHECK(st77xx_init(&d, &c) == DZ_EINVAL);
}

/* ---- 假 HC-05：从 UART TX 取命令，按 AT 规则回 OK/ERROR ---- */
static void fake_bt_step(bool fail_uart)
{
    uint8_t buf[128]; uint16_t n = host_sim_uart_take_tx(RES_UART_BT, buf, sizeof buf - 1);
    if (!n) return;
    buf[n] = 0;
    const char *ok = "OK\r\n", *err = "ERROR:(1D)\r\n";
    const char *r = (fail_uart && strncmp((char *)buf, "AT+UART", 7) == 0) ? err : ok;
    if (strncmp((char *)buf, "AT", 2) != 0) return;   /* 透传数据不应答 */
    host_sim_uart_inject_rx(RES_UART_BT, (const uint8_t *)r, (uint16_t)strlen(r));
}

TEST(bt_serial_fake)
{
    fresh();
    CHECK(bt_serial_selftest() == DZ_OK);
    bt_t b; bt_cfg_t c = { RES_UART_BT, RES_GPIO_BT_STATE, RES_GPIO_BT_EN, BT_HC05, 1000 };
    CHECK(bt_init(&b, &c) == DZ_OK);
    char line[80];
    /* 透传：一次注入两行 + 半行 */
    const char *in = "KP 1.5\r\nGO\nHAL";
    host_sim_uart_inject_rx(RES_UART_BT, (const uint8_t *)in, (uint16_t)strlen(in));
    CHECK(bt_poll(&b, 0, line, sizeof line) && strcmp(line, "KP 1.5") == 0);
    CHECK(bt_poll(&b, 0, line, sizeof line) && strcmp(line, "GO") == 0);
    CHECK(!bt_poll(&b, 0, line, sizeof line));
    host_sim_uart_inject_rx(RES_UART_BT, (const uint8_t *)"F\n", 2);
    CHECK(bt_poll(&b, 0, line, sizeof line) && strcmp(line, "HALF") == 0);
    /* 超长行丢弃 */
    char big[100]; memset(big, 'x', 90); big[90] = '\n';
    host_sim_uart_inject_rx(RES_UART_BT, (const uint8_t *)big, 91);
    CHECK(!bt_poll(&b, 0, line, sizeof line) && b.dropped == 1);
    CHECK(bt_send_line(&b, "hello") == DZ_OK);
    uint8_t tx[16]; uint16_t n = host_sim_uart_take_tx(RES_UART_BT, tx, sizeof tx);
    CHECK(n == 7 && memcmp(tx, "hello\r\n", 7) == 0);
    /* AT 配置成功 */
    CHECK(bt_set_en(&b, true) == DZ_OK && host_sim_gpio_level(RES_GPIO_BT_EN));
    CHECK(bt_config_start(&b, "DZ-CAR", 115200, 0) == DZ_OK);
    for (uint32_t t = 0; t < 100 && bt_at_state(&b) == BT_AT_BUSY; t += 10) { fake_bt_step(false); (void)bt_poll(&b, t, line, sizeof line); }
    CHECK(bt_at_state(&b) == BT_AT_DONE);
    CHECK(strcmp(b.cmds[1], "AT+NAME=DZ-CAR") == 0 && strcmp(b.cmds[2], "AT+UART=115200,0,0") == 0);
    /* 第 3 条报错 */
    CHECK(bt_config_start(&b, "DZ-CAR", 115200, 0) == DZ_OK);
    for (uint32_t t = 0; t < 100 && bt_at_state(&b) == BT_AT_BUSY; t += 10) { fake_bt_step(true); (void)bt_poll(&b, t, line, sizeof line); }
    CHECK(bt_at_state(&b) == BT_AT_FAIL && strncmp(bt_at_current(&b), "AT+UART", 7) == 0);
    /* 模块没回应 → 超时 */
    CHECK(bt_config_start(&b, 0, 0, 5000) == DZ_OK);
    (void)host_sim_uart_take_tx(RES_UART_BT, tx, sizeof tx);
    (void)bt_poll(&b, 5900, line, sizeof line); CHECK(bt_at_state(&b) == BT_AT_BUSY);
    (void)bt_poll(&b, 6100, line, sizeof line); CHECK(bt_at_state(&b) == BT_AT_FAIL);
    /* JDY-31 命令格式 */
    c.module = BT_JDY31; c.state = PAL_ID_NONE; c.en = PAL_ID_NONE;
    CHECK(bt_init(&b, &c) == DZ_OK);
    CHECK(bt_config_start(&b, "JDY", 9600, 0) == DZ_OK);
    CHECK(strcmp(b.cmds[1], "AT+NAMEJDY") == 0 && strcmp(b.cmds[2], "AT+BAUD4") == 0);
    bool known = true; CHECK(!bt_connected(&b, &known) && !known);
    CHECK(bt_config_start(&b, "bad name", 0, 0) == DZ_EBUSY);
    CHECK(bt_init(&b, &c) == DZ_OK);
    CHECK(bt_config_start(&b, "bad name", 0, 0) == DZ_EINVAL);
    CHECK(bt_config_start(&b, 0, 12345, 0) == DZ_EINVAL);
    CHECK(bt_set_en(&b, true) == DZ_ENOTSUP);
    c.module = BT_HC05; c.state = RES_GPIO_BT_STATE; CHECK(bt_init(&b, &c) == DZ_OK);
    host_sim_gpio_set_input(RES_GPIO_BT_STATE, true);
    CHECK(bt_connected(&b, &known) && known);
}

TEST(motor_2pwm_drv8833)
{
    fresh();
    CHECK(motor_2pwm_selftest() == DZ_OK);
    motor_2pwm_t m; motor_2pwm_cfg_t c = motor_2pwm_cfg_default(RES_PWM_MOTOR_C_IN1, RES_PWM_MOTOR_C_IN2);
    CHECK(motor_2pwm_init(&m, &c) == DZ_OK);
    CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_C_IN1) == 0 && host_sim_pwm_duty(RES_PWM_MOTOR_C_IN2) == 0);
    CHECK(motor_2pwm_set(&m, 0.25f) == DZ_OK);       /* 慢衰减：IN1=1，IN2=1−d */
    CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_C_IN1) == PAL_DUTY_MAX && host_sim_pwm_duty(RES_PWM_MOTOR_C_IN2) == 7500);
    CHECK(motor_2pwm_set(&m, -2.0f) == DZ_OK);       /* 限幅到 −1 */
    CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_C_IN1) == 0 && host_sim_pwm_duty(RES_PWM_MOTOR_C_IN2) == PAL_DUTY_MAX);
    CHECK(motor_2pwm_stop(&m, true) == DZ_OK);
    CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_C_IN1) == PAL_DUTY_MAX && host_sim_pwm_duty(RES_PWM_MOTOR_C_IN2) == PAL_DUTY_MAX);
    c.decay = MOTOR_2PWM_FAST_DECAY; c.invert = true; c.deadband = 0.1f; c.max_duty = 0.9f;
    CHECK(motor_2pwm_init(&m, &c) == DZ_OK);
    CHECK(motor_2pwm_set(&m, 0.5f) == DZ_OK);        /* 反向 + 死区：0.1+0.5·0.8=0.5 → IN2 */
    CHECK(host_sim_pwm_duty(RES_PWM_MOTOR_C_IN1) == 0 && host_sim_pwm_duty(RES_PWM_MOTOR_C_IN2) == 5000);
    CHECK(motor_2pwm_set(&m, 0.0f / 0.0f) == DZ_OK && host_sim_pwm_duty(RES_PWM_MOTOR_C_IN2) == 0);
    c = motor_2pwm_cfg_default(RES_PWM_MOTOR_C_IN1, RES_PWM_SERVO_X);     /* 20 kHz vs 50 Hz */
    CHECK(motor_2pwm_init(&m, &c) == DZ_EINVAL);
    c = motor_2pwm_cfg_default(RES_PWM_MOTOR_C_IN1, RES_PWM_MOTOR_C_IN1); CHECK(motor_2pwm_init(&m, &c) == DZ_EINVAL);
    motor_2pwm_t z = {0}; CHECK(motor_2pwm_set(&z, 0.1f) == DZ_ESTATE);
}

void suite_modlib(void)
{
    RUN(servo_pwm); RUN(buzzer_patterns); RUN(battery_lowvolt);
    RUN(ssd1306_pal_transports); RUN(hcsr04_fake); RUN(gpio_irq_and_hcsr04_irq); RUN(line_sensor_fake); RUN(stepper_ramp);
    RUN(st77xx_fake); RUN(bt_serial_fake); RUN(motor_2pwm_drv8833);
}
