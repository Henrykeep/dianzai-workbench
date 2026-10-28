# buzzer — 蜂鸣器节奏

开/关毫秒序列 + 重复 + 优先级，非阻塞（`buzzer_tick()` 周期推进）。内置：`BUZZER_BEEP/OK/ERROR/LOWBAT/ALARM`。

## board.yaml（二选一）
```yaml
gpio:   # 有源蜂鸣器（通电就响），一般经三极管驱动
  - { name: BUZZER, pin: PB8, dir: out, active_low: false }
pwm:    # 无源蜂鸣器（需要方波），频率选谐振点 2.7 kHz 左右最响
  - { name: BUZZER_PWM, timer: TIM4, channel: 3, pin: PB8, freq_hz: 2700 }
```

## 用法
```c
buzzer_init(&bz, PAL_ID_NONE, RES_PWM_BUZZER_PWM);
buzzer_play(&bz, &BUZZER_OK, pal_millis());
buzzer_tick(&bz, pal_millis());   /* 10 ms 任务 */
```
- 高优先级（ALARM=9 > LOWBAT=3 > ERROR=2 > BEEP/OK=1）不会被低优先级打断，返回 `DZ_EBUSY`。
- 自定义节奏：要重复的必须偶数步（以“停”结尾）。

## 测试状态
- 【已实测】主机单测：时序、循环、优先级、长时间不 tick、GPIO/PWM 两种输出。
- 【未验证】上板音量与频率。
