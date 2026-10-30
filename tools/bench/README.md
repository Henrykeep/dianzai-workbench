# tools/bench — 端到端基准（`make bench`）

`make bench` 在 host-sim 上逐题跑：构建 + 连接 → 默认参数阶跃 →（可选）PID 清零继电起步并采纳 → 阶跃 → 验收评分，
输出 stdout 表和 `build/bench/results.{json,md}`。每题 100 分：连上并出遥测 10、阶跃指标有效 10、验收通过 40、
超调 20（0%→20，≥50%→0）、调节时间 20（≤ t_max/3 满分，≥ t_max 0 分）；总分 = 各题平均。

- 用例：`cases.json`（`runner` 默认 sim_step；`kickoff` 类只做覆盖统计，不计分）；阶跃设定见仓库根 `dzbench.json` 的 step_tests。
- 只跑某题：`make bench ARGS="--only 2026H"`；对比：`ARGS="--baseline old/results.json"`。
- 评分口径单测（不起仿真板，`make check` 里跑）：`python3 tools/bench/test_bench.py`。
- 基线（fw-runtime，2026-10-31，UTC+8）：motor_pos 99.5、2013C 88.2、2023E 71.1、2026H 84.7，平均 **85.9**（新克隆、空 HOME、make fetch 后实测；已构建的工作区可能因缓存差 ±0.1）。
