# 变周期 M/T 法测速  `v1.0.0`

低线数编码器 + 高频控制环时，`encoder` 的窗口差分（M 法）速度只能在几个台阶之间跳。这里用边沿时间戳：
本周期到达的 m 个边沿 ÷ 两个边沿之间的真实时间。高速时等于 M 法，低速时等于 T 法，误差只有一个时钟（1 µs）。

- 接口：`mtspeed_edge`（边沿中断里，给 PAL 边沿回调的 `t_us`）、`mtspeed_poll`（控制周期）、`mtspeed_rps`
- 接线：只喂同一种边沿（如 A 相上升沿），方向看 B 相电平；`counts_per_rev` = 每转喂进来的边沿数
- 和 `encoder` 的关系：位置/累计计数仍用 `encoder`（硬件计数器）；只有低速测速不够用时再加这一路
- 自检：`mtspeed_selftest()`；tests/host/test_ctrlparts.c

## 验证状态
- **已实测（PC 主机）**：匀速读数；低速 1.9 rps、52 边沿/转、1 kHz 轮询时标准差：M 法 1 ms 窗口 5.74 rps、20 ms 窗口 0.147 rps、M/T 0.0003 rps（仿真边沿是理想等间隔，实物会被边沿抖动拉大）；减速时读数下降、超时归零、停后重起不拿旧边沿算、反转、µs 回绕
- **[未测]**：中断打断 poll 时的版本号双读（主机单线程测不到）、真实编码器、边沿中断抖动/毛刺（需要硬件滤波或 PAL 去抖）、高速时边沿中断占用 CPU（每转 counts_per_rev 次中断）

## 参考来源
- Ohmae 等的 M/T 法及"变周期 M/T"（计数窗口起止对齐到编码器边沿）：Luan 等, DEStech TCSE 2017（dpi-journals.com/index.php/dtcse/article/view/5340）；EMEIT 2012 doi:10.2991/emeit.2012.411。
- STM32 上用编码器定时器 + 输入捕获定时器级联的实现：github.com/ufnalski/incremental_encoder_pulse_timing_l432kc（只借思路；本模块走 PAL 边沿中断，不绑定定时器级联）。
