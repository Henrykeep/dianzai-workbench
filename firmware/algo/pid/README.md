# PID 控制器（位置式/增量式/串级）  `v1.0.0`

纯 C、无硬件依赖。含积分限幅、积分分离（|err| 大时不积分）、微分先行（默认，对测量值求导）、微分低通、输出限幅与输出变化率限制、无扰切换 `pid_reset_to()`。

- 接口：`pid_init/pid_update/pid_reset/pid_set_gains`，增量式 `pid_inc_*`
- 自检：`pid_selftest()`；主机单测 tests/host/test_pid.c
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：主机单测 + 一阶电机模型闭环仿真（tests/host/test_sim.c）
- **未验证**：真实电机上的增益/抗饱和效果**未实测**

## 参考来源
- Brett Beauregard《Improving the Beginner's PID》系列（brettbeauregard.com，微分取测量值、抗积分饱和、无扰切换）；RoboMaster 官方开发板 C 型例程中的 PID（github.com/RoboMaster/Development-Board-C-Examples，位置式+增量式结构）
- PX4 Autopilot 姿态/速率控制器（github.com/PX4/PX4-Autopilot，src/lib/pid，BSD-3）：积分钳位与微分取测量值的同类做法，作对照，未拷贝代码。
- 用户 P1 工程的 pid.c（商家教程风格，许可不明）**未使用**；本模块是工作台自写。

## dt 异常（1.1.0）

`pid_check_gap(&pid, 实际间隔秒)` 放在 `pid_update` 前：间隔 > 5×dt 或 > 0.5 s（断点恢复、任务被饿死）时清微分历史和微分滤波，积分保留。
低通同理：`lpf1_check_gap(&f, 实际间隔, 上限)` 让下一个样本直通重起。思路来自 SimpleFOC（MIT），代码自写。car_2wd 控制中断里已接上。

## 继电覆盖（1.2.0）
调参页“无初值一键起步”用。上位机发 dzctl `DATA 0x7C`（u8 loop, f32 amp, f32 hyst, f32 timeout_s），
第 loop 个 `pid_init` 过的位置式 PID 的输出换成 `bias ± amp`（bias = 开始时的输出；滞环 hyst；仍按 out_min/out_max 限幅，amp ≤ 半量程）。
`timeout_s`（≤ 60 s）到了、`pid_relay_stop()`、`pid_reset()`（急停）任一发生都结束，并以 bias 无扰切回 PID。
apps/include/link_app.h 已接好（急停中拒绝，上位机掉线时停止）；自己写收发的应用调用 `dzctl_relay_parse` + `pid_relay_start/stop` 即可。
