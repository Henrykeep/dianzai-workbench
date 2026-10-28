# motor_2pwm — DRV8833 / 双 PWM H 桥

IN1、IN2 都是 PWM 的驱动（DRV8833、AT8236、L298N 两路都接 PWM 时）。TB6612（PWM + AIN1/AIN2）请用 `motor_dc`。为什么拆成两个模块见 QUESTIONS 36。

## board.yaml
```yaml
pwm:   # 同一个定时器的两个通道，保证同频
  - { name: MOTOR_C_IN1, timer: TIM8, channel: 1, pin: PC6, freq_hz: 20000 }
  - { name: MOTOR_C_IN2, timer: TIM8, channel: 2, pin: PC7, freq_hz: 20000 }
```

## 用法
```c
motor_2pwm_cfg_t c = motor_2pwm_cfg_default(RES_PWM_MOTOR_C_IN1, RES_PWM_MOTOR_C_IN2);
c.deadband = 0.08f;                 /* 克服静摩擦 */
motor_2pwm_init(&mc, &c);
motor_2pwm_set(&mc, u);             /* 控制环里，u ∈ [-1,1] */
motor_2pwm_stop(&mc, true);         /* 刹车；false = 滑行 */
```
- 慢衰减（默认）：转速–占空接近线性，低速好调；快衰减：松手更“滑”。
- DRV8833 每路 1.5 A RMS，带不动 520/370 大电机时换 TB6612 或更大的桥。
- 电机转向反了改 `invert`。

## 测试状态
- 【已实测】主机单测：慢/快衰减占空、限幅、反向、死区、NaN、刹车/滑行、两路频率不一致被拒、同一 ID 被拒。
- 【未验证】上板。真值表来自 TI DRV8833 数据手册（SLVSAR1）。
