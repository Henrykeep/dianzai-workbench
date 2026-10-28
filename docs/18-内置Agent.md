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
- 常见错误（401/402/404/429/断网）都给出修法；断网时提示改用“分析阶跃”或本地 Ollama。
- 真实服务商联调 [未测]（测试用本地假 HTTP 服务验证请求格式与错误映射）。

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

`python3 app/tools/shot.py` 生成 `app-tune.png`（阶跃分析）、`app-agent.png`（对话，假 LLM）、`app-diff.png`（写回 yaml 的 diff）、`app-commit.png`（门禁通过已提交）、`app-llm.png`（设置）。Agent 截图改的是临时克隆，门禁 `make check` 是真跑的。

## 风险分级（agent/risk.py）

| 等级 | 工具 | 行为 |
|---|---|---|
| auto | read_telemetry list_params step_analysis list_files read_file tune_context read_symbol decode_hardfault build_log | 直接执行 |
| log | build reset propose_param_change propose_edit observe；仿真里的 run_step_test rollback_best | 执行并写 `~/.dzbench/agent_audit.jsonl`（提议本身仍要人确认才落地） |
| human | flash erase mem_write；实机的 run_step_test rollback_best | 变成“需要你确认”动作卡，人点“执行”才跑；烧录卡片里先给 dry-run 预览 |
| forbid | raw_cmd disable_estop unlock_rdp estop，以及**任何没登记的工具** | 永远拒绝 |

## 调参护栏（agent/guard.py，思路参考 llm-pid-tuner，MIT）

- **LLM（或规则）只提议，程序判定**：每轮 `run_step_test` 做标准阶跃（按 `dzbench.json` 的 `step_test` 通过 dzctl/DATA 下发），程序给出 continue / done / rollback / stop；模型说 DONE 只是建议。
- **指标全是相对量**：超调、稳态误差按阶跃幅度 |sp−y0| 归一化（目标为 0 的平衡角/球位置也成立），过零检测带滞回死区；评分 = 归一化 IAE + 超调比 + 稳态误差比 + 0.1×振荡次数，不稳定 +1。
- **单步限制**（实机 / 仿真）：增幅 ≤×1.5 / ×3，降幅 ≥×0.7 / ×0.4，绝对变化 ≤ 量程×10% / 25%，参数为 0 时第一步 ≤ 量程×2% / 5%；再叠加板上 dzctl 限幅。
- **每轮只改一个参数**；上一轮变差的（参数, 方向）下一轮禁止；证据不足用 `observe`。
- **停止**：连续 2 轮 good-enough（超调 ≤10%、|稳态误差| ≤2%、进 2% 带、振荡 ≤1）；实机最多 8 轮（配置上限 10）、仿真 20 轮；遥测里有 vbat / temp 字段且配置了 `tune.vbat_min` / `tune.temp_max` 时越限即停。
- **回滚到最好**：仿真自动；**实机要人点**（docs/QUESTIONS.md 第 19 条）。
- **上下文压缩** `tune_context`：指标 + ≤20 个关键样本（极值、设定跳变点、分桶极值）+ best / last_rejected / 最近 5 轮历史表 + 护栏规则原文。
- **严格解析** `parse_reply`：只认 JSON 对象，action ∈ PROPOSE/OBSERVE/DONE，拒绝 bool/NaN/溢出，不从散文里猜参数。
- **无 LLM 模式** `tune_rule_round`：规则给一项建议，同样经护栏和人工确认。
- **基准** `python -m dzbench.agent.bench`：固定种子，baseline / rules /（可注入）llm，三种起点（car 默认、过激、迟钝），统计达标轮数、最终归一化 IAE、越界次数（必须 0），进 `make test`。
  当前结果：car 默认 2 轮达标；迟钝起点规则 4 轮达标；**过激起点（kp 0.6 ki 15）规则 8 轮内未达标**——规则只会小步降 kp，被“变差方向禁止”卡住，留作后续改进（LLM 路径或更好的规则）。

## 烧录 / 编译 / 调试（全部 ⚠ 未上真机，假探针单测）

- `flash.py`：pyOCD 优先。前置条件：最近一次编译成功且镜像 sha256 未变、急停已锁存、配置了 target；探针 DP IDCODE 必须与目标内核一致；**默认 dry_run**；烧前备份同大小区域到 `~/.dzbench/flash_backup/`；烧后等心跳且 schema 哈希等于本次编译的 link_schema；不符可一键回滚到备份。
- `keil.py`：`UV4 -b proj -t target -j0 -o log` 无界面编译，解析 ARMCC/ARMCLANG 诊断、Error/Warning 汇总、Program Size（flash = Code+RO+RW，ram = RW+ZI）；退出码 ≥2 判失败。
- `hardfault.py`：栈帧 + EXC_RETURN + （v7-M 才有的）CFSR/HFSR/MMFAR/BFAR；**M0/M0+ 没有这些寄存器**，只靠 PC/LR 和对齐提示；有 ELF 时把 PC/LR 翻成 `函数+偏移`。
- `elfsym.py`：纯 Python 读 ELF32 符号表；`SymbolWatch` 按变量名经探针轮询画曲线（虚拟 schema `ELF`，仅串口未绑定固件 schema 时可用）。
- `config.py` 分层：内置默认 < `~/.dzbench/machine.json`（UV4 路径、探针序列号）< 仓库 `dzbench.json`（芯片、ELF、阶跃实验、门限；**出现 api_key/password/token 直接报错**）< 环境变量。
