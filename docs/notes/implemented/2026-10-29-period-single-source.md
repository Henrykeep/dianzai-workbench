# 控制周期只有一个来源

- **决定**：题目工程的子系统周期只写在 `project.yaml` 的 `period_ms`，生成 `PERIOD_MS_*`，调度与 dt 都用它；apps/ 单文件应用的周期宏必须同时交给 `pal_timer_start` / `.period_ms`。
- **为什么**：用户 p1 工程 `User/encoder.h:11` 写 `CONTROL_FREQUENCY 300`，实际 100 Hz 调用，速度错 3 倍，编译和仿真都看不出来（user-projects/review.md:131）。
- **守护**：`tools/check_deps.py` 规则 F1，夹具 `tools/fixtures/deps_F1_hand_freq`。
- **已知漏网**：数字字面量的 dt（如 `examples/2026H_ball/io/io_main.c` 编码器 `ec.dt_s = 0.001f`，依赖主循环 1 ms 节拍）不拦。没改：改了会动行为，且需要上板确认（[未测]）。
