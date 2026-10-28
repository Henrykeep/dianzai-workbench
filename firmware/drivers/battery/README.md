# battery — 电池电压与低压告警

ADC 原始码 → 整包电压（分压比）→ 一阶滤波 → OK/LOW/CRIT/NONE（滞回 + 保持时间）→ 粗略百分比。

## board.yaml
```yaml
adc:
  - { name: VBAT, instance: ADC1, channel: 9, pin: PB1, scale: [11, 1] }  # 100k/10k 分压
```
`cfg.div_num/div_den` 非 0 时覆盖 board.yaml 的 scale。

## 硬件提醒（控制方向同学常踩）
- 分压后引脚电压必须 < ADC 参考（3.3 V）。2S 满电 8.4 V → 至少 1:3，推荐 100k/10k（1:11），加 100 nF 到地。
- 3S 用 1:11 时 12.6 V → 1.15 V，分辨率仍够。
- 电机启动会把电压瞬间拉低，所以有 `hold_ms`（默认 2 s）。

## 用法
```c
battery_cfg_t c = battery_cfg_default(RES_ADC_VBAT);
c.cells = 2; c.low_mv = 7000; c.crit_mv = 6600;
battery_init(&bat, &c);
battery_update(&bat, pal_millis());          /* 50 ms 任务 */
if (battery_state(&bat) == BAT_LOW) buzzer_play(&bz, &BUZZER_LOWBAT, now);
```
CRIT 时建议应用层降速/停机——但**不要**让自动逻辑去解除急停。

## 测试状态
- 【已实测】主机单测：换算、瞬时压降不报警、LOW/CRIT、滞回、拔电池、非法配置。
- 【未验证】上板。MSPM0 端口的 ADC 目前仍返回 `DZ_ENOTSUP`（见 ports/mspm0-driverlib/README）。
- 百分比为空载近似，负载下偏低，仅作显示。
