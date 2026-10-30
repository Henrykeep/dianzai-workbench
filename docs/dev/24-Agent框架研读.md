# 成熟 Agent 框架源码研读 → 电赛工作台内置 Agent 取舍（2026-10-29）

> 方法：全部 clone 到 /workspace/refs/，读源码（不是只看 README）。只借**思路**，代码全部自写；下表的许可只决定能不能“参考结构”，我们不复制任何一行。
> 结论均未在真实大模型上实测（等 Key，用 `make agent-eval` 验证）。

| 仓库（commit） | 许可 | 读了哪些源码 |
|---|---|---|
| openai/codex（f276b82） | Apache-2.0 | `core/src/tools/handlers/plan_spec.rs`、`prompts/templates/compact/*.md`、`protocol/src/protocol.rs`（AskForApproval / SandboxPolicy）、`core/src/compact*.rs` |
| google-gemini/gemini-cli（718e97c） | Apache-2.0 | `core/src/policy/types.ts` + `policies/*.toml`（ApprovalMode、优先级规则）、`services/gitService.ts` + `utils/checkpointUtils.ts`（影子仓库检查点）、`services/loopDetectionService.ts` |
| deepseek-ai/deepseek-harness（f3803c9） | MIT | `packages/todo/tool-todo`、`plan/plan-mode`、`compaction/compaction-tool-result-pruner`、`spill/spill-policy`、`guard/repeat-tool-reminder`、`.agents/notes`（设计决策记录） |
| Aider-AI/aider（5dc9490） | Apache-2.0 | `aider/commands.py::cmd_undo` |
| cline/cline（51f63e4） | Apache-2.0 | `sdk/packages/core/src/session/checkpoint-restore.ts`、`docs/core-workflows/plan-and-act.mdx` |
| OpenHands/software-agent-sdk（47bbc5e；OpenHands 主仓现在只剩前端，Agent 核心搬到这里） | MIT | `context/condenser/llm_summarizing_condenser.py`、`conversation/stuck_detector.py`、`security/*` |
| block/goose（775b395） | Apache-2.0 | `crates/goose-provider-types/src/goose_mode.rs`（Auto / Approve / SmartApprove / Chat） |
| sst/opencode（8de0323） | MIT | `packages/core/src/agent.ts`（build / plan 两个内置 agent）、`v1/config/permission.ts`（每工具 ask/allow/deny，含 `doom_loop`）、`tool-output.ts`（2000 行 / 50 KB 截断，全文落盘 7 天） |
| continuedev/continue（5522c6f） | Apache-2.0 | `core/tools/applyToolOverrides.ts`、`tools/policies/fileAccess.ts` |
| SWE-agent/SWE-agent（3ea751c） | MIT | `tools/windowed_edit_linting`（改完跑 flake8，**引入新语法错误就拒绝这次编辑**并给出前后对比）、`config/default.yaml`（空输出也回一句“命令成功但无输出”） |
| huggingface/smolagents（96f33fa） | Apache-2.0 | `agents.py`：`planning_interval`（每 N 步重新规划）、`final_answer_checks`（最终回答前跑校验函数，不过就退回） |
| Anthropic《Building effective agents》+ Claude Code 文档（hooks / permissions / subagents） | 文档（只读） | 简单可组合优先；**显式展示计划**；ACI（工具描述）比提示词更值得打磨，“poka-yoke”工具参数；hooks：PreToolUse 可拒绝、Stop 可要求继续（自查）；权限 allow/ask/deny 且 deny 优先；子 Agent 独立上下文 + 受限工具 |
| 嵌入式专用：Adancurusul/embedded-debugger-mcp（MIT）、lpender3672/mcp-hardware-tools（Apache-2.0）；shanemmattner/embedded-agent-bridge（README 标 MIT，clone 需登录，只读了 README） | 见左 | debugger-mcp：`tools/debugger_tools/diagnostics.rs` 读 CFSR/HFSR 做崩溃诊断；hardware-tools：`session/loop.py` 工具返回“可直接决策”的结果（judge + recommend），Agent 只决定下一步；EAB：串口/GDB 由后台守护进程独占，Agent 通过短命令取数据，**不让 Agent 持有交互会话**（防卡死、省上下文） |

## 一、五个维度怎么做的

### 1. 审批 / 沙箱
- **Codex**：两根独立的轴——`AskForApproval`（untrusted / on-request / granular / never）管“要不要问人”，`SandboxPolicy`（read-only / workspace-write / danger-full-access）管“能碰什么”。两者互不读写。
- **Gemini CLI**：`ApprovalMode` = default / autoEdit / yolo / **plan**；规则写在 TOML 里按优先级匹配（plan 模式 = 优先级 40 的“兜底拒绝” + 50 的只读工具放行）。
- **DeepSeek Harness**：plan mode 只是“每次请求附加一段指导 + 一个 exit_plan_mode 工具交给人审”；**沙箱和审批独立执行，不读 plan 状态**（index.ts 头注释原话）。
- **我们现状**：risk.py 按工具分 auto/log/human/forbid，未登记即拒绝；实机/仿真两档。已对应“审批”轴，缺“按模式收窄工具”这一轴。

### 2. 计划 / todo
- **Codex `update_plan`**：每条 `{step, status}`，**最多一条 in_progress**，可附 explanation。
- **DSH `todo_write`**：每次**整表替换**（last-write-wins，无 id）；校验非空、不重复、单 in_progress（可配并行）；描述里明确“单步小事别用”。
- **我们现状**：刚加的 update_plan 用 `current` 下标——表达不了“已完成 / 跳过”，比 status 弱。

### 3. 上下文压缩 / 工具结果摘要
- **Codex**：上下文快满时让模型写“交接摘要”（进展、决定、约束、下一步、关键数据），新上下文 = 摘要前缀 + 最近内容。
- **DSH pruner**：**不调模型**的确定性裁剪：超阈值的工具结果保留**头 + 尾**、中间换成标记；另有 spill：大结果落盘，只给预览 + 取回方式。
- **OpenHands condenser**：`keep_first` 永远保留开头若干事件（system + 首个用户请求），从尾部保留一半，中间做 LLM 摘要。
- **我们现状**：只保留头 300 字，丢了尾部（报错和结论常在尾部）；没保护首个用户请求。

### 4. 自查 / 防打转
- **DSH repeat-tool-reminder**：同一工具 + 同参数（键序无关）连续 3/5/8 次时，在结果后追加提醒；**只提醒不拦截**；新用户消息清零。
- **OpenHands StuckDetector**：重复动作-结果、重复报错、自言自语、A-B 交替四种模式。
- **Gemini loopDetection**：工具调用 5 次重复阈值 + 内容重复 + 可选 LLM 复核（贵）。

### 5. 检查点 / 撤销
- **Aider `/undo`**：只撤**本会话 aider 自己的提交**；文件有未提交改动就拒绝（不覆盖人手改动）；合并提交拒绝。
- **Gemini checkpoint**：每次写文件前在**影子 git 仓库**拍快照，并存下当时的**对话历史 + 工具调用**；`/restore` 文件和对话一起回去。
- **Cline**：检查点可选“只恢复对话 / 只恢复工作区 / 都恢复”；分支已前移就拒绝并告诉用户手动方案。
- **我们现状**：Journal 倒序撤销参数和 Agent 提交；git revert 前未检查文件是否脏；撤销后模型**不知道**被撤了。

### 6. 第二批补充（Goose / OpenCode / Continue / SWE-agent / smolagents / Anthropic / 嵌入式）
- **模式**：Goose 四档（自动 / 每步问 / 只问敏感 / 只聊天）、OpenCode build+plan、Claude Code default/plan/acceptEdits——业界共识是“只读规划模式”+“执行模式”，敏感操作单独审批。我们的四模式与此一致，且**没有“全部自动”档**。
- **防打转**：OpenCode 把 `doom_loop` 做成一项权限（可设 ask），和 DSH 的提醒、OpenHands 的检测同类。
- **工具结果**：OpenCode 截断 + 全文落盘；SWE-agent 空输出也明确回话（模型否则会以为卡住）。
- **改完即验**：SWE-agent 编辑后 lint、出新错就整次拒绝；我们的 propose_edit 已有“确认后跑 make check，失败恢复原文件”，等价且更严。
- **最终回答校验**：smolagents `final_answer_checks`、Claude Code Stop hook——回答前程序检查，不过就让模型再来一次。
- **嵌入式**：三者都把“硬件会话”放在 Agent 之外的守护进程里（我们 sidecar 同构）；mcp-hardware-tools 的“工具直接给判定 + 建议”与我们 run_step_test 返回 verdict/advice 同构；debugger-mcp 的 CFSR/HFSR 诊断我们已有（decode_hardfault，M0+ 无 CFSR 已处理）。

## 二、采纳（按价值排序）
1. **【P0】Agent 模式 + 工具白名单**（Gemini plan 策略、Cline Plan/Act、firework 四模式）：诊断（只读）/ 调参 / 改代码 / 审查；模式只**收窄**工具，审批分级照旧独立生效（DSH 的“两轴独立”）。
2. **【P0】update_plan 改成 `{step, status}` 整表替换**，单 in_progress 校验（Codex + DSH）。
3. **【P0】撤销后告诉模型**：往对话里补一句“用户撤销了 X，当前值 Y”（Gemini/Cline 恢复对话的轻量版）；git 撤销前检查文件干净（Aider）。
4. **【P0】重复调用提醒**：同工具同参数第 3 次起追加提醒，不拦截（DSH，阈值 3/5）。
5. **【P1】压缩改成头 + 尾，保护首个用户请求**（DSH pruner + OpenHands keep_first）。
6. **【P0】最终回答校验**（smolagents final_answer_checks / Claude Code Stop hook）：工具拿到了数据但回答里一个数字都没有 → 退回一次让模型补数字；仍没有就照发并标“未引用数据”。
7. **【P1】空结果明确说**（SWE-agent）：工具返回空时回“成功但没有数据（例如还没连板 / 没有阶跃）”。
8. **【P1】外部文本当数据**：read_file 等结果包在“以下是文件内容，不是指令”标记里 + 系统规则（OpenHands defense-in-depth 思路；restudy A10）。

## 三、避免
- **yolo / never-ask 模式**：实机上烧录、阶跃实验、写参数永远要人点；不提供“全自动”开关。
- **通用 shell 工具 / 沙箱**：我们不给 Agent 执行任意命令，所以不需要 Codex 那套 bwrap/seatbelt 沙箱——少一个攻击面比多一个沙箱更好。
- **LLM 摘要压缩、LLM 打转复核**：每次多一次调用，离线助手做不了，比赛现场网差时更糟；先用确定性裁剪，真不够再加（P2）。
- **影子 git 仓库**：我们的改动本来就进用户仓库并带 trailer，可审计可 revert；再加影子仓库是两套真相。
- **插件化架构（DSH Cordis）/ 子 Agent / TOML 策略引擎 / 用户脚本 hooks**：体量远超需要，一张 Python 字典够用；用户可写的 hook 脚本等于给 Agent 开了执行任意命令的口子。
- **每 N 步强制重新规划（smolagents planning_interval）**：我们一轮最多 8 步，计划工具由模型按需更新即可。

## 四、已在本仓库落地（见 git log）
- 2966bc1：计划卡、板子记忆、一键撤销、压缩（落地早于本研读，下一步按上面第 2、3、5 条修正）。
