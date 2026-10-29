# pid_helper —— PID_Helper 阶跃辨识（GPL-3.0）

Source: gitee.com/qianmonai/PID_Helper@17813ca src/shared/pid-identification.ts
（提交时间 2026-05-26 17:46 UTC+8；作者 qianmonai，队友/开源组项目）

- 许可：GPL-3.0（`LICENSE` 原样复制）。所以单独放这里，侧车只经 `app/sidecar/dzbench/tuning/identify.py` 调用。
- 搬了什么：全部导出函数（候选网格、纯 P / 速度环阶段指标与打分、阶跃稳态判定、开环阶跃 FOPDT + 保守 λ 整定）和 float-utils 的 normalize/clamp。
- 改了什么（逐行对照可查）：
  1. TS → Python，camelCase → snake_case；样本对象改 dict（t / actual / input / ts）。
  2. 写死的阈值做成参数，默认值与原版一致：稳态判定的 900 ms 最短观察 → `min_observe_ms`，绝对阈值 0.2/0.12/0.05/0.35 统一乘 `unit`；开环辨识的 0.2 最小变化 → `min_delta`。原版量纲是电机转速，这些绝对值对弧度、米太大，适配层按阶跃幅度换算 unit。
  3. 抛 `Error` 改为抛 `IdentError`（ValueError 子类）。
- 第二个文件 `pid_helper_pso.py`（缺口清单第 2 项）：Source: gitee.com/qianmonai/PID_Helper@17813ca src/shared/pid-pso.ts 全部 + pid-optimizer.ts 的分阶段候选（P/I/D 六档比例、±5% 微调）、三种打分权重、calculateOptimizationScore。
  改动：TS → Python；PID 改 dict；`default_options` 多一个 `pos_bounds`（原版按 seed 推边界，量纲是电机转速，调用方可给自己的范围）；`random` 可注入（测试固定种子）；指标键改 snake_case（settlingTimeMs → settling_ms）。
  侧车只经 `app/sidecar/dzbench/tuning/search.py` 调用，并且 PSO 只许在仿真里跑（agent/experiment.require_swarm）。
- 没搬：pid-optimizer.ts 其余（闭环稳态/跟踪检测、接受判据文字）、界面与串口代码。
