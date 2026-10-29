# B2 跟车间距 —— host-sim 仿真
- 谁测：Grok Bot（自动回归）；场地：host-sim；电源：无（仿真）
- 方法：后车跑 examples/2026X_follow 真固件，前车是 sim_setup.c 的虚拟车（0.3 m/s，发真实 peerlink STATE 帧）
- 现象：稳态 gap_m 收敛到 0.40 m，1 s 窗口内全部在 ±5 cm 内
- 结论：partial —— 只说明控制律和链路处理逻辑对；真车的里程标定误差、无线延迟抖动没计入
