# 不对称变化率限制  `v1.0.0`

上升 / 下降（或加速 / 减速）各自一个速率上限。典型用法：小车起步慢、刹车快；云台往外打慢、回中快。

- 接口：`slew_init/slew_update/slew_reset`；模式 `SLEW_BY_DIR`（正向/负向）、`SLEW_BY_MAG`（远离 0 / 靠近 0，跨零先减后加）
- 和 PID 的关系：PID 的 `out_rate_max` 只有对称速率；要不对称就把它设 0，PID 输出再过 slew。不对称**限幅**用 PID 的 `out_min/out_max`（本来就支持，例如 -0.3..1.0）。
- 自检：`slew_selftest()`；tests/host/test_ctrlparts.c

## 验证状态
- **已实测（PC 主机）**：两种模式的速率、跨零先减后加、NaN/dt 非法保持、不限速直通、和一阶电机模型串起来时加速段时长按 rise 算
- **[未测]**：实车起步打滑 / 刹车距离是否真的改善

## 参考来源
- 斜坡发生器是常识做法；按"远离 0 / 靠近 0"区分加减速的思路见 PX4 `lib/slew_rate` 与 ArduPilot 的加减速限制（只借思路，代码自写）。
