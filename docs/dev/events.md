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
