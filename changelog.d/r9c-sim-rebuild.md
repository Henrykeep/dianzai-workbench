### 修复：仿真板调参在负载下“卡在 step_wait”（test_user_flow_2026H_fresh_project_memory_and_best_card 超时）

- 根因不是侧车丢了 step_result：`build/<板>/gen/board_gen.*` 按板共享、内容与应用无关，但 Makefile 的生成规则依赖
  `$(APP_DIR)/app.yaml` 并带 `--app`。新建工程（新 app.yaml）或换应用一编，`board_gen.h` 就被重写，
  同板上其它所有应用（仿真板 motor_pos / 2026H_ball …）下次 connect 时整套重编 20–60 s（负载下更久）。
  用例里先连 motor_pos 再换 2026H_ball，两次重编吃掉大半个 120 s 预算，剩下的时间正好落在调参每轮 8 s 的
  `step_wait` 里，于是看起来像“等不到单步结果”（integ10 / integ13 同一处）。
- 修复：共享 gen/ 不再依赖 app.yaml、不带 `--app`（应用 requires 仍由每个 板×应用 的 `.requires_ok` 检查）；
  `tools/gen_board.py` 内容没变就不重写 `.h/.c`（保留 mtime）。
- 回归：`tools/test_gen_shared.py`（进 make test）：换应用 / 重跑生成器后 `board_gen.h` mtime 不变；旧代码上该测试失败。
