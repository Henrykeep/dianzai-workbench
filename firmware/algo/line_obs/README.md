# line_obs — 丢线观测与找线恢复

纯逻辑，接在任何循迹传感器后面（`line_sensor` 的 `LINE_F_LOST/LINE_F_CROSS`、摄像头线位置都行）。

| 状态 | 进入 | 调用方该做 |
|---|---|---|
| TRACK | 正常 / 找回后 | 正常循迹 |
| WIDE | 路口、横线（cross） | 按任务（直行/计数），不算丢线 |
| LOST | 连续 `lost_confirm` 拍没线 | 朝 `line_obs_dir()` 原地/慢速转找线；`line_obs_just_lost()` 那拍记黑匣子 `BB_EV_LINE_LOST` |
| FAIL | LOST 超过 `lost_timeout_ms` | 安全停车，锁存；人确认后 `line_obs_reset()` |

找回要连续 `reacq_frames` 拍看到线（不是一拍就切回，防止找线时扫过一下就猛拐）。

默认参数 3 / 4 / 10 / 12000 ms 来自 DS-land-and-air（2026 电赛 D 题省一车）的实车值，[仿真] 本仓库只做了模型测试
（tests/host/test_ctrlparts.c `line_obs_recover_and_timeout`）。来源见 docs/参考来源.md。

## 用法示例

`apps/line_car/app_main.c`（1.1.0）：`line_obs_update` 每 5 ms 一拍；LOST 时朝 `line_obs_dir` 原地转、方向为 0 时左右扫；`line_obs_just_lost` → 写黑匣子 `BB_EV_LINE_LOST`。
