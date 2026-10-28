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
