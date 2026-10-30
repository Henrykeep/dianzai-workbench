# 内置 Agent 设计（v2：跟着比赛时间线干活）

用户口径：**Agent 是每一步页面的助手，替人把能做的做完；人只在“写板子 / 烧录 / 写文件”时点确认。**
总体说明见 docs/18-内置Agent.md；本篇只记这次的取舍。

## 1. 审计结论（2026-10-30）

| 时间线步 | 之前 Agent 能做的 | 缺口 |
|---|---|---|
| 项目 | 读/改仓库文件（propose_edit）、仓库地图、计划、记忆 | **不能推进项目页五步**：读题/方案/导入/分配/生成全靠人点；不知道项目走到哪一步 |
| 烧录 | build / build_log / flash（确认卡）/ flash_rollback | — |
| 模块 / 联调 / 标定 | 只有通用 read_telemetry / list_params | 标定向导、联调 io 没有工具（留待后续） |
| 调参 | tune_context、step_analysis、提议参数、阶跃/扫频实验、回到最好一轮、TuneGuard 判定 | 仿真里采纳后还要人再点一次“阶跃实验”；并且整组验证从来没触发过（见 §3 bug） |
| 评分 | 无 | 看不到评分项和证据 |
| 封箱 / 排障 | decode_hardfault、read_symbol | — |

安全：工具白名单 + risk.py 四级（auto/log/human/forbid，默认拒绝）+ 确认卡 + TuneGuard 限幅 + 急停不在工具表（断言）。
上下文：OpenHands 式压缩（旧工具结果截断 + 头尾裁剪）、触发词知识包、人确认才写的项目记忆、板级记忆。
失败处理：工具错误原文回给模型（含 fix）、空输出明说、卡死检测、最终回答“必须引用数字”自查一次、LLM 连不上退回离线规则助手。

## 2. 这次的改动（按省掉的人工排序）

1. **项目步工具**（agent/steptools.py）：`project_state`（只读，从文件数出哪步已完成、下一步要什么输入、评分项/证据条数）、
   `flow_preview`（= op flow_preview，只写 ~/.dzbench/flow 暂存区，log 级）、`flow_accept`（= op flow_accept，human 级确认卡）、
   `score_items`（= op score_items，只读）。**全部直接调 projflow.Flow / scoring 的同一函数**，不另写逻辑；entrypoints.yaml 已登记归属。
2. **确认后自动备好下一步**：flow_accept 卡被点“执行”后，服务端立刻跑下一步预览，通过就再出一张卡；
   下一步要人给的东西（题目 PDF、CubeMX 工程路径）时只报告“需要什么”，不猜。
3. **仿真里采纳即验证**：Agent 的单个参数提议在仿真板上被采纳后，自动做一次验证阶跃（复用仿真搜索的 verify_groups 通路）。
   实机不自动——实机阶跃仍是 run_step_test 确认卡（含实验前检查）。
4. 离线规则助手加“项目”剧本：没 Key 也能“推进项目 X”。
5. 系统提示第 16 条：项目推进的 plan→act→verify 顺序（状态 → 预览 → rc=0 才出卡；缺输入就问）。
6. 知识：EDC-Skill 三篇原文（拆题决策树、串口协议、视觉优化手册）收为触发词知识包 edc-*.md。

## 3. 顺手修的 bug

`verify_after_decide` 判 `status == "applied"`，但 `AgentTools.decide` 返回里 set_param 的 `status`（ok/clamped）把它盖掉了，
所以“仿真搜索 → 上板验证”的整组自动阶跃**从来没触发过**。改为接受 applied/ok/clamped。

## 4. 不做的

- 不给“全自动”模式；不把 flow_accept 降级；不让 Agent 碰急停。
- 标定 / 联调 / 模块步工具：等这些页的入口函数稳定后再包（避免两条路径）。

## 5. 点击数（tests/test_agent_steps.py 守着）

口径：发一句话或点一个按钮记 1 下；给文件/路径两边都要，不计。

| 场景 | 之前（手动页面） | 现在（Agent） |
|---|---|---|
| 项目：读题 + 方案 | 4（运行、确认 ×2） | 3（一句话 + 2 张卡；方案卡是自动备好的） |
| 仿真调参一轮 | 4（阶跃实验、规则建议、采纳、阶跃实验） | 2（一句话 + 采纳；验证阶跃自动） |
