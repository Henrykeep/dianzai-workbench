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
- 没连板子 / 回放时的急停回包不是状态事件（无 `state`），仍是 `{type, sent:false, …}` 提示，只弹 toast、不进告警条。
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
- `contest_mode` 时另推一条 `{type: "agent_error", code: "contest_mode", message, message_zh, fix_action: "enable_cloud", retryable: false}`。
- 开关：暂读 `~/.dzbench/config.json` 的 `contest_mode` / `cloud_enabled`（TODO：设置入口未做）。
