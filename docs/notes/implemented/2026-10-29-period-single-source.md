# 控制周期只有一个来源

- **决定**：题目工程的子系统周期只写在 `project.yaml` 的 `period_ms`，生成 `PERIOD_MS_*`，调度与 dt 都用它；apps/ 单文件应用的周期宏必须同时交给 `pal_timer_start` / `.period_ms`。
- **为什么**：用户 p1 工程 `User/encoder.h:11` 写 `CONTROL_FREQUENCY 300`，实际 100 Hz 调用，速度错 3 倍，编译和仿真都看不出来（user-projects/review.md:131）。
- **守护**：`tools/check_deps.py` 规则 F1，夹具 `tools/fixtures/deps_F1_hand_freq`。
- **已补（同日）**：数字字面量的 dt 也拦了（check_deps F1 `check_dt_literal`，夹具 `deps_F1_dt_literal`）。2026H 的 `ec.dt_s = 0.001f` 改成和主循环门控共用 `IO_TICK_MS`；门控从 `now == last` 改成 `now - last < IO_TICK_MS`，取 1 时两者等价，example 测试 35/35。[未测] 上板。
- **仍漏**：主循环卡顿超过一个节拍时，编码器仍按标称 dt 算（实际间隔更长 → 速度偏大）。修它要让 encoder 接收实测间隔，属于 encoder 的接口改动，没做。
- **否决**：把 `sim_setup.c` 也纳入——那里的 dt 是仿真对象的物理积分步长，不是控制周期，强行改成周期宏反而把两件事绑死。
