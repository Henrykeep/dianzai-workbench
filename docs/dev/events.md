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
