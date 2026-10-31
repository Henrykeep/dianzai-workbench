# 自动迭代协议（#38）

状态：**定稿**（2026-10-31，已与嵌入式开发-2 对齐字段）。实现：agent/service.py `tune_autopilot` 扩展到实机、`agent/loop.py` 主线。仿真板与实机共用同一份固件实现，本地服务不为仿真另写一套。
验收（问题池 #38）：`agent_mainline.py` 人工介入 ≤ 2 次，300 s 内达标（单次迭代预算 180 s）。

## 1. 行为

- **默认自动迭代**：Agent 进入调参后自己连续跑“改参 → 阶跃 → 判定”，直到 **达标** 或 **停止条件**（第 5 节）才把控制交回给人。中途不再问“你指定一项，我出卡”。
- **从板上当前参数出发**：每次迭代以板子当前参数为起点（不沿用上一次运行或别的工程的初值）。确认卡显示这组起始值及其 `params_hash`；step_result `iter = 0` 记录起始参数（基线一轮）。
- **一次确认**：方案卡（改哪几个参数、方向、轮数上限、预算）和参数卡（首轮具体数值）合并成 **一张批量确认卡**。卡上逐个参数列出：允许范围 [min, max]、单步最大变化 `max_delta`、起始值；以及总预算（时间 + 轮数）。人点一次“开始自动迭代”，之后每轮在第 4 节的安全限幅内自动写参数，不再逐轮弹卡。
  - 仿真：沿用现有 SIM 档，确认卡可以省略（`tune_autopilot` 已是自动连跑）。
  - 实机：必须有这张卡；卡上写明限幅和停止条件；任何时刻急停、点“停止迭代”都立即生效。
- **超出批准范围要重新确认**：要改卡上没有的参数、或超出卡上范围，就停下并出一张新卡（计一次介入）。

## 2. 每轮记录（本地服务 → 界面 / Agent / 迭代日志）

| 字段 | 含义 |
|---|---|
| `iter` | 第几轮：0 = 起始参数基线，之后从 1 开始；aborted / 无效轮不占号 |
| `params` | 本轮参数 `{name: value}` 和 `params_hash`（与固件回报核对） |
| `ss_err_pct` | 稳态误差 % |
| `overshoot_pct` | 超调 % |
| `settle_ms` | 调节时间 ms（没进带 = null） |
| `rise_ms` | 上升时间 ms |
| `metric_mode` | `rel`（百分比口径）或 `abs`（阶跃幅度小时，改用 board.yaml 的 `abs_tol` 绝对容差判定） |
| `pass` | 每项是否达标：`{ss_err, overshoot, settle, rise}` 各 true/false，外加总判 `all` |
| `source` | `firmware`（板上 step_result）或 `sidecar`（老固件，本地按同一口径从遥测算） |
| `valid` / `why_invalid` | 无效轮的原因：`aborted` / `too_few_samples` / `hash_mismatch` |

达标阈值默认用护栏 `GOOD`：超调 ≤ 10%，|稳态误差| ≤ 2%，已进 2% 带；连续 2 轮达标才算“达标”。评分项有自己的指标（requirements.yaml）时以评分项为准。

## 3. 固件回报字段（给嵌入式开发-2）

### 3.1 `step_result`（每轮阶跃结束后固件发一帧）

| 字段 | 类型 | 说明 |
|---|---|---|
| `proto` | u8 | 本结构版本，从 1 开始 |
| `iter` | u16 | 本地服务下发的轮号，原样回带；0 = 起始参数基线 |
| `params_hash` | u32 | CRC32，按 board.yaml 参数表顺序，对本轮生效的参数值计算（算法见 3.4） |
| `t0_ms` | u32 | 阶跃起点的板上时间 |
| `metric_mode` | u8 | 0 = rel，1 = abs（阶跃幅度小于 board.yaml `abs_tol` 对应阈值时用绝对容差） |
| `n` | u16 | 参与计算的样本数；**n 过少（< 本地阈值，默认 20）这一轮视为无效** |
| `setpoint` | f32 | 阶跃目标值 |
| `overshoot_pct` | f32 | 超调 % |
| `rise_ms` | u32 | 10% → 90% 的时间 |
| `settle_ms` | u32 | 误差进入并保持在 ±2% 带内的时刻（相对 t0）；没进带填 0xFFFFFFFF |
| `ss_err_pct` | f32 | 最后 20% 窗口的平均绝对误差 ÷ \|setpoint\| × 100 |
| `u_sat_ratio` | f32 | 输出饱和样本占比 0~1 |
| `peak_abs_err` | f32 | 最大绝对误差 |
| `aborted` | u8 | 1 = 本轮被打断（急停、超限、超时） |
| `abort_cause` | u8 | 打断原因码（沿用急停原因码表，另加“超时”） |

**aborted 的一轮作废**：不计入迭代、不更新最好成绩、不参与方向判断。

### 3.2 `param_reject{name, reason}`

固件拒绝写入（越界、类型不对、当前状态不允许）时回报。`reason` 用短码：`range`（越界）/ `type`（类型不对）/ `state`（当前状态不允许）/ `step`（单次变化超过 board.yaml 的 `max_delta`）。

### 3.3 心跳 busy 位

- 迭代进行中置 1；**急停期间必须清零**（急停优先）。
- 位置：**bit17，`DZCTL_HB_ITER_BUSY`**（已确认；bit14 是 `DZCTL_HB_STANDALONE`）。
- dzctl 0.15.0 起 **bit18 `DZCTL_HB_SENSOR_SAT`**：被控量在量程边界（传感器饱和 / 仿真对象钳位），实时值、不锁存。上位机据此把这段数据标“到量程、不可信”，不当作对象响应。
- 同时作为 #44 `status.agent_busy` 的板上依据。

### 3.4 指标口径（仿真与实机同一套）

- `ss_err_pct`：最后 20% 窗口的平均 |误差| ÷ |setpoint|。
- `settle_ms`：误差进入并 **保持** 在 ±2% 带内的时间。
- `rise_ms`：从 10% 到 90% 的时间。
- 百分比的分母都是 |setpoint|；setpoint 为 0 时改用阶跃幅度 |setpoint − y0|。
- `metric_mode = abs`：阶跃幅度小（相对口径不可靠）时，±2% 带和稳态误差改用 board.yaml 的 `abs_tol`（绝对量，单位同 y）；step_result 与本地记录都标出所用口径。
- `params_hash`：CRC32（IEEE 802.3，与 zlib.crc32 相同），输入为按 board.yaml 参数表顺序排列的各参数值，按小端拼接（f32 按 IEEE754，整型按其声明宽度）。本地服务用同一算法核对，不一致 → 本轮无效（`hash_mismatch`）。
- 本地服务对老固件（不发 step_result）按同一口径从遥测计算，结果标 `source: sidecar`。

## 4. 安全限幅

- 写参数前，本地服务按 board.yaml 参数表校验类型与范围（与 #40 共用同一段校验）：NaN / Inf / 越界 / 类型不对直接拒绝，返回 `invalid_param`，不钳位。
- 单步变化幅度：不超过 board.yaml 的 `max_delta`（固件超过时回 param_reject reason=step）；同时沿用护栏档位。实机 HW 档：新值在当前值的 ×0.7~×1.5 之内，且单步 ≤ 量程 × 10%；当前为 0 时首步 ≤ 量程 × 2%。仿真 SIM 档更宽。
- 每轮只改 1~2 个参数。
- 输出饱和：`u_sat_ratio` > 0.5 的一轮不往“更激进”的方向走。
- 收到 `param_reject`：这一轮停下，**换方向**，不重试同一个值。
- 板上 dzctl 仍会再限幅一次（双保险）；固件越界一律回报 param_reject，不悄悄钳位。

## 5. 停止条件（任一满足即停，交回给人）

1. 达标：连续 2 轮全部达标。
2. 预算用完：总时长 180 s，或轮数到上限（实机 8 轮、仿真 20 轮），先到为准。
3. 急停（任何来源）或人点“停止迭代”：立即停，不再写参数，不自动恢复。
4. 连续 3 轮无效（aborted / 样本太少 / hash 不一致）。
5. 连续 3 轮没有改进（得分不降）。
6. 不稳定：振荡 > 2 次或超调 > 40%。实机先回到最好一轮的参数（要人确认），仿真自动回滚。
7. 所有方向都被 param_reject 或限幅挡住。

停下时给出：最好一轮的参数和指标、停止原因、建议的下一步（一句话）。

## 6. 事件

已定稿，以 `docs/dev/events.md`「自动迭代 `iterate.*`」为准（入口 op、事件顺序、轮数上限 N = `iterate.started.limits.rounds`、结束时的“采用最好参数”卡）。

## 7. 本地服务实现（dzctl 0.13.0 实帧）

- 帧编解码直接用 `tools/dzstep.py`（`dzbench/stepproto.py` 引入），与固件 `dzstep.c` 同口径：DATA 0x7B 开始（12 B：ch, 0, iter, target, dur_ms 200–30000；空载荷 = 停止，结果 aborted、cause 0x80）、应答 4 B（0 已开始 / 1 参数错 / 2 急停中 / 3 忙 / 4 不支持 / 5 脱机）、step_result 56 B；DATA 0x7A param_reject（1 range / 2 type / 3 state / 4 step）；PARAM_ACK status 5 = 被拒。
- 校验以 `link_schema.json`（app.yaml `link.params`）为准：类型、[min, max]、单步 `max_delta`（缺省 = max − min）；本地先拒（`invalid_param`，`reject: step`），从不钳位。急停中、心跳 bit17 置位时不写参数（`param_locked`）。
- **参数角色 `role`**（可选，app.yaml `link.params[].role`）：`P` / `I` / `D` / `FF`（前馈）/ `LIM`（限幅）/ `other`。`tools/gen_link.py` 校验（其他值中文报错、退出 1），写进 `link_schema.json` 的 `params[].role`（没写 = `null`，上位机不按参数名猜；`LIM` 不参与整定）。只给上位机，**不进 schema 哈希**，改角色不用重烧。`tools/randplant.py` 生成的 app.yaml 每个参数都带 role。
- `params_hash` 取 step_result 里的 CRC32；本地按参数表顺序算同一个值核对，不一致记 `hash_mismatch`。心跳尾部的 params_hash 仍是 FNV（0.12），两者不混用。
- `metric_mode = abs` 时 `overshoot_pct` / `ss_err_pct` 是物理单位（记录里 `unit: "abs"`），按 `link.step.abs_tol` 判稳态误差；超调只记录不判。
- 代码：`dzbench/agent/iterate.py`（`Iterator` 引擎 + `SessionIO`）、`AgentService.iterate_start / iterate_cancel`（工具同名；实机 human 级出批量卡，仿真 log 级）、`Session.step_start / step_wait / step_stop / iter_busy`。测试：`tests/test_iterate.py`（mock step_result + car_2wd 仿真真固件）。
- 事件：`iterate.started {plan, start, start_hash, limits}`、`iterate.round`（第 2 节字段 + `local_hash` `unit` `band` `changed`）、`iterate.param_reject {name, value, reason}`、`iterate.stopped {reason, message_zh, rounds, best{iter, params, params_hash, metrics, pass, gaps}, next_zh}`；`reason` ∈ pass / budget_time / budget_rounds / estop / stopped / invalid / no_improve / unstable / blocked / error。
