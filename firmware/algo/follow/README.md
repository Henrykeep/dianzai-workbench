# follow — 跟车间距控制

`v_cmd = v_lead + kp·(gap − gap_ref) − kd·(v_self − v_lead)`，限 0..v_max、加速 accel、减速 decel。

| 情况 | 行为 |
|---|---|
| gap < gap_min | 立即 0（TOO_CLOSE，不受 decel 限） |
| 对方数据不新鲜 / 中止（lead_ok=false） | 按 decel 减到 0（LINK_LOST），恢复后自动继续 |
| 正常 | 上式 |

gap 来源二选一：两车里程差（`peerlink` STATE 的 s_m，收到后按 v 外推到当前时刻），或测距传感器。
整链路模型测试：tests/host/test_ctrlparts.c `follow_two_car_link`（10 Hz 链路、断链 0.5 s、领车停车后中止）。[仿真]
