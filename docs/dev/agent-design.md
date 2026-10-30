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
失败处理：工具错误原文回给模型（含 fix）、空输出明说、卡死检测、最终回答“必须引用数字”自查一次、云端连不上自动切本地 Ollama，都没有就出“暂时用不了”卡（重试 / 设置）。

## 2. 这次的改动（按省掉的人工排序）

1. **项目步工具**（agent/steptools.py）：`project_state`（只读，从文件数出哪步已完成、下一步要什么输入、评分项/证据条数）、
   `flow_preview`（= op flow_preview，只写 ~/.dzbench/flow 暂存区，log 级）、`flow_accept`（= op flow_accept，human 级确认卡）、
   `score_items`（= op score_items，只读）。**全部直接调 projflow.Flow / scoring 的同一函数**，不另写逻辑；entrypoints.yaml 已登记归属。
2. **确认后自动备好下一步**：flow_accept 卡被点“执行”后，服务端立刻跑下一步预览，通过就再出一张卡；
   下一步要人给的东西（题目 PDF、CubeMX 工程路径）时只报告“需要什么”，不猜。
3. **仿真里采纳即验证**：Agent 的单个参数提议在仿真板上被采纳后，自动做一次验证阶跃（复用仿真搜索的 verify_groups 通路）。
   实机不自动——实机阶跃仍是 run_step_test 确认卡（含实验前检查）。
4. （第三轮已删：离线规则助手整个去掉，见第三轮。）
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

## 第二轮（project_chain / 评分 / 自动调参 / 标定联调工具）

| 步 | 新工具 | 风险级 | 说明 |
|---|---|---|---|
| 项目 | `project_chain` | log | 依次预览 读题→方案→（导入 或 从零新建，芯片取 scratch_options 第一个可用项）→分配→生成；前一步在沙盒 `~/.dzbench/flow/<code>/sandbox` 里 accept，后一步才看得到；仓库不动 |
| 项目 | `project_apply` | human | 一张卡按顺序调 `Flow.accept`（暂存区就是卡上审过的内容）；某步失败就停、报告已写的 |
| 项目 | `project_state` | auto | 现在认本题自己的板子（project.yaml boards.main / alloc/board.yaml 草稿名）、.ioc 是否写了、CubeMX 是否已 GENERATE |
| 标定 | `polarity_check` | auto | 与标定页同一函数 `dzbench/pageops.py` |
| 联调 | `fft`、`wave_measure` | auto | 同上（server.py 的内联实现搬进 pageops，op 和工具共用） |
| 评分 | `score_run` | 实机 human / 仿真 log | 按 step_test 跑 N 次，用 accept.py（=accept.ts）判；只认评分项点名的规格或题目原文给的 band，不拿示例规格凑数 |
| 评分 | `score_save`、`score_writeback` | human | 调 scoring.save / writeback；回写卡上展示 diff，执行时用同一 sha |
| 调参 | `tune_autopilot` | 仿真 log，实机拒绝 | rule_round→采纳→阶跃→护栏判，到 done/stop/rollback 或 N 轮；没 done 就回到最好一轮 |

点击（一次发消息或点按钮记 1 下）：

| 流程 | 页面手动 | 第一轮 Agent | 第二轮 Agent |
|---|---|---|---|
| 新题：读题→方案→从零新建→生成 | ≥8 | 1 + 每步 1 张卡（≥5） | **2**（问 + 一张总卡） |
| 仿真调参到护栏通过 | 每轮 4 | 每轮 2 | **1**（问，0 张卡） |
| 评分一项 ×3 → 证据 → 回写 | 6 | — | **3**（问 + 保存卡 + 回写卡） |

测试：tests/test_agent_steps.py（脚本化模型，离线）。真模型：本机没有 ~/.dzbench/config.json、没有 DZBENCH_API_KEY、没有本地 ollama，**没测真模型**。
已知不足：确认卡预览还是 JSON 原样展示；离线助手还不会触发 tune_autopilot / score_run（只有接了大模型时可用）。


## 第三轮（2026-10-30）

1. **确认卡不再是原始 JSON**（agent/cards.py → agent.ts renderAction）：标题 + 一句话总结 + 仿真/实机标签 + 步骤时间线；
   每步列改动行，排序 引脚 → 参数 → 证据 → 文件（文件只显示文件名，“新文件 N 行”或“+a −b”），旧值划线 → 新值琥珀色；
   超过 6 行折进“查看改动”，里面带着色 unified diff（≤80 行）。同一张卡里后一步对前一步的结果做 diff。底部“执行/拒绝”吸底。
   flash 的原始 dry-run 计划留在 preview.plan（测试用），界面不显示 JSON。截图自查两轮：
   ①文件名被截断、引脚被文件挤下去 → 只显示文件名、引脚排前；②卡在对话流里被压扁、“执行”看不到 → flex:none + 吸底操作栏。
2. **大模型为主路径，规则助手删除**：offline.py 及其测试、evalrun --offline、两条离线评测测试已删。离线 = 本机 Ollama（见 docs/18 §3.1）。
3. **首次接入**：没配置时自动弹“接上大模型”（每次会话一次）：服务商卡片（含硅基流动）、地址/模型（“列出可用模型”= GET /models）/Key（可显示）、
   “测试连接”（op agent_config_test，用表单值发一句话，不写配置，401 等错误只显示服务给的那句话 + 修法）、
   本地兜底开关 + 推荐小模型 + “检查 Ollama 并拉模型”（op agent_ollama）、高级（工具调用 自动/JSON、单价、工程仓库）。
4. **客户端**（agent/llm.py）：流式、流式 tool_calls、重试退避、token/费用、JSON 兜底、Failover。全部对本地假服务测过（tests/test_llm_client.py、test_llm_setup.py）。
5. 回答下方一行状态：谁在答（大模型 / 本地，切换原因）、累计 token（填了单价显示 ¥）、重试中、已改 JSON 兜底。

截图：walk/shots/agent_5..8（确认卡）、llm_1..3（首次接入、401、通过）、llm_6..10（拉模型中、就绪、云端流式、断网切本地、全断时的卡）。
