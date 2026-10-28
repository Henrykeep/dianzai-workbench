# line_sensor — 灰度/红外循迹阵列

1..8 路，数字（比较器输出 GPIO）或模拟（ADC）；输出线位置 mm（左负右正）、强度、掩码、丢线/路口标志。

## board.yaml
```yaml
gpio:   # 数字：板子上有比较器 + 电位器的那种
  - { name: LINE0, pin: PB0, dir: in, active_low: true }   # 看到黑线时 DO 低 → active_low
  # ... LINE1..LINE7
adc:    # 模拟：灰度传感器 AO
  - { name: LINE_A0, instance: ADC1, channel: 4, pin: PA4 }
  # ... LINE_A1..A3
```

## 用法
```c
line_cfg_t c = line_cfg_default();
c.n = 4; c.analog = true; c.pitch_mm = 15; c.cross_n = 4;
c.ids[0] = RES_ADC_LINE_A0; /* ... */
line_init(&ls, &c);
line_calib_begin(&ls);  /* 推着车在线上左右扫 2 s，每 5 ms 调一次 */ line_calib_feed(&ls); line_calib_end(&ls);
line_read(&ls, &r);     /* 控制周期里：r.pos_mm 作为转向 PID 的误差 */
if (r.flags & LINE_F_LOST) { /* 往 r.pos_mm 的符号那边原地转找线 */ }
```

## 调试建议（控制向）
- 探头离地 5–10 mm；先看各路原始值在白/黑的差，差 < 50 码 `line_calib_end` 会拒绝。
- 位置是连续量，比“哪一路亮”更适合 PD；数字传感器位置是离散的，D 项要小。
- 路口计数、直角弯处理放应用状态机，不放驱动。

## 测试状态
- 【已实测】主机单测：假场景（线在 x 处的高斯反射）下标定 + 插值位置、丢线记边、标定动态范围不足被拒、8 路数字位置/路口、非法配置。
- 【未验证】上板。
