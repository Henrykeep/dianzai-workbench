---
triggers: 堵转, stall, 卡住不转, 电机不转, 过流
---
# 堵转（algo/stall）
- 判据：负载（电流或 PWM 占空比）高于阈值 **且** 速度接近零，持续 hold_ms 以上才报；负载刚升高后 start_ignore_ms 内豁免（起步电流大）；NaN 输入保持上一状态、不误报。
- 报出后锁存（count 累计次数）；retry_ms > 0 时锁存这么久后自动重试，= 0 时只能 stall_clear 解除。
- 先排除：编码器没接/方向反（看 polarity_check）、PWM 没输出（逻辑分析仪看引脚）、机械卡死。
- 代码：`firmware/algo/stall/stall.h`；主机测试 `tests/host/test_ctrlparts.c` 的 stall_detect_model（一阶电机模型）。
- 安全对照与缺口（没开 IWDG 等）：`docs/32-控制安全对照.md`。
