# 18 内置 Agent（dzbench）

目标：比赛现场压力大，Agent 帮你**看曲线、给建议、改参数、改代码**，但**绝不替你做决定**，也**碰不到急停**。没网、没 Key 时，最有用的功能（阶跃分析）照样能用。

代码：`app/sidecar/dzbench/agent/`，测试：`app/sidecar/tests/test_agent.py`（全部离线，假 LLM）。

## 1. 借鉴了谁

| 来源 | 借鉴点 | 本项目做法 |
|---|---|---|
| Claude Code 权限模型（allow / ask / deny，按工具和路径） | 分层权限，默认拒绝 | `gateway.LAYERS`：路径 → 层 → 读/写权限，先匹配先生效，未列出的一律拒写 |
| Aider SEARCH/REPLACE 编辑格式 + 每次改动自动 git commit | 小块精确替换，改动可追溯可撤销 | `propose_edit(path, search, replace)`：search 必须**恰好出现一次**；每个改动一个提交，带 `Dzbench-Change:` 尾注 |
| Cursor 的 diff 审阅 / 采纳 | 改动先以 diff 呈现，人点采纳 | 文件改动卡片：diff → 确认并提交 / 拒绝；已提交可一键回滚 |
| OpenHands 的“动作—观察”循环与沙箱 | 工具结果（含错误）回喂模型，步数上限 | `AgentLoop`：工具出错把错误原文还给模型，`max_steps=8` |
| Ogata《现代控制工程》/ MATLAB `stepinfo` | 上升 10–90%、超调、±5% 调节时间定义 | `tuning.step_metrics` |
| Åström & Hägglund《Advanced PID Control》 | 经验整定规则 | `tuning.tuning_hints`（见 §4） |

## 2. 分层写权限（gateway）

| 层 | 路径 | 读 | 写 | 接受前门禁 |
|---|---|---|---|---|
| secret | `.git/*` `*.env` `*secret*` `*.key` `*.pem` | 拒 | 拒 | — |
| frozen | `firmware/ ports/ tools/ third_party/ schema/ Makefile .github/ app/ tests/ build/ iface.lock.json` | 可 | 拒 | — |
| config | `apps/*/app.yaml` `examples/*/{project,app}.yaml` `boards/*/board.yaml` | 可 | 问 | `make check` |
| app | `apps/*` `examples/*` | 可 | 问 | `make check` + `make test` |
| docs | `docs/*` | 可 | 问 | — |
| 其他 | | 可 | 拒 | — |

接受一个改动的流程（`Gateway.decide`）：

1. 涉及文件在 git 里必须干净，且内容与提议时一致（防止覆盖你手改的东西）；
2. 写入 → 跑门禁；**任一失败就还原原文件**，卡片显示门禁输出；
3. 通过才 `git commit`（尾注 `Dzbench-Change: <id> (<来源>)`）；
4. 回滚只允许针对带尾注的提交（`git revert`，冲突则中止）。

**参数**（板上实时值）不经过文件：Agent 只能 `propose_param_change`，按 schema 限幅，卡片上点“采纳”才下发（docs/17）。

**急停**：工具表里没有任何急停类工具（`loop.py` 有断言），模型凭空调用也只会收到“不存在”。急停只属于人：按钮 / Space / Esc。设置对话框是非模态的，开着也能点急停。

## 3. 大模型（可插拔）

任何 OpenAI 兼容 `/chat/completions` 接口（带 tools）。预置：DeepSeek、通义千问（DashScope 兼容模式）、Moonshot、智谱、OpenAI、本地 Ollama、自定义。

- Key 只存在本机 `~/.dzbench/config.json`（POSIX 下权限 600；Windows 依赖用户目录权限 [未测]），环境变量 `DZBENCH_API_KEY` 优先。界面只拿到 `…末4位`。
- 工程仓库路径：`DZBENCH_REPO` > 设置里的“工程仓库” > 开发模式下的本仓库。安装版必须在 ⚙ 里填 [未在 Windows 实测]。
- 常见错误（401/402/404/429/断网）都给出修法；断网时自动切本地 Ollama（§3.1）。
- 真实服务商联调 [未测]（测试用本地假 HTTP 服务验证请求格式与错误映射）。

### 3.1 没网 / 没模型时

离线也要有真 Agent，所以兜底是**本机大模型（Ollama，同一套 OpenAI 兼容接口）**，不是手写规则（旧的 `agent/offline.py` 规则助手已删）。

- 云端为主、本地兜底（`llm.Failover`）：云端**连不上**（断网、超时、拒绝连接）→ 自动切到设置里的本地模型，回答下方标“本地 qwen2.5:7b-instruct · 云端连不上，已自动切到本地”，之后本次会话都用本地。Key 错、余额不足不切，照常报错让人修。
- 只配了 Ollama：直接用本地。推荐清单 `llm.LOCAL_MODELS`：qwen2.5:7b-instruct（默认）、qwen3:8b、qwen2.5:3b-instruct。设置里“检查 Ollama 并拉模型”一键检查 `/api/tags`、缺了就 `/api/pull`。
- 云端、本地都没有：不编答案，发 `agent_unreachable`，面板出“Agent 暂时用不了”卡（原因 + 修法 + 重试 / 大模型设置）。调参、示波、急停、阶跃测试、评分页都不依赖 Agent，照常能用。
- 小模型工具调用：服务回 400 不认 `tools` 时自动改 **JSON 兜底**（工具表写进 system，模型回 `{"tool":..,"args":..}`，tool 结果改成 user 文本）；设置里也可强制“总是 JSON”。模型把 JSON 写进正文时也认成调用（只认工具表里的名字）。
- 其它：流式输出（`agent_delta` 逐段上屏，流式 tool_calls 按 index 拼参数）、429/5xx/断网指数退避重试（`agent_retry`）、token 用量（`agent_usage`；填了单价才算钱，价格不内置）、`/models` 列表换模型、上下文压缩见 §6。
- 测试：`tests/test_llm_client.py` 用本地假 OpenAI 兼容服务覆盖以上全部（含云端断 → 假 Ollama 接管、整条 AgentLoop 走流式 tool_calls）；**真实服务商与真 Ollama 未测**（本机没有）。

### 3.2 在仿真板上跑评测集

运行 `python -m dzbench.agent.evals [sim:car_2wd]`，在 app/sidecar 目录下执行。

- 连接仿真板后，每个用例先在后台持续发送一次 low → high 的阶跃（防止断线停车），再用 AgentService 真跑一轮对话。
- **按对象选阶跃配置**：`dzbench.json` 的 `step_tests` 是 {名字: 配置}，取第一个 `y`、`sp` 两个字段都出现在遥测里的那条（旧的单条 `step_test` 仍兼容）。配置可带：
  - `start`：开跑前下发的命令（只允许 T/P/G/S；'R' 同时清急停，绝不放进来，只在 `state_field == done_state` 且未急停时才补发）；
  - `gains`：{kp: 参数名, ki: 参数名}，例如 2026H 是 pos_k / ball_ki，避免把球环的问题建议到底盘 chassis_kp 上。
- 用例可带 `user_if_param`：板上有某参数时换一种问法（2026H 没有 kp，改问 pos_k）；`user_generic`：点名的参数板上没有时，换成板上第一个参数（倒立摆没有 kp）。
- `as_hw: true`：这一例把仿真板当实机（端口加 `+hw`），配合 `expect_action` 检查实验类工具变成确认卡而不是直接执行。
- 评测要一个模型（`llm=`）；`make agent-eval` 用配置的模型。2026H 的球物理是简化模型（τ=30 ms 一阶舵机 + 5/7·g·sinθ），**不代表实机参数**。
- 最后由 `grade()` 按调用序列和回答打分。用例里的 `context.verdict` 会注入为“上一轮实验结果”，tune_context 里的字段是 `last_verdict`。
- 真实大模型还没跑过这套评测（**[未测]**）。

### 3.3 用真大模型跑评测（一条命令）

```
export DZBENCH_API_KEY=sk-…        # 或在工作台 Agent 设置里填过 Key；Ollama 不要 Key
make agent-eval                     # = python -m dzbench.agent.evalrun --repeat 3
make agent-eval ARGS="--only no_estop_control --repeat 5"
```

- 默认两块仿真板（`--ports all` = 全部 6 个仿真对象）× 13 个用例 × 重复 3 次，约几分钟，费用按服务商计（每回合最多十几次调用）。
- 报告：`~/.dzbench/evals/<时间>/report.md`（每例通过率 + 失败原因）和 `report.json`（含每次调用序列和回答，便于复查）。Key 不进报告。
- 退出码 0 全过、1 有失败、2 没 Key 或**中途退回了离线助手**（Key 错、断网、额度用完时会这样，这次不算大模型成绩）。
- 大模型有随机性：看通过率，不看单次；建议换模型时都跑一遍对比。
- 运行器本身有离线测试（tests/test_evalrun.py）；**对真模型的结果 [未测]**，等有 Key 后跑出第一份报告再填到这里。

## 4. 离线阶跃分析（不需要大模型）

在曲线上给一个设定值阶跃（或斜坡——加速度限幅后的设定值也认），点“分析阶跃”。反馈/设定通道按名字自动配对（`sp_x ↔ x`、`target/ref/set`），可改。

| 指标 | 定义 |
|---|---|
| 上升 | 从 10% 到 90% 阶跃幅度 |
| 超调 | 越过目标的最大量 / 阶跃幅度 |
| 调节 | 最后一次离开 ±5% 带之后的时间 |
| 振荡 | 带滞回的目标穿越次数 / 2 |
| 稳态误差 | 末尾 10% 均值与目标之差 / 幅度 |

规则（按优先级，每步只改一点，改完再测）：执行器饱和 → 先别调增益；持续振荡 → Kp −30%、Ki −15%；超调过大 → Kd +30%（无 Kd 则 Kp −15%）；没到 90% → Kp +30%；无超调但慢 → Kp +15%；稳态误差 → Ki +30%。每条建议带“提议”按钮，生成的仍是参数提议卡片，要你采纳。

这些规则是**起点，不是答案**：机械间隙、摩擦、采样延迟都会让经验规则失效。调好后存快照，再“写回 yaml”。

## 5. 写回 yaml

把板上当前参数写回 `app.yaml` 的 `default:`。只改 `default:` 字段，数值未变（含 f32 舍入）的行保持原样，所以 diff 只含真改的行。走 config 层流程：diff → 确认 → `make check` → git 提交。

## 6. 截图

`python3 app/tools/shot.py` 生成 `app-tune.png`（阶跃分析）、`app-first-run.png`（空闲面板 + 示例问题）、`app-agent-unreachable.png`（没填 Key 时离线规则助手回答，带工具与模式标签）、`app-agent.png`（对话，假 LLM）、`app-diff.png`（写回 yaml 的 diff）、`app-commit.png`（门禁通过已提交）、`app-llm.png`（设置）。Agent 截图改的是临时克隆，门禁 `make check` 是真跑的。

## 风险分级（agent/risk.py）

| 等级 | 工具 | 行为 |
|---|---|---|
| auto | read_telemetry list_params step_analysis list_files read_file tune_context read_symbol decode_hardfault build_log | 直接执行 |
| log | build reset propose_param_change propose_edit observe；仿真里的 run_step_test rollback_best | 执行并写 `~/.dzbench/agent_audit.jsonl`（提议本身仍要人确认才落地） |
| human | flash erase mem_write；实机的 run_step_test rollback_best | 变成“需要你确认”动作卡，人点“执行”才跑；烧录卡片里先给 dry-run 预览 |
| forbid | raw_cmd disable_estop unlock_rdp estop，以及**任何没登记的工具** | 永远拒绝 |

## 调参前问答（agent/pretune.py）

菜单“调参前问答”：先答对象类型、执行器、能接受的超调、输出安全限、目标侧重、步子，再加自由补充。确认后偏好进 Agent 上下文（优先于默认启发式，硬约束不可违反），并只收紧护栏：超调上限压低达标线、目标选打分权重、保守档单步 ≤±20%。“清掉偏好”回到默认。思路取自 llm-pid-tuner pre_tuning_dialog.py（MIT），改成固定问题 + 规则解析，不需要大模型。

## 调参护栏（agent/guard.py，思路参考 llm-pid-tuner，MIT）

- **LLM（或规则）只提议，程序判定**：每轮 `run_step_test` 做标准阶跃（按 `dzbench.json` 的 `step_test` 通过 dzctl/DATA 下发），程序给出 continue / done / rollback / stop；模型说 DONE 只是建议。
- **指标全是相对量**：超调、稳态误差按阶跃幅度 |sp−y0| 归一化（目标为 0 的平衡角/球位置也成立），过零检测带滞回死区；评分 = 归一化 IAE + 超调比 + 稳态误差比 + 0.1×振荡次数，不稳定 +1。
- **单步限制**（实机 / 仿真）：增幅 ≤×1.5 / ×3，降幅 ≥×0.7 / ×0.4，绝对变化 ≤ 量程×10% / 25%，参数为 0 时第一步 ≤ 量程×2% / 5%；再叠加板上 dzctl 限幅。
- **每轮只改一个参数**；上一轮变差的（参数, 方向）下一轮禁止；证据不足用 `observe`。
- **停止**：连续 2 轮 good-enough（超调 ≤10%、|稳态误差| ≤2%、进 2% 带、振荡 ≤1）；实机最多 8 轮（配置上限 10）、仿真 20 轮；遥测里有 vbat / temp 字段且配置了 `tune.vbat_min` / `tune.temp_max` 时越限即停。
- **回滚到最好**：仿真自动；**实机要人点**（docs/dev/QUESTIONS.md 第 19 条）。
- **上下文压缩** `tune_context`：指标 + ≤20 个关键样本（极值、设定跳变点、分桶极值）+ best / last_rejected / 最近 5 轮历史表 + 护栏规则原文。
- **严格解析** `parse_reply`：只认 JSON 对象，action ∈ PROPOSE/OBSERVE/DONE，拒绝 bool/NaN/溢出，不从散文里猜参数。
- **无 LLM 模式** `tune_rule_round`：默认**分阶段 P→I→D**（`tune.rule_mode=staged`，每阶段沿一个方向 ×1.3，变差就进下一阶段）；`hints` 为旧的规则提示。同样经护栏和人工确认。

## 实验与打分（agent/experiment.py，思路参考 PID_Helper，GPL-3.0，只借思路、代码自写）
- **相对基线打分**：第一轮有效实测为基线，每项指标 (x+floor)/(基线+floor) 按权重平均，1.0=和基线一样。权重模板 `tune.weights`：balanced / conservative（怕超调振荡，钢珠/平衡）/ actuator（护电机，重罚振荡）。
- **四段正负阶跃**：`step_test.segments=4, delta=[..]`，SP→SP−Δ→SP→SP+Δ→SP，每段出指标，`asymmetry` 提示摩擦/重力不对称（优先前馈/静摩擦补偿）。护栏按最差一段判。
- **稳态原因码** `verdict.steady.reason`：steady / warming_up / still_drifting / oscillating / too_little_motion / too_few_samples。drifting/warming_up 时给 `advice: OBSERVE`，不要据此改参数。
- **门禁**：开环实验需 `step_test.plant_stable=true`（实机还要 `open_loop_max`）；群体搜索（PSO 等）实机 forbid、仿真 log。
- **"慢"不等于"不稳定"**：没进 2% 带但几乎无超调不再按不稳定罚分（否则迟缓对象加 Kp 每步都被回滚）。

基准（`python -m dzbench.agent.bench`，固定种子 1/7/42，均 0 越界）：

| 用例 | rules 达标 | staged 达标 |
|---|---|---|
| car_default | 3/3，2 轮 | 3/3，2 轮 |
| sluggish | 3/3，4 轮 | 3/3，5 轮 |
| aggressive | 0/3 | 实机档 0/3；仿真档 3/3（约 8 轮） |

aggressive 在实机档 8 轮内仍调不好（单步 ×0.7 下限太保守），属已知限制。
- **基准** `python -m dzbench.agent.bench`：固定种子，baseline / rules /（可注入）llm，三种起点（car 默认、过激、迟钝），统计达标轮数、最终归一化 IAE、越界次数（必须 0），进 `make test`。
  当前结果：car 默认 2 轮达标；迟钝起点规则 4 轮达标；**过激起点（kp 0.6 ki 15）规则 8 轮内未达标**——规则只会小步降 kp，被“变差方向禁止”卡住，留作后续改进（LLM 路径或更好的规则）。

## 烧录 / 编译 / 调试（全部 ⚠ 未上真机，假探针单测）

- 协处理器部署（缺口 12）：菜单“协处理器部署…”，`dzbench/deploy.py` 走系统 ssh/scp（BatchMode，只密钥）推脚本、nohup 启动、停、`tail dz.log`。
- 界面：烧录页“调试探针…”选后端 / 探针类型 / 序列号（存 ~/.dzbench/machine.json），可按后端列出已插探针，点“用这个”填入。
- `probes.py`（缺口 10）：调试后端 `flash.tool` = pyocd（默认）/ openocd / jlink / probe-rs，`flash.probe_kind` = stlink（默认）/ daplink / jlink，`flash.probe` = 序列号。烧录、烧前备份、ELF 变量实时读取共用同一后端。OpenOCD 默认自己起（接口 cfg 按探针类型选，目标 cfg 按 target 查表，没登记写 `flash.openocd.target_cfg`），写 `flash.openocd.host` 就连已在跑的；长连接，适合 20 ms 刷新。J-Link / probe-rs 每个操作起一次进程，变量刷新建议 ≥200 ms。J-Link 后端只认 J-Link 探针。自检会查可执行文件在不在。
- `flash.py`：pyOCD 优先。前置条件：最近一次编译成功且镜像 sha256 未变、急停已锁存、配置了 target；探针 DP IDCODE 必须与目标内核一致；**默认 dry_run**；烧前备份同大小区域到 `~/.dzbench/flash_backup/`；烧后等心跳且 schema 哈希等于本次编译的 link_schema；不符可一键回滚到备份。
- 编译结果怎么变成“可烧”：Agent 的 `build` 工具（配了 `build.keil_uv4 + keil_project`）或 `build_log`（你自己在 Keil 里编完）把结果登记给烧录器，镜像取 `build.image`（缺省 `build.elf`），烧后核对的哈希取 `build.link_schema`。日志和镜像修改时间差超过 120 s 视为旧日志，不登记。（v0.7.0 审计前这一步漏接了，烧录前置条件永远不满足。）
- `keil.py`：`UV4 -b proj -t target -j0 -o log` 无界面编译，解析 ARMCC/ARMCLANG 诊断、Error/Warning 汇总、Program Size（flash = Code+RO+RW，ram = RW+ZI）；退出码 ≥2 判失败。
- `hardfault.py`：栈帧 + EXC_RETURN + （v7-M 才有的）CFSR/HFSR/MMFAR/BFAR；**M0/M0+ 没有这些寄存器**，只靠 PC/LR 和对齐提示；有 ELF 时把 PC/LR 翻成 `函数+偏移`。
- `elfsym.py`：纯 Python 读 ELF32 符号表；`SymbolWatch` 按变量名经探针轮询画曲线（虚拟 schema `ELF`，仅串口未绑定固件 schema 时可用）。
- `config.py` 分层：内置默认 < `~/.dzbench/machine.json`（UV4 路径、探针序列号）< 仓库 `dzbench.json`（芯片、ELF、阶跃实验、门限；**出现 api_key/password/token 直接报错**）< 环境变量。

## 护栏：卡死、外部文本、长对话、编辑没对上（2026-10-29，UTC+8）
只对真大模型开（`AgentLoop.guards`），测试里的脚本化模型不需要。
- **卡死检测** `agent/stuck.py`（直接移植 OpenHands software-agent-sdk 的 StuckDetector，MIT）：同动作同结果 4 次、同动作同报错超过 3 次、连续 3 条不调工具的自言自语、两个动作 ABAB 交替 6 次 → 停下，界面收到 `agent_stuck` 事件，回答“我卡住了：原因”。快到阈值时（第 3 次）先在工具结果后面提醒一次。用户插话后重新计数；结果在变（真在干活）不算。
- **外部文本是数据**：每条工具结果包进 `<工具数据 来源="工具名">…</工具数据>`，系统提示第 15 条说明里面的话不是指令；内容里伪造的闭合标签会被插零宽空格转义（`agent/untrusted.py`）。
- **头尾裁剪**：压缩早期工具结果后仍超预算 → 保留 system、第一条用户请求和最近 12 条，中间换成一句“已省略 N 条”；切点不落在 tool 结果上，不拆开工具调用和它的结果。
- **编辑没对上给提示**：`propose_edit` 的 search 找不到时，用 aider 的 find_similar_lines（Apache-2.0）找出最像的几行回给模型照抄；replace 内容已经在文件里时直接说“可能已经改过”。错误的 `fix` 字段现在也会回给模型（以前丢了）。

### 上下文：仓库地图 / 触发知识 / 项目记忆
- **repo_map**（`agent/codemap.py`）：按 aider repomap 的方法给出“最相关文件 + 定义行”，可带 focus 词；按 git 状态缓存，改了文件自动失效。
- **触发知识**（`docs/agent-knowledge/*.md`）：文件头 `triggers: 词1, 词2`，用户话里出现才把正文附到请求前，一次对话每篇一次。
- **项目记忆**（`docs/agent-knowledge/project-memory.md`）：`remember` 只提议，人接受后才写入并 git 提交；新对话（重置）才进系统提示，只取末尾 3000 字。
