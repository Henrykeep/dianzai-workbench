# 侧车 → 界面事件约定

## 急停 `type: "estop"`

一条统一事件，按 `state` 区分阶段；`source` 是来源（`ui` / `board` / `agent` …），不再有 `src`、`sent`、`message`。
代码里的权威定义：`Session.ESTOP_EVENT_KEYS`（`app/sidecar/dzbench/session.py`），测试断言键集合与之精确一致。

| state | 必有键 | 可选键 | 说明 |
|---|---|---|---|
| `requested` | `type` `seq` `state` `source` `t` `ok` `message_zh` | — | 上位机已发出急停帧；`ok=false` = 没写出去（断电/拔电池） |
| `latched` | `type` `seq` `state` `source` `t` | `cause` `message_zh` `latency_ms` | 板子心跳确认锁存；`latency_ms` 是 requested→latched 的诊断值，仅在本次由上位机发起时给出 |
| `cleared` | `type` `seq` `state` `source` `t` | `message_zh` | 人工 R 解除 |

- `t`：毫秒 Unix 时间；`seq`：单调递增。
- 没连板子 / 回放时的急停回包不是状态事件（无 `state`）：键集合固定为 `type` `ok` `reason` `message_zh`（代码 `Session.ESTOP_REPLY_KEYS`），`ok=false`，`reason` 为 `no_board`（没连板子，只弹提示、不进告警条）或 `replay`（回放中）。不再有 `sent` / `message` / `nolink` / `src`。
- 前端对旧格式（`sent` / `message`）与新格式都兼容。

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
