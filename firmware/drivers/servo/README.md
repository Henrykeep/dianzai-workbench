# servo — 舵机 PWM

角度→脉宽（min/center/max + trim + invert）、软件限位、速率限制（slew）。只依赖 `pal_pwm_set_pulse_us`。

## board.yaml
```yaml
pwm:
  - { name: SERVO_X, timer: TIM3, channel: 1, pin: PA6, freq_hz: 50 }   # 换板只改 pin/timer
```

## 用法
```c
servo_cfg_t c = servo_cfg_default(RES_PWM_SERVO_X);
c.lim_lo_deg = -40; c.lim_hi_deg = 40;   /* 机构干涉范围，先手动量 */
c.slew_dps = 300;                        /* 防止猛甩；0 = 不限 */
servo_init(&s, &c);
servo_set_deg(&s, 15.0f);  /* 控制环里 */
servo_tick(&s, 0.01f);     /* slew>0 时每周期调用 */
```

## 标定步骤
1. `servo_set_us()` 从 1500 开始，找机构真正的中位 → 差值填 `trim_us`。
2. 慢慢加减找到不顶死的两端 → 换算成 `lim_lo/hi_deg`（顶死会烧舵机）。
3. 方向反了置 `invert`，不要改接线。

## 测试状态
- 【已实测】主机单测：映射、限位、slew、NaN、非法配置、host-sim PWM 占空比（50 Hz 下 1500 us = 7.5%）。
- 【未验证】上板（SG90/MG996R 实际脉宽范围因厂家而异）。
