# stepper — 42 步进 STEP/DIR 梯形加减速

适用 A4988 / DRV8825 / TMC2208/2209（STEP/DIR 模式）/ TB6600。整数 Q32 相位累加器，ISR 里无 float、无除法。

## board.yaml
```yaml
gpio:
  - { name: STEP, pin: PA8, dir: out }
  - { name: STEP_DIR, pin: PA9, dir: out }
  - { name: STEP_EN, pin: PA10, dir: out, active_low: true }   # 驱动板 EN 低有效
timer:
  - { name: STEP_TICK, instance: TIM6, note: 20 kHz }
```

## 用法
```c
stepper_cfg_t c = stepper_cfg_default(RES_GPIO_STEP, RES_GPIO_STEP_DIR, RES_GPIO_STEP_EN);
c.max_sps = 3200; c.acc_sps2 = 6400;         /* 16 细分 → 1 圈/秒 */
stepper_init(&st, &c); stepper_enable(&st, true);
pal_timer_start(RES_TIMER_STEP_TICK, 50, (pal_timer_cb_t)stepper_tick, &st);   /* 20 kHz */
stepper_move_to(&st, 3200);
```
- 步数 = 200 步/圈 × 细分。42 步进常见 1.8°。
- 起跳速度 `start_sps` 太高会丢步/啸叫；负载大就降低加速度。
- 失步不会被检测（开环）：需要回零开关 + `stepper_set_pos(0)`。
- `stepper_halt()` 立即停脉冲（急停用）；高速时惯性会让电机多转/丢步，恢复后要重新回零。
- 20 kHz 中断在 F407/MSPM0 上开销很小，但不要在同一中断里做别的重活。

## 测试状态
- 【已实测】主机单测：在 host-sim 上数 STEP 上升沿 = 目标步数、最高速度不超 max_sps、高速中途反向时**不会**在运动中改 DIR、平滑停止的刹车距离 ≈ v²/2a、急停、使能脚、非法配置。
- 【未验证】上板（驱动板 STEP 最小脉宽、DIR 建立时间按 1 个 tick = 50 us 留够了余量）。
