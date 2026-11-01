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

- ~~`result.cleared`~~（已被 r9g `result_reset` 取代，见文末）`{reason: iterate_start|reconnect|board_change, message_zh}`：迭代开始、重连、换板时推送；前端收到后清空结果 / 判定卡。`iterate_status` 在清空后、新结果出来前返回 `result: null, last: null, cleared: true`。
- `list_ports` 每次重扫仿真对象；sim 端口新增 `app`、`app_name`（app.yaml `name:`）、`label`（`仿真 · 应用名`）。只声明 `plant:` 的项目也列为仿真板。
- Agent 工具 `change_status`（只读）：每张改代码卡 `{id, title, files, write_status, commit_status, commit, status_zh}`；Agent 每轮上下文附「改代码卡真实状态」（#99）。
- `iterate.stopped`：没有任何稳定轮（有效且超调 ≤ 40%）时 `best: null`，`message_zh: "发散，未找到稳定参数"`。
- `ss_err` 新增 `value_source: sim_nominal|hw_measured`，`pass_basis` 末尾写明「测量值为仿真标称值 / 实机实测值」。

- `files[].status`：`A` 新建 / `M` 修改。`message` 是将用的 git 提交信息（原文），`message_zh` 是给人看的一句话。
- `status`：`pending` → `committed` / `rejected` / `failed`（结果会再推一次同一事件，外加更新后的 `change` 卡）。
- 界面回复 WS op：`{"op":"commit_confirm","request_id":<id>,"approve":true|false}`。
  - 批准：提交，返回 `{ok:true, ...change 卡（status=committed, commit=短哈希）}`。
  - 拒绝或超时：不提交，返回 `{ok:false, reason:"commit_declined", reason_zh, fix_action:"ask_user_commit", ...请求字段}`；文件仍留在工作区。提交本身失败时 `reason:"commit_failed"`。
- Agent 发起的任何 git 写操作（commit/branch/reset/push/tag/merge/rebase/checkout/revert/stash/cherry-pick）未经批准一律返回 `{ok:false, op, reason:"commit_declined", reason_zh, fix_action:"ask_user_commit"}`，不执行。
- `pending` 列表里同时包含待批的 `commit_confirm_request`。

### autotune op / step_too_large（#107–#109）
- `{"op":"autotune","spec_text":"…","ch":0,"seed":0}`：通用整定，和 `tools/tunegate.py` 用的是同一份 `tuning.autotune`。参数名、范围和 max_delta 来自握手参数表（参数的 `role`，或 link.step.u_max 指向的参数 → ulim，其余按名字猜）；量程和 max_step 来自 link.step。只在仿真里跑，实机返回 `hw_needs_human`。找不到比例增益时返回 `no_roles`。
- `iterate_start` / `iterate_plan`：没传 params 时，用握手参数表里所有声明了 [min,max] 的浮点参数；没写 abs_tol 时，取 sensor_range × 1%。
- `step_too_large`（message_zh + fix，fix_action=`lower_step`，带 `max_step`）：iterate 的阶跃目标、或一次设定值跳变超过 link.step.max_step 时返回。
- 探测幅度 = 量程 × PROBE_FRAC，受 max_step 限制；没声明量程时用最小可测幅度（不再固定 0.05）。
- 参数角色（字段规格，gen_link / randplant 由嵌入式开发-2 加）：app.yaml `link.params.<名>.role` ∈ P/I/D/FF/LIM/other，握手参数表带 `role`（没写为 null）。后端只认这个声明，名字猜测只当建议；LIM / other 不参与整定，也不进 iterate 的默认参数集。
- #123：角色只从握手 `params[i].role` 来（P/I/D/FF/LIM/other 或 null），侧车不按参数名猜（`guess_gain` 已删）；LIM / other 不参与整定。`tools/tunegate.py` 也从握手表（randplant 写的 app.yaml 经 gen_link）取角色，不读 plant.json。
- `autotune` 角色没声明时返回 `{"verdict":"needs_human","reason":"roles_unconfirmed","missing":[名],"suggested":{名:角色},"message_zh","fix","fix_action":"confirm_roles"}`，不跑。
- `suggested` 只按结构给：`link.step.u_max` 指向的参数 = `"LIM"`，其余 `null`（要人选），不按名字猜。
- `{"op":"confirm_roles","roles":{<参数名>: "P"|"I"|"D"|"FF"|"LIM"|"other"},"app_dir"?,"confirmed"?,"change_id"?}`（#145 两步）：不带 `confirmed` 只预览、**不写任何文件**，返回 `{ok:true, needs_confirm:true, change_id, target, diff, copy_from, message_zh}`；再发 `{"op":"confirm_roles","confirmed":true,"change_id":…}` 才写（change_id 一次性，复用报 `no_change`；预览后文件被改过要重新预览）。只写 `$DZBENCH_HOME/projects/<名>/app.yaml`：app_dir 是仓库 apps/ 或 examples/ 时先把整个应用目录复制到工程目录再写；app_dir 在工程目录之外报 `not_project_dir`。带 `protect` 的参数（schema 或 app.yaml `protect:`）不许给 P/I/D/FF，报 `protect_param_role`（带 `params`、`reason`、`message_zh`、`fix_action:"confirm_roles"`）。其它失败 `bad_role` / `bad_param`。角色与握手一致时 `{ok:true, roles, unchanged:true}`。Agent 工具同名但只能预览，确认必须由人点卡片。
- `iterate_plan` 没给 dur_ms（或用默认目标）时先实测阶跃时序；测不出来（会话不支持 / 失败）就退默认，结果带 `fallback: ["dur_default"|"span_quarter"|"max_step"]`、`message_zh`（说明退了什么、为什么）和 `fix_action: "measure_step_timing"`。

## 上位机心跳 / 心跳超时急停

- 侧车心跳：专用线程，每 250 ms 一帧（`Session.HOST_HB_PERIOD_S`），按单调时钟定拍，不拿 session.lock（只用写锁）。
- 板端阈值归固件（嵌入式开发-2）：当前 `apps/include/link_app.h` `dzctl_wd_init(&L->wd, 1000u)`；改为可声明、默认 1500 ms 并在握手上报 `wd_timeout_ms`。侧车读 schema `wd_timeout_ms`（或 `link.wd_timeout_ms`），没报 = `null`，文案里整段不写阈值（#138），不编造。串口卡死检查在单独线程 `_stall_loop`。
- ~~（已被文末 r9g 取代：gap_ms→measured_ms）~~ 心跳超时急停的 `estop_cause` / `estop state:"latched"`：`cause:"hb_timeout"`、`message_zh:"心跳超时 <实测间隔> ms"`、`gap_ms`、`threshold_ms`（可为 null）、`detail_zh`、`fix_action:"estop_clear"`（一键解除）。
- ~~（已被文末 r9g 取代）~~ `$DZBENCH_HOME/estop_latch.json` 每条记录：`source`、`detail`、`t`（epoch s）、`latched_at`（ISO 本机时间带时区，如 `2026-10-31T21:58:03+0800`）、`reason`（原因码，如 `hb_timeout`）、`gap_ms`、`threshold_ms`、`cause`。锁存持久化是设计行为，只有人点解除才清。
- 侧车重启 / 重连恢复锁存：`estop_cause` 与 `tx_locked` 事件、`estop` 阻塞项都带 `restored:true`、`fix_action:"estop_clear"`，`message_zh` 形如 `21:58 心跳超时 1001 ms，已锁存`。

### #102 被控量到量程（dzctl 0.15.0 心跳 bit18 `DZCTL_HB_SENSOR_SAT`）
- status 的 `hb_flags` 多一项「被控量到量程」（实时、不锁存；旧固件恒无）。
- status 带 `sensor_sat: bool`：最新一帧心跳的 bit18（`DZCTL_HB_SENSOR_SAT`），不锁存；旧固件 / 没心跳恒 false。
- 自动迭代每轮记录 `sensor_sat: bool`（该轮阶跃期间任一心跳带 bit18）；到量程的轮不算稳定。
- `iterate.stopped` 加 `sensor_sat: bool`（最后一轮到量程）；没有稳定轮或最后一轮到量程 → `best: null`，`message_zh: "发散，未找到稳定参数"`。
- 急停阈值 `threshold_ms` 取握手 `wd_timeout_ms`（固件 fw-wd，默认 1500）；握手未上报为 null。

## r9g 最终字段（以本节为准，覆盖上文 r9e / 心跳一节的临时名）

### #101 结果清空 `type: "result_reset"`
`{run_id, reason: "iterate_start" | "reconnect" | "board_change"}`。`run_id` 是清空后的新一轮运行 id（reconnect / board_change 时为当前 run_id）。前端收到后清空结果 / 判定卡。

### #104 `list_ports` 仿真条目
sim 端口加 `app_name`（app.yaml `name:`，没有则取目录名）和 `app_dir`（项目目录绝对路径）。`label` 仍为 `仿真 · <app_name>`。

### #115 台账 / 运行
- 每条台账记录带 `run_id`；每次 `iterate_start` 开一个新 `run_id`。
- 最好参数、“初值即最好”只在当前 `run_id` 内计算。
- 手动阶跃实验记录 `kind: "manual_step"`，不算迭代轮，不参与最好参数；迭代轮 `kind: "round"`。

### #116（= #102）/ #121 最好参数与判定
- `best` 永不指向无效 / 发散 / 到量程（心跳 bit18 `DZCTL_HB_SENSOR_SAT`，dzctl 0.15.0）的轮；没有稳定轮或最后一轮到量程 → `best: null`，`message_zh: "发散，未找到稳定参数"`。每轮和 `iterate.stopped` 带 `sensor_sat: bool`。
- verdict `pass` 时总带 `verdict_zh: "通过"`。

### 急停 status / 事件（`estop`、`status.estop_cause`）
`{reason, reason_zh, latched_at, measured_ms, threshold_ms, restored, fix_action}`
- `reason`：原因码（如 `hb_timeout`、`manual`）；`reason_zh`：中文说明（心跳超时为 `心跳超时 <measured_ms> ms`）。
- `latched_at`：ISO 本机时间带时区，如 `2026-10-31T21:58:03+08:00`。
- `measured_ms`：实测间隔（取代旧的 `cause.value` / `gap_ms`，#118）。
- `threshold_ms`：取握手 `wd_timeout_ms`（固件 fw-wd，默认 1500，阈值归固件）；握手没有该字段则为 `null`。
- 手动急停：`measured_ms` / `threshold_ms` **不出现**（不是 null）。
- `restored: bool`：重启后从 `estop_latch.json` 读回为 true。
- `fix_action: "estop_clear"`。
`estop_latch.json` 记录同名字段：`reason`、`reason_zh`、`latched_at`、`measured_ms`、`threshold_ms`。

## 随包数据表 `hello.data_tables`（#136）
`hello` 返回里多一项 `data_tables: {roles, reason_codes}`，每项为 `{sha256, content}` 或 `null`：
- `sha256`：对文件原始字节（docs/dev/<名>.json）算的十六进制 SHA-256；`content`：原样解析的 JSON（不改字段）。
- 文件缺失、不是合法 JSON 或 `schema_version` 不认识 → 该项为 `null`，同时 `progress` 出阻塞项 `{code/reason: "data_file_missing", file, message_zh, fix_action: "reinstall"}`。两份都必需（#144）：`reason_codes.json` 缺失 / 损坏同样为 `null` + `data_file_missing`，自检 `ok:false`、CLI 退出 1。结构校验：roles.json 要有非空 `roles`；reason_codes.json 每项要有 `zh`。
- 查找顺序：安装包解包目录 → `DZBENCH_REPO` → 本仓库根。命令行自检：`python -m dzbench selfcheck-data`（必需表缺失退出 1）。
- `roles.content`：`{schema_version: 1, roles: [{code, zh}]}`；侧车的 `no_roles` 提示也只读这份。

### op `selfcheck_data`（数据文件自检）
请求 `{op:"selfcheck_data"}` → `{ok, items:[{file, status:"ok"|"missing"|"invalid", message_zh, fix_action}]}`；`fix_action` 为 `"reinstall"` 或 `null`。
与 `python -m dzbench selfcheck-data`、独立脚本 `python <安装目录>/app/sidecar/selfcheck_data.py`（自己把所在目录放进 sys.path，适配忽略 PYTHONPATH 的嵌入式 Python）是**同一个函数** `datafiles.report()`，脚本打印同一份 JSON，缺必需文件退出 1。面向用户的 `message_zh` 不出现命令行，只说“重新安装工作台”“点『运行自检』”。
## #129 降幅测试（题面幅度超过 max_step / 量程）
- `autotune` 结果和 metrics_card `items[]` 每项加 `amp_reduced: true`、`amp_spec`（题面阶跃幅度）、`amp_tested`（实际测的幅度）、`warning_zh: "按降幅测试，未验题面幅度"`；没降幅时这些字段都不出现。
- 同时带 `amp_unit`：被阶跃信号（link.step 的 y）在握手里声明的单位；没声明 = `null`（不写死）。`amp_unit_decl`：这个单位在 app.yaml 里的声明键路径 `link.telemetry.fields[name=<y>].unit`（没声明单位 = `null`），界面“改单位”直接指过去。
- 同时带 `retest_blocked_by`：按题面幅度 `amp_spec` 重测会不会被 iterate_start 拒（#109，同一个函数 `dzbench.tuning.steplimit.step_block`）。会被拒 → `{reason:"step_too_large", limit:<声明的 max_step>, limit_unit:<单位或 null>, limit_name:"link.step[<ch>].max_step", message_zh:"题面幅度 X 超过声明的单步上限 M，需先在声明里放宽 max_step 或确认执行器能承受", fix_action:"edit_declaration"}`；能重测 → `null`。
- 降幅时本来达标的项 `verdict: "partial"`、`verdict_zh: "未验题面幅度"`，整卡 verdict 也是 `partial`，永不给 `pass`。未达标项仍是 `fail`。
- `tools/tunegate.py`：降幅却给了 pass 算假达标（硬红）。

## 原因待确认（#125 之前的过渡规则）
- 未达标但特征不足以归类时：`category` / `reason` 为 `"unconfirmed"`，`pass_basis` 以「原因待确认」开头，不给错误类别。

## tunegate 分桶（判卷侧，tools/tunegate_grade.py 是唯一读真值的模块）
- randplant `feasible` 三态 `true` / `false` / `"unknown"` 原样透传（不 `bool()`）。
- `false_pass`：卡上 pass 而真值不满足，或标签 false、复核也不可达却 pass，或降幅给 pass → 硬红。
- `truth_label_suspect`：标签 false、卡上 pass 且真值满足、`feascheck.judge()` 复核找到达标参数 → 单独报，不算后端假达标。
- `undecided`：标签 unknown、复核仍 unknown → 单独计数，不进通过率分母。打印 unknown 个数 / 比例，> 10%（`FEAS_MAX_UNKNOWN`）出 `::warning::`。
- `tools/check_no_truth_leak.py`（make check）：后端 dzbench 与 tools/tunegate.py 读 plant.json / 真值键 / import randplant 就红。

## 原因码总表 `docs/dev/reason_codes.json`（#139）
- `{code: {zh, kind}}`，kind ∈ `round`（单轮无效，`iterate.round.invalid_reason`）/ `abort`（开始被拒）/ `stop`（`iterate.stopped.reason`）/ `diverge`（发散）。
- 由 `tools/gen_reason_codes.py` 从后端 `dzbench.agent.reason_codes` 生成；`make check` 跑 `--check`（过期即红），`tests/test_reason_codes.py` 校验后端每个原因码都在表里且 zh 非空。前端只读这个文件，不手抄。
- `kind` 取值：`round` / `abort` / `stop` / `diverge`，以及 `blocker`（连接阻塞，目前只有 `schema_conflict`）。

## schema 冲突 `schema_conflict`（r10 阻塞项）
板子心跳报的 schema 哈希在本机匹配到**多份内容不同**的 `link_schema.json`（例如两块板来回插，两次编译出同哈希、`wd_timeout_ms` 等不同的格式文件）时，侧车**一份都不用**（不取第一份，也不取最新的一份）：
- 推事件 `{type:"error", code:"schema_conflict", reason:"schema_conflict", message_zh, fix, fix_action:"clear_schema_cache"|"build", hash:"XXXXXXXX", board_uid:"16位小写hex"|null, files:[{path:绝对路径, kind:"cache"|"build"}…]}`（kind=cache 是侧车缓存 `$DZBENCH_HOME/schemas` 里的拷贝；build = 编译产物 / 工程 / 仓库里的文件。有 cache 份 → fix_action `clear_schema_cache`；只有 build 份，或编译产物与板子 'I' 回包的 wd_timeout_ms 不一致 → `build`（重编重烧））。`clear_schema_cache` 只删 kind=cache 的文件，编译产物、工程和仓库里的文件一律不删；`status.schema_conflict` 为同一对象（无冲突为 `null`），`status.schema_ok` 为 `false`，不推 `schema` 事件，遥测不解码。
- `progress` 出阻塞项 `{code/reason:"schema_conflict", hash, board_uid, files:[{path, kind}…], message_zh, fix_action:"clear_schema_cache"|"build", blocks:[sim, bringup, tune, score, seal]}`（`detail` 里同样有 hash/board_uid/files）。
- 修复 op `clear_schema_cache {hash}`（hash 为十六进制串或整数）：界面先出确认卡，确认后再调。只删本机缓存里这个哈希的格式文件（别的哈希不碰），返回 `{ok:true, removed:[绝对路径…]}`；随后推 `{type:"rehandshake", reason:"clear_schema_cache", hash}` 并清掉该哈希的绑定，下一帧心跳重新绑定（本机已无该哈希 → `schema_missing`，需重新编译/放回正确的那份）。动作 id `clear_schema_cache` 见 entrypoints.yaml。
- 依赖 schema 的写入一律拒绝，错误码 `schema_conflict`（同上 message_zh / fix_action）：写参数、读参数、阶跃、继电器、存 Flash、应用 DATA 帧。急停、停止阶跃、解除急停不受影响。
- 修法（`fix` 原文）：按当前这块板重新编译烧录固件后重新连接，或删掉不属于这块板的那份格式文件后重新连接。重新连接时侧车重新查找。
- 内容完全相同的多份（如 `build/` 与 `~/.dzbench/schemas/` 里的拷贝）不算冲突。导出记录遇到冲突同样报错，不挑一份。
- 哈希本身把 `wd_timeout_ms` 与板子身份算进去由固件侧（gen_link）负责，本节只管查找时不挑错。

## 板子身份 `board_uid` / `uid_supported`（换板识别，r10）
固件规格见 fw-wdhash 592ea43 的 `docs/dev/fw-handshake.md`（dzctl 0.17.0）。**心跳仍为 40 字节，侧车从不在心跳里读 board_uid**（0.16.0 曾追加到 48 B，已撤回；侧车对心跳只读前 40 B）。
- 连上后，收到第一帧**有效的 40 B 心跳**（确认对端是工作台固件）时，侧车发一次 `DATA id=0x7E {'I'}`。心跳急停位 bit10 置位（锁存或 'R' 后输出保持）或侧车 tx_locked 时先不发，等清零后再发：dzctl < 0.17.0 的 link_app 会把未知单字节命令当新指令、清掉 'R' 后的输出保持。2 s 超时从发出时算。
- 回包 `DATA id=0x7E len=23`（小端）：`'I'`, u8 `info_ver`, u32 `schema_hash`, u32 `wd_timeout_ms`, u8 `uid_supported`, u32 `board_uid_lo`, u32 `board_uid_hi`, u32 `fw_rev`（`board_ident.decode_info`）。
- **2 s 内没回包**（固件 < dzctl 0.17.0）→ `board_uid:null, uid_supported:false`，推 `{type:"board_id", reason:"fw_too_old", message_zh:"固件版本过旧，不支持板子识别"}`。
- **板子身份来源（契约）**：`status` 里的 `board_uid` / `uid_supported` / `proto_ver` 只来自侧车解码后的 'I' 握手回包，原样转发，并带 `board_ident_source:"handshake"`；status 里没有任何字段由心跳推算（心跳 offset 4 的芯片 ID 只供内部换口识别 / 急停锁存，不对外）。没回包时三者为 null / false。
- **fw_estop_unsafe（急停安全最低固件）**：规格 fw-unknown-cmd 854b6a1 `docs/dev/fw-handshake.md`。dzctl 0.18.0 起 'I' 回包 `info_ver=2`、27 B，偏移 23 加 `u32 proto_ver`（major<<16|minor<<8|patch，0.18.0 = `0x00001200`）；`decode_info` 两种布局都收，报 `proto_ver`（info_ver 1 为 null）。fw_rev 仍是 git 短哈希，不用来判版本。最低版本只在 `dzbench/board_ident.py` 的 `MIN_ESTOP_SAFE_PROTO = 0x00001200` 定义。`info_ver < 2`、proto_ver 低于最低、或 2 s 内没回包 → 推 `{type:"fw_estop_unsafe", safe:false, reason:"fw_estop_unsafe", message_zh:"此固件存在急停可被误清除的问题，请重新烧录", fix_action:"reflash", min_version:"0.18.0", version}`，并拒绝一切驱动执行器的操作（set_param / setpoint_set / step_start（含迭代、autotune、tune_autopilot）/ relay / set_run_mode / run_selftest / send_data / send_raw），error `code:"fw_estop_unsafe"`、`fix_action:"reflash"`。读参数、存 flash（W）、烧录、解除急停不拦。`sim:` / `replay:` 端口和没有心跳的非工作台设备不受此限（现有 host-sim 是 0.17）。**拦截开关 `board_ident.ENFORCE_FW_ESTOP` 现为 False**：integration 的 host-sim / e2e 伪串口板仍是 0.17，打开会拦掉 make test 的真仿真 e2e；integration 合入 fw-unknown-cmd 854b6a1 后改 True。检测、事件、status 现在就生效；拦截逻辑在 tests/test_fw_estop_unsafe.py 里打开开关照测。'I' 只在心跳 bit10 清零且未 tx_locked 时发——这条永久保留（旧固件板子会一直存在）。
- 回包 `uid_supported=0` → `board_uid:null`，`reason:"uid_unsupported"`，文案「此芯片暂不支持板子识别，换板检测不可用」。
- **交叉核对**：回包的 `schema_hash` 与已绑定的格式文件相同、但 `wd_timeout_ms` 不同（双方都非 0）→ 这份缓存不是这块板的，按 `schema_conflict` 处理（`files` 为那一份缓存文件的绝对路径，`fix_action:"clear_schema_cache"`）。
- `status.board_uid`：16 位小写十六进制字符串，或 `null`。`status.uid_supported`：bool。`status.board_id_known`：bool。`status.board_id_message_zh`：身份未知时为上面两句之一（过旧固件 / 芯片不支持），否则 `null`。
- `uid_supported:false`、`board_uid` 缺失或为 0 → `board_uid:null`，并推 `{type:"board_id", board_uid:null, uid_supported, board_id_known:false, message_zh}`。这种板子**永远不当作**缓存里的任何一块板（不按身份复用缓存）。
- 按板缓存：schema 绑定按 `(schema 哈希, board_uid)` 缓存；同哈希同内容的两块板不算冲突，同哈希不同内容仍是 `schema_conflict`（不挑最新）。
- 换板：与上次握手的 `board_uid` 不同，或任一方为 `null` → 推 `{type:"board_changed", from, to, uid_supported, message_zh}`，清掉上一块板的参数读数与 schema 绑定并重新查找。同一块板重启（同 `board_uid`）不推。
- 旧的 32 位心跳芯片 ID（latch / lastsession 用）不变。
- 现状：固件握手帧尚未推送；侧车按本规格实现，测试在真仿真板会话上把握手 dict 交给真解析器。

## 采纳未验证的参数（#141）
- `agent_action_decide` 采纳 `iterate_apply_best` / `autotune` 卡时，响应多 `verified: bool`、`unverified_reason`。卡（服务端保存的那份，不认客户端标记）verdict 为 `partial` 或任一 item `amp_reduced` → `verified:false, unverified_reason:"amp_reduced"`，不进已验证档 / 封箱清单；否则 `verified:true, unverified_reason:null`。
- 采纳 `kept_initial: true` 的卡（按服务端保存的卡判）→ 报错 `kept_initial`（「调参未能改善，已保留初值」，板上仍是初值），不记采纳、不进已验证档。

## 题型与非控制类快速开始（#85）、按 plant: 声明新建（#106）
- `quick_start` 的 `spec` 新增 `task_kind`（`control` / `measure` / `power` / `other`）和 `task_kind_reason`（命中的通用词，如「题面出现「频率、测量」→ 测量类」）。只按题面通用词判断，不认题号。
- 非控制类：`spec.sim = null`、`kind = null`；确认卡照常出（①–⑤ 预览），确认后**不连仿真、不调参**，`task_kind` 写进工程 `project.yaml`，推 `{type:"metrics_card", task_kind, task_kind_reason, items[]}`（每项 `measured:null, verdict:"unknown", verdict_zh:"待测量"`；阈值抽不出 `target:null`），结果多 `next`。
- 控制类但不是电机速度 / 位置环：报 `quick_kind`，fix 指向 `project_from_plant`。
- 新 op / Agent 工具 `project_from_plant {plant, name?}`（风险档 log）：`plant` 为对象或 YAML 文本，按 `schema/plant.schema.json` 校验。不合规 → `{ok:false, reason:"plant_invalid", errors[], message_zh, fix_action:"edit_declaration"}`，不建目录；合规 → `$DZBENCH_HOME/projects/<slug>/app.yaml`（缺 link/requires 由 plantmodel scaffold 补），设为当前项目，推并返回 `{type:"project_created", via:"plant", project, path, sim_board:"sim:<目录名>", message_zh}`。

## 读题不再要求刚性文件（#86）
- `flow_preview step:"req"` 除 `src` / `pdf_b64` 外接受 `file_b64 + filename`（PDF / txt / png / jpg 等，按后缀读；图片走 Tesseract OCR chi_sim+eng，没装 → `✗ … 把题目文字直接粘贴进来`）和 `text`（直接粘贴的题目文字）。都没给 → `no_src`「先拖入题目 PDF / 图片，或直接粘贴题目文字」。
- 没有「一、任务 / 二、要求」版式时按条款号（(1) ① 1.）切，再不行按句切。
- `items[]` 每项新增 `clause`（如「要求(B2)」）；抽不出阈值 / 单位的项 `metrics:[]` + `manual_entry:true` + `notes`（「没抽出阈值 / 单位：请对照原文手填指标」），不报错。范围两端单位只差 SI 前缀（10Hz~100kHz）时下限换到上限单位。

## 整定写参数、会话哈希、文案补齐（#126 #127 #128）与工具风险档
- #126：autotune 每步只走 `max_delta×(1−1e-6)`（再扣两端 float32 舍入）；板子 / 侧车按单步拒写时把这一步缩半重试（最多 8 次），不再抛错中断整轮。侧车 `set_param` 的单步比较加相对容差（`1e-6` + float32 舍入）。
- #127：`PARAM_ACK` 回来的 float32 存成最短且能还原同一 float32 的十进制（以前 `round(,6)` 会改掉小数值的位，本地参数哈希和板上 `step_result.params_hash` 对不上 → 连续 `hash_mismatch`）。`autotune` 结束把 `best.params` 写回板子并从板上重读参数；结果多 `applied_best: true`、`params_hash`（写回后本地算的 CRC32）。
- #128：`iterate_start` / `iterate_plan` 的 `step_too_large` 带与 #129 同一份字段 `reason, limit, limit_unit, limit_name, message_zh`，外加 `max_step, target, fix_action:"lower_step"`。`iterate.stopped` 本身带 `verdict` / `verdict_zh`：`reason:"pass"` → 「通过」（#121），没有可用一轮 → `unknown`。
- `agent_tool`、`agent_action` 事件新增 `tier`（auto/log/human/forbid，仿真按 SIM_RELAX 降档）、`tier_zh`、`name_zh`（`agent/risk.py NAME_ZH`，每个登记工具都有）。`autotune` = 「通用自动整定」，实机 human、仿真 log。

## 通用整定策略：按证据诊断、增益下限、收敛停、代价对齐题面、初值已达标（tuning strategy）
`autotune` 结果（Agent 工具 `autotune` 的返回 / 指标卡）新增字段：
- `causes: [{code, evidence, basis_zh, score}]`：未达标时每个候选原因（`saturation` / `delay` / `nonminimum_phase`）各自按证据打分，`evidence ∈ strong | medium | weak`，按证据强弱排序（不按固定先后）。证据来源：辨识模型阶跃响应（稳态增益 → 满输出能走到几成、起步反向幅度）+ 板上实测（控制量开始动 → 输出开始动的纯滞后 / 上升时间、顶限幅时间占比；振荡顶限幅不算饱和证据）。`category` = 第一个原因的 `code`；没有证据 = `unconfirmed`。前两个证据同档 → `verdict_zh` 写「未达标：可能是 A或B」。
- `stop_reason ∈ converged | budget_exhausted | at_limit` + `stop_reason_zh`：只有满足题面（且同参数复现两次都满足）才算 `converged`；参数全撞声明边界 = `at_limit`；否则一直搜到 `budget`（板上试参次数，`12 + 6 × 可调参数个数`，上限 48）用完 = `budget_exhausted`。一圈没变好就缩小步子继续，不提前宣布收敛。
- 板上代价 = 题面指标超标量（相对题面值）×10 + IAE 代价；题面没写指标退回 IAE 代价。
- 增益下限：`kp` / `ki` 不低于候选（初值、模型设计、SIMC）最大值的 2%、初值的 2%、声明 `min` 三者取大，搜索不会把增益压到 ≈0。
- 初值已满足题面（复现两次）：不改参数直接返回，`unchanged: true`、`tuned: false`、`unchanged_zh` / `pass_basis` =「初值已满足题面，本次没有改动参数」、`margins: {指标: 题面值 − 实测值}`（`items[].margin` 同），`verdict_zh` =「通过（初值已达标，未调参）」，不显示为整定成功；降幅测的照旧 `partial`。
- 绝不交付比初值差的参数：搜索结束后在 n / 2n / 4n 三个窗口各复测最好参数与初值（整定器自己的实测代价 `cost`，不读真值），任一窗口最好参数更差 → 退回初值：`kept_initial: true`、`unchanged: true`、`tuned: false`、`reason_zh` =「调参未能改善，已保留初值」（`verdict_zh` / `pass_basis` 以它开头），未达标时照常给 `causes`。结果总带 `cost_initial` / `cost_best`（2n 窗口的实测代价）与 `final_check: {n, windows:[{n, best_cost, initial_cost}], best_cost, initial_cost}`；`items[].margin` = 题面值 − 实测值（无穷 / 缺测为 null）。

tunegate（`tools/tunegate.py`，汇总在 `tools/tunegate_grade.py summarize()`）：
- 每行带 `stop=`、`unchanged`；汇总打印通过率（全部 / 只算可行）、unknown 比例、初值已达标个数、各原因类别 `{n, cause_ok}`。
- 硬门禁（退出码 1）：假达标 = 0，且可行对象上「报收敛却未达标」（`early_stop_not_pass`）= 0。
- 判卷：不可行对象未达标时卡上 `category` 必须等于真值原因（不再放过 `unconfirmed`）；`unchanged` 且真值满足题面 → 只按题面判，不要求“比初值好”。
- `make check` 的 `check_no_truth_leak`：真值键（feasible / feasibility / reason_category / infeasible_reason / witness）和 plant.json 只许判卷模块、出题方（randplant*、tunegate_plant、feascheck）和测试引用；后端、tools/tunegate.py 及 tools/ 其余脚本里任何字符串常量、属性、变量名、关键字参数、取键都算泄漏。

## 对象无响应硬上限（plant_unresponsive）
- 阶跃无响应（`no_rise` / `settle_zero`）时 iterate 把阶跃时长翻倍重做，翻倍有硬上限：声明 `link.step[ch].max_step_dur_ms`（毫秒）；没声明用默认 `NO_RESPONSE_DUR_CAP_MS = 12000`（再夹板上上限 30000）。
- 到上限仍无响应：停阶跃（step_stop）、设定值放回起点，`iterate.stopped` 的 `reason = "plant_unresponsive"`，`best = null`，卡片结论 `unknown`（不给结论）。reason_codes.json 里带 `message_zh`「对象无响应」和 `causes`（没上电 / 接线 / 方向 / 执行器饱和）。
- 注：`max_step_dur_ms` 要经 tools/gen_link.py 透传进 link_schema.json 才生效（tools/ 归嵌入式开发-2）；未透传前一律按默认值。
