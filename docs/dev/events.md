# 侧车 → 界面事件约定

## 急停 `type: "estop"`

一条统一事件，按 `state` 区分阶段；`source` 是来源（`ui` / `board` / `agent` …），不再有 `src`、`sent`、`message`。
代码里的权威定义：`Session.ESTOP_EVENT_KEYS`（`app/sidecar/dzbench/session.py`），测试断言键集合与之精确一致。

| state | 必有键 | 可选键 | 说明 |
|---|---|---|---|
| `requested` | `type` `seq` `state` `source` `t` `ok` `message_zh` `cause_zh` | `fix_hint_zh` | 上位机已发出急停帧；`ok=false` = 没写出去（断电/拔电池） |
| `latched` | `type` `seq` `state` `source` `t` | `cause` `message_zh` `cause_zh` `fix_hint_zh` `latency_ms` | 板子心跳确认锁存；`latency_ms` 是 requested→latched 的诊断值，仅在本次由上位机发起时给出 |
| `cleared` | `type` `seq` `state` `source` `t` | `message_zh` `cause_zh` `latency_ms` | 人工 R 解除，**且固件心跳 bit10 已清零**（发 R 后第一帧 bit10=0 的心跳；老固件心跳无状态字时取下一帧心跳）。侧车不提前宣告：R 发出到确认前仍锁存（`tx_locked`），`latency_ms` = R 发出到确认的时长；固定提醒 agent_notice `estop_cleared` 紧随其后、只推一次 |

- `t`：毫秒 Unix 时间；`seq`：单调递增。
- 文案拆分：`cause_zh` 只讲原因（界面时间线只显示它）；`fix_hint_zh` = 怎么解除（固定为“确认安全后点“解除急停””），**只在急停仍有效时出现**（`requested` 且 `ok=true`、`latched`），`cleared` 和未送达的 `requested` 没有；`message_zh` = `cause_zh`（有提示时再接“；”+ `fix_hint_zh`），给旧界面兼容。`link.state`/`status` 里的 `estop_cause` 同样带 `cause_zh`，锁存期间另带 `fix_hint_zh`；原因随锁存持久化，重连/侧车重启后仍在，直到人工解除才清空。
- 没连板子 / 回放时的急停回包不是状态事件（无 `state`）：键集合固定为 `type` `ok` `reason` `message_zh`（代码 `Session.ESTOP_REPLY_KEYS`），`ok=false`，`reason` 为 `no_board`（没连板子，只弹提示、不进告警条）或 `replay`（回放中）。不再有 `sent` / `message` / `nolink` / `src`。
- 前端对旧格式（`sent` / `message`）与新格式都兼容。

## 只下发目标 `op: "setpoint_set"` 与 `status.sp_before_latch`

- 请求 `{op:"setpoint_set", name, value}`：只发 DATA id=1（设定值槽位 = 遥测里带 `ref_for` 的字段，按出现顺序；其他槽位保持遥测当前值），**不跑阶跃实验**。成功返回 `{name, value, slot}`。
- 急停锁存中（`tx_locked`）拒绝：`error.code = "estop_locked"`，`fix_action = "estop_clear"`，`extra.reason = "state"`。
- 按 link_schema 校验，从不钳位：`name` 不是设定值 → `invalid_param`（`reject: "name"`）；非十进制数 / NaN / Inf → `invalid_param`；有 `link.step` 通道且 `|value| > range` → `invalid_param`（`reject: "range"`）。
- `status.sp_before_latch`：锁存那一刻冻结的急停前主设定值（`link.step[0].sp` 槽位，没有则第 0 槽；取锁存前最后一帧遥测，因为固件锁存时把设定值清零），解除后仍保留供「恢复急停前目标」；`setpoint_set` 成功后变 `null`。没有设定值字段 / 没收到过遥测时为 `null`。
- 阶跃实验进行中（心跳 bit17）拒绝且不发：`error.code = "iter_busy"`，`fix_action = "stop_iteration"`，`message_zh` 「阶跃实验进行中，结束或停止后再设定目标」；不中止本轮。
- 设定值通道 `hold`（`latched` | `timeout`，app.yaml link 设定值通道上的字段，侧车原样透传；**缺省按 `timeout`**）：先看 `link.step` 里 `sp` 同槽的条目，再看遥测字段本身。
  `hold = timeout` 的通道（板子按 cmd_timeout 自己把目标清零）拒绝且不发：`error.code = "hold_timeout"`，`fix_action = "restart_experiment"`，`message_zh` 「这块板子的目标不会保持，重新开始实验即可」。侧车**不做**保活重发。
- 透传位置：`schema` 摘要的 `setpoints: [{name, slot, ref_for, hold}]`（另带 `step`），`status.setpoints` 同结构。

## 自动迭代 `iterate.*`（#38）

`iterate.started` / `iterate.round` / `iterate.param_reject` / `iterate.stopped`，字段见 `docs/dev/iterate.md` 第 7 节。阶跃开始被拒：`step_estop`（带 `fix_action: "estop_clear"`）、`step_busy`、`step_bad_arg`、`step_unsupported`、`step_offline`。

入口（界面 #62 / 脚本，与 Agent 工具 `iterate_start` / `iterate_cancel` 同一实现，见 entrypoints.yaml）：

| op | 请求 | 返回 |
|---|---|---|
| `iterate_start` | `{target, params?, dur_ms?, ch?}`；`params` 缺省 = 增益参数 | 仿真：`{status: "started", budget: {time_s, rounds}}`；实机：`{status: "pending_human_click", action_id}`，同时推一张 `agent_action`（tool=`iterate_start`）批量确认卡，确认走 `agent_action_decide`。已在跑 → `error.code = "iterate_running"` |
| `iterate_cancel` | `{}` | 立即停止（板上本轮中止，参数停在当前值），随后推 `iterate.stopped reason=stopped` |
| `iterate_status` | `{}` | `{running, result}`，`result` = 最近一次 `iterate.stopped`（含 `best_card`），没跑过为 null |

每次迭代的事件顺序（每条都带 `type`）：

1. `iterate.started` `{plan, start, start_hash, limits: {time_s, rounds}}`——**`limits.rounds` 就是本次的轮数上限 N**（实机 8 / 仿真 20），`limits.time_s` 是时间预算（180 s）。界面显示“第 i / N 轮”用它，不要写死。
2. 每轮一条 `iterate.round`：`iterate.md` 第 2 节字段（`iter` 0 = 起始参数基线，之后从 1 计；无效轮 `valid=false` 不占号）+ `local_hash` `unit` `band` `changed`。
3. 0~多条 `iterate.param_reject` `{name, value, reason}`（候选值被本地 / 板子拒，换方向，不算一轮）。
4. 恰好一条 `iterate.stopped` `{reason, message_zh, rounds, best{iter, params, params_hash, metrics, pass, gaps}, next_zh, pass_basis}`；`reason` ∈ pass / budget_time / budget_rounds / estop / stopped / invalid / no_improve / unstable / blocked / error（`error` 时只有 `reason` `message_zh`）。
5. 有 `best` 时紧接一张 `agent_action`（tool=`iterate_apply_best`，标题“采用最好参数”，`preview.changes` = 旧→新）：**仿真和实机都要人点**，确认后逐个写回并回读核对；Agent 一轮调参以这张卡收尾（#53）。

## 模型列表 `op: "agent_models"` 的返回

键集合固定为 `ok` `models` `reason` `fix_action` `message_zh`（代码：`llm.MODELS_KEYS`；测试断言精确一致，不再有 `message`）。成功时 `reason` / `fix_action` 为 `null`。

| reason | 触发 | fix_action |
|---|---|---|
| `unsupported` | HTTP 404 / 405 / 501，或响应不是 OpenAI 格式 | `manual_model` |
| `empty` | 列表为空 | `manual_model` |
| `auth` | HTTP 401 / 403 | `check_key` |
| `error` | 其他 HTTP 错误、网络错误、未填地址 | `retry` |
| `contest_mode` | 比赛模式且未启用云端、地址不是本机（localhost / 127.0.0.1 / ::1）：**不拼 URL、不发请求** | `enable_cloud` |

- `message_zh` 只按类别给中文（网络：连接超时 / 域名解析失败（DNS）/ 连接被拒绝 / TLS/证书握手失败 / 网络错误），不含原始异常、不含 Key。
- 原始报错先脱敏（替换 api_key 值、`Bearer …`、`sk-…`）再写本地日志 `~/.dzbench/logs/llm_models.log`。
- `contest_mode` 时回包另带 `human_only: true`、`goto: "settings:cloud"`（键集合 = 上面五个 + 这两个），并另推一条 `{type: "agent_error", code: "contest_mode", message_zh, fix_action: "enable_cloud", human_only: true, goto: "settings:cloud", retryable: false}`（键集合精确如此，没有 `message`）。
- 开关：`~/.dzbench/config.json` 的 `contest_mode` / `cloud_enabled`。`contest_mode` 暂无设置入口（TODO），`cloud_enabled` 只能经下面的确认路径改。

## 合规底线：启用云端只能由人

比赛模式下是否把数据发往外部模型服务，是参赛合规问题，**只能由人决定**：

- 凡返回 `fix_action: "enable_cloud"` 的地方（`agent_models` 回包、`agent_error`、Agent 调用被拒）都带 `human_only: true`；给 Agent 的只有跳转 `goto: "settings:cloud"`，与 `set_run_mode` 的 `human_only` / `goto: "step:封箱"` 同一机制（`dzbench/human_only.py`）。
- 修改 `cloud_enabled` 的唯一途径：界面确认卡确认后发 op `set_cloud_enabled {enabled, confirmed: true}`。侧车用与 `set_run_mode` 相同的 `require_confirmed` 校验——只认布尔 `true`，否则只回 `{ok:false, needs_confirm:true, message_zh}`，不改任何东西。
- `contest_mode` / `cloud_enabled` 不在设置表单的可写键里：`agent_config`（`save_config`）传了也忽略，并原样保留文件里的值。
- Agent 工具表里没有、也不得有能改 `cloud_enabled` / `contest_mode` 的工具；`script_ops` 不得包含 `set_cloud_enabled`；名字含这些词的工具调用一律以 `human_only` 拒绝（内置 Agent 与外部 `agent_tool` 都是）。Agent 传 `confirmed: true` 无效。
- 自动流程（`quick_start`、Agent 步骤）不读写这两个开关。
- 入口登记：`docs/dev/entrypoints.yaml` 的 `enable_cloud`（`at: toolbox:设置`，`human_only: true`，`ops: [set_cloud_enabled]`），不进 `script_ops`。
- 守护测试：`app/sidecar/tests/test_cloud_guard.py`。

### J-Link 工具识别（#49）

`flash.tool = jlink` 时只认 SEGGER J-Link：路径里有 `SEGGER` 直接认；否则跑 `<exe> -?`（stdin 关闭、5 s 超时）要求输出含 `SEGGER`。
Windows 依次试 `JLink.exe`、`JLinkExe`（JDK 的 `jlink.exe` 大小写不敏感地撞名）。只找到 Java jlink 时：
`code = "jlink_not_segger"`，`fix_action = "install_jlink"`，`message_zh` 「找到的 jlink 是 Java 工具，不是 SEGGER J-Link，请安装 J-Link 软件包」；
自检 `tool_status` 与 `list_probes_for("jlink")` 的返回同样带 `fix_action` / `message_zh`。完全找不到也给 `install_jlink`。

### 急停 `board_t_ms` / 连上即已急停

- 心跳尾部（0.6.0 起，偏移 16–27，共 28 字节）`u32 cause, u32 t_ms, f32 value`：`t_ms` 是锁存时的板上时刻 → `latched` 事件的 `board_t_ms`（`status.estop_cause.board_t_ms` 同值）。
- 32 字节心跳在 28 处再带 `u32 clear_t_ms` → `cleared` 事件的 `board_t_ms`；28 字节心跳的 cleared 不带 `board_t_ms`。按长度解析（40+ 字节的 28.. 是自检，不当 clear_t_ms）。
- 连上时板子已急停（bit10 一开始就是 1，或按端口/身份恢复了锁存、没有上升沿）：第一帧带原因的心跳也推一次 `latched`（带 `cause` / `cause_zh` / `board_t_ms`），每次连接只推一次。

## 模型重试 `type: "agent_retry"`（r8 llm_503）

模型服务出可重试错误（429 / 5xx / 网络）时，每次自动重试前推一条：`{attempt, max, wait_s, code, why, message_zh}`。
`message_zh` 直接给用户看（例：「模型服务暂时不可用（HTTP 503），1.6 秒后自动重试（第 2/4 次），不用重发」）；`why` 是服务原话（已截断、打码）。
502/503/504 最多重试 `RETRIES_5XX = 4` 次（退避 0.8→1.6→3.2→6.4 s），其余按 `retries`（默认 2）；用尽后照常推 `agent_error`（`message` 末尾写明“已自动重试 N 次仍失败”）+ `agent_unreachable`，不会无声挂住。

## 模型服务忙 `type: "llm_retry"`（502 / 503 / 504）

仅 502/503/504 时，与 `agent_retry` 同一时刻再推一条：`{attempt, max, wait_s, code, fix_action, message_zh}`。
- `attempt` / `max`：第几次 / 最多几次（`RETRIES_5XX = 4`）；`wait_s`：本次等待秒数（退避，单次 ≤ 30 s）。
- `fix_action: "switch_local_model"`：界面据此给「换成本地模型」按钮（打开模型设置，选本地/局域网的 OpenAI 兼容服务）。
- 429 和断网不发 `llm_retry`（不是服务端忙，换模型未必有用），只有 `agent_retry`。

## 自动新建项目 `type: "project_forked"`（开局按最近例题建，不出卡）

开局一句话命中内置例题时，本地服务直接把例题复制成新项目目录（例题只读不动），推：`{example, project, path, message_zh}`，
`message_zh` 固定为「已基于 <example> 新建 <project>，可更换」，Agent 回复第一句同样是这句。想换例题或从头建，直接跟 Agent 说。

## “采用最好参数”卡的 `args.ss_err` / `preview.ss_err`

`{measured, unit, band: {limit, unit, item, source}, inside, note_zh}`：实测稳态误差（绝对值）、题目误差带及出处（`source` 如「题目 B3：… ≤ 1cm」；
题目没写时为默认口径 2%，`source` 会写明）、本次是否在带内。
- 仿真板：单位对不上时用仿真对象自己的标称几何换算（`dzbench.json` `step_tests.<应用>.sim_nominal` `{from, to, per, source}`，
  如 2026H_ball：`SIM_PX_PER_M=600`，1 px = 1/6 cm），多一个 `converted: {value, unit, note_zh}`，`inside` 照常判 true/false，
  `note_zh` 含「仿真标称换算，未实机标定」。仿真对象没有这层几何时 `inside: null`。
- 实机：单位对不上时 `inside: null`，`note_zh` 说明需先标定（#51）。
- `pass_basis`（字符串，卡上 `ss_err.pass_basis`，也在 `iterate.stopped` / `iterate.stopped（engine=host_step）` 顶层）：“达标停止”的依据。迭代本身一律按默认口径判达标，
  取值：「按默认 2% 判定（题目没写误差带）」/「按默认 2% 判定，题目误差带待标定」（`inside: null`）/
  「按默认 2% 判定达标；另对照题目 B3：钢球误差绝对值 ≤ 1cm：在带内|超出」。界面原样显示，别只写“已达标”。

## “采用最好参数”卡的 `args.compare` / `preview.compare`

`{round0: {iter, metrics: [...]}, best: {iter, metrics: [...]}, unchanged, note_zh}`：第 0 轮（初值）和最好一轮并排。
`metrics` 每项是 `{key, value, unit}`（`value` 为数值，`unit` 单独给，如 `sse`→遥测单位 px、`overshoot_pct`→`%`、`iae`→`px·s`）；
`key` ∈ ss_err_pct / sse / overshoot_pct / overshoot / settle_ms / settling / iae。`iterate.stopped` / `iterate.stopped（engine=host_step）` 顶层也带 `round0`。
`unchanged: true`（最好一轮就是初值）时 `note_zh` 为「初值已达标，未改参」（初值没达标时为「初值就是最好一轮，未改参（仍未达标…）」），
不写“第0轮最好”；否则为「第 N 轮比初值好：sse 3 → 1px，…」。

## `status.agent`（Agent 状态唯一来源）

`hello.status` 和周期 `status` 都带 `agent: {state, fix_action?, message_zh?}`，`state` ∈ `ready` / `unconfigured` / `busy`：
- `unconfigured`：没配模型（无 Key 且不是本地 Ollama），带 `fix_action: "configure_model"`（界面打开“大模型设置”）。
- `busy`：正在回答（`agent_ask` 进行中）或自动迭代在跑。
- `ready`：其余。界面只看这个字段，不要自己拼。

## 参数提议 `type: "proposal"` 的 `source`

`source` ∈ `llm`（大模型调 `propose_param` 提的）/ `rule_engine`（分阶段 P→I→D、规则提示、继电起步、仿真搜索算的）。
原来的中文来源说明移到 `source_zh`（如「规则引擎」「继电起步」「仿真搜索」）。

## r9q 补充

- **调参模式工具**：只剩 `iterate_start` / `iterate_cancel`（外加只读、扫频、评分）。仿真板没有板上阶跃（如 2026H_ball）时，`iterate_start` 自己改走上位机阶跃，事件仍是 `iterate.started` / `iterate.round` / `iterate.stopped`，`engine: "host_step"`。
- **`sim_starting`**：`{type, state: "start"|"ready", message_zh?, elapsed_s?}`。首次连仿真板要先同步编译（冷编译约 11–15 s），期间先发 `start`，连上发 `ready`。同一仿真口的重复连接会排队并复用（`connect` 返回 `reused: true`），不会拆掉重编。
- **`board_switch`**：例题建项目时，若已连着别的仿真板，自动换到例题自己的板（`project.yaml` 的 `sim_board`，缺省 `sim:<例题>`）；实机不动。`project_fork` 结果带 `sim_board`。
- **项目编号**：只看 `projects/` 下真实存在的目录（大小写不敏感），干净 HOME 第一个是 `2026h-ball`，没有 `-2`。
- **提议 `origin`**：原始调用方（`agent` / `规则引擎` / 其他），journal 据此记录；对外看 `source` 枚举。
- 内置例题自带 `requirements.yaml`，读题已完成，不向用户要 PDF 路径。

## 迭代结果持久化、卡片 verdict、换例题（前端用）

- **`iterate_status`** 返回 `{running, result, last}`。`last = {board, t, result}`：最近一次 `iterate.stopped`（含 `best_card`、`card`、`ss_err`、`pass_basis`、`verdict`）按 **项目 + 板卡** 存在 `<项目>/.dz/iterate_last/<板卡>.json`，刷新页面或重启侧车后仍能还原；内存里没有结果时 `result` 回落到 `last.result`。
- **`verdict`**（`iterate.stopped`、`iterate_apply_best` 卡、`card` 都带）：`pass | fail | unknown`，附 `verdict_zh`。
  - `ss_err.inside` 为 `null`（单位对不上 / 实机未标定）→ 一律 `unknown`，界面显示 `verdict_zh`，**不得**写「各项指标均已达标」。
  - `inside=true` 且停止原因 `pass` → `pass`；其余 → `fail`。
- **WS op `project_switch_example {example}`**：从内置例题复制出全新项目（新 slug，例题目录只读、不复用旧项目），只写审计（`project_switch_example`）不出确认卡；推 `project_forked {example, project, path, message_zh, via: "project_switch_example"}`，返回同样字段加 `fork`。例题不存在 → `bad_example`。

## 提交确认 `commit_confirm_request`（#88）

写文件确认卡（`change`）带 `scope: "write_only"`：**只授权写文件**。`change_decide accept=true` 后写入 → 跑门禁 → `change.status = "written"`（不再直接 `committed`），并紧接推送：

`{type:"commit_confirm_request", request_id, repo_root, branch, files:[{path, status}], message, message_zh, status}`

- `files[].status`：`A` 新建 / `M` 修改。`message` 是将用的 git 提交信息（原文），`message_zh` 是给人看的一句话。
- `status`：`pending` → `committed` / `rejected` / `failed`（结果会再推一次同一事件，外加更新后的 `change` 卡）。
- 界面回复 WS op：`{"op":"commit_confirm","request_id":<id>,"approve":true|false}`。
  - 批准：提交，返回 `{ok:true, ...change 卡（status=committed, commit=短哈希）}`。
  - 拒绝或超时：不提交，返回 `{ok:false, reason:"commit_declined", reason_zh, fix_action:"ask_user_commit", ...请求字段}`；文件仍留在工作区。提交本身失败时 `reason:"commit_failed"`。
- Agent 发起的任何 git 写操作（commit/branch/reset/push/tag/merge/rebase/checkout/revert/stash/cherry-pick）未经批准一律返回 `{ok:false, op, reason:"commit_declined", reason_zh, fix_action:"ask_user_commit"}`，不执行。
- `pending` 列表里同时包含待批的 `commit_confirm_request`。
## r9c：有效性、换算出处、迭代时长（#75 #92 #93 #94）

- **唯一有效性判定** `iterate.step_invalid`：台账 `tune_round`、结果卡、规则提议、自动迭代 `iterate.round` 都用它。原因码 `why_invalid` 新增 `zero_step`（阶跃幅度 < 回位容差）。规则引擎最近一轮无效时只回 `OBSERVE`，不出改参提议。
- `iterate.round` 新增 `step_amp`、`step_tol`（物理单位）。
- `iterate.stopped`（`reason: "invalid"`）新增 `why_invalid` 和 `reason_zh`（如「连续无效：阶跃幅度为 0（目标就是当前位置）」），卡片按它写原因，不再只写「没有可用的一轮」。
- 新事件 `iterate.dur_extended {dur_ms, why}`：窗口太短（`settle_zero` / `no_rise`）时阶跃时长翻倍重做同一轮（上限 30000 ms），不计入「连续 3 轮无效」。
- 目标等于当前位置时，迭代先把设定值退到 目标 − 量程×25% 再跳；无效轮重跑回同一起点。
- `pass_basis` / `verdict_zh` 一律写明换算出处：「按仿真标称换算、未实机标定」「按实机标定换算」「同单位直接比较、无需换算」；实机未标定为 `inside: null` + 「待标定：实机未标定」。
## metrics_card（指标卡，草案 r10 #82）

一道题一张卡，取代单独的调参卡。前端只认 `items` 统一列表渲染；字段名只在 `app/ui/src/fieldmap.ts` 对接。

| 字段 | 说明 |
|---|---|
| `task_kind` | `control` / `measure` / `power` / `other`，Agent 读题面判断 |
| `task_kind_reason` | 判断依据（一句话） |
| `items[]` | 每条指标一项，见下 |

`items[]` 每项：

| 字段 | 说明 |
|---|---|
| `name`, `clause` | 指标名、条款号（如「要求(3)」） |
| `spec_text` | 题面原文，一字不改 |
| `target` | `{op, value, unit}`；抽不出 = `null`，并在 `pass_basis` 写「按默认判定」 |
| `measured` | `{value, unit, method, n}`：实测值、单位、测量方法、样本数 |
| `uncertainty` | 不确定度；`measure` 类必填 |
| `verdict` / `verdict_zh` | `pass` / `fail` / `unknown` + 中文 |
| `pass_basis` | 一句话判定依据；卡在哪（饱和、时延过大、非最小相位、待标定）也写这里 |
| `source` | `sim` / `real` / `calibrated` / `manual`。**只由固件握手帧上报的运行环境与标定状态决定**，上层传入一律忽略；握手没报 → `sim` 并标「来源未知」；人填值 → `manual` |
| `evidence` | 录波 / 原始数据文件路径 |
| `method` | `auto` / `manual`（外部仪器测的） |
| `manual_steps` | manual 时：用什么仪器、怎么接线、读哪个数 |
| `procedure` | 给评委看的测试步骤：条件、次数、读数方法 |
| `manual_entry` | `{value, by, at}`：人填的值、填写人、时间（UTC+8） |
| `tuning`（可选） | 控制类：`{round0, best, ss_err, …}`，原调参卡字段并入 |
| `calibration`（可选） | 测量类：校准系数、校准信号源 |

导出：后端出 CSV / xlsx，列与 `items` 字段一一对应（计划中，未实现）。
门禁（#78 `tools/tunegate.py`）用 plant.json 真值对比 `measured` / `verdict` 判假达标。

## r9e（#100 / #101 / #102）

- `result.cleared` `{reason: iterate_start|reconnect|board_change, message_zh}`：迭代开始、重连、换板时推送；前端收到后清空结果 / 判定卡。`iterate_status` 在清空后、新结果出来前返回 `result: null, last: null, cleared: true`。
- `list_ports` 每次重扫仿真对象；sim 端口新增 `app`、`app_name`（app.yaml `name:`）、`label`（`仿真 · 应用名`）。只声明 `plant:` 的项目也列为仿真板。
- Agent 工具 `change_status`（只读）：每张改代码卡 `{id, title, files, write_status, commit_status, commit, status_zh}`；Agent 每轮上下文附「改代码卡真实状态」（#99）。
- `iterate.stopped`：没有任何稳定轮（有效且超调 ≤ 40%）时 `best: null`，`message_zh: "发散，未找到稳定参数"`。
- `ss_err` 新增 `value_source: sim_nominal|hw_measured`，`pass_basis` 末尾写明「测量值为仿真标称值 / 实机实测值」。
