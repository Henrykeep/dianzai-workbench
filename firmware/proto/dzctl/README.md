# 上位机控制服务 dzctl  `v0.4.0`

dzframe/1 之上的三件事：**参数读写（板端限幅、回传生效值）**、**急停**、**带 schema 哈希的心跳**。桌面工作台（app/）和 Agent 都只通过它改板上参数。

| 方向 | 帧 | 负载 |
|---|---|---|
| PC→板 | PARAM_SET id=序号 | 空 = 读；f32 = 写 |
| 板→PC | PARAM_ACK id=序号 | u8 status（0 OK / 1 已限幅 / 2 序号错 / 3 长度错 / 4 NaN·Inf 拒绝）, f32 生效值 |
| PC→板 | DATA id=0x7F | 空：急停（应用锁存） |
| PC→板 | DATA id=0x7E | u8 命令字符（应用自定义） |
| PC↔板 | DATA id=0x7D（0.6.0） | 黑匣子：上位机 len=0 请求导出；板子每条记录回一帧 u32 t_ms, u16 code, u16 arg, f32 a, f32 b（码见 framework/blackbox `BB_EV_*`） |
| 板→PC | HEARTBEAT | u32 schema_hash，上位机据此找 `link_schema.json`；0.3.0 起再跟 u32 board_uid（芯片 UID 折成 32 位，0 = 未知；F1/F4 读 UID，MSPM0 读 FACTORYREGION TRACEID/USERID，上板【未测】）。旧上位机只读前 4 字节，兼容；0.4.0 起第 3 个 u32 fw_rev = git 短哈希（低 28 位）| bit31 未提交改动，0 = 未知（Keil/CCS 没传 `DZ_FW_REV`）；0.5.0 起第 4 个 u32 status：低 8 位复位原因（pal_reset_cause_t，0 = 未知/应用没填），bit8 SAFE_BOOT（异常复位后进安全态）、bit9 STALL、bit10 ESTOP |

参数表、遥测打包函数和 `link_schema.json` 由 `tools/gen_link.py` 从 yaml 的 `link:` 段生成，C 与上位机同源。

**设定值通道的 `hold`**（`link_schema.json` 的遥测字段，进 schema 哈希）：凡有 `ref_for` 或显式写 `hold` 的遥测字段都带 `hold`，说明上位机不再发命令时固件怎么处理这个目标：
- `latched`：保持到上位机改它为止（motor_pos、pendulum_rot、pan_tilt、line_car、2026X_follow——link_app 的 `L.sp[]` / 参数）；
- `timeout`：超过 `cmd_timeout_ms` 没有新命令就归零（断线停车，car_2wd）。
- yaml 不写时默认 `timeout`（保守），但 `tools/test_link_hold.py` 要求每个设定值通道显式写，并按应用源码有无 `cmd_timeout` 核对。
- 两种都会在急停锁存时立即清零（见上文），`hold` 只描述正常运行时的行为。


## 标准命令（全量回读 / 版本 / 黑匣子）
- **参数全量回读**：上位机按 schema 逐个发空 PARAM_SET（板端回生效值，不是上位机记的值）。侧车 `Session.export_readback()` / WebSocket op `params_readback` 写 `params.txt`（界面按钮【未做】）（带 schema_hash、fw_rev、board_uid、时间），
  `python3 tools/params_diff.py last_good.txt now.txt` 对比两次回读（docs/verify 的 params_before/params.txt 就是它）。
- **固件版本**：心跳里的 fw_rev；make 编译自动注入，`make vars` 可见 `FW_REV`。
- **黑匣子导出**：约定单字节命令 `'F'` → 应用调 `bb_dump`（firmware/framework/blackbox），按行发 `BB,...`（参考 DS 的 F/P/H 命令）。

## 验证状态
- **已实测（PC）**：`dzctl_selftest()`、tests/host 单元测试、host-sim 与桌面 sidecar 的端到端测试（app/sidecar/tests）。
- **未验证**：真实串口上的参数写入时序（写参数与控制中断并发：f32 对齐写在 Cortex-M 上是原子的，非对齐/多字段组合不保证）。

## 参考来源
- MAVLink 参数协议（mavlink.io/en/services/parameter.html）：SET 后回传实际值、上位机以回传为准。
- PX4 参数元数据（min/max/unit 与代码同源生成）的思路。

## 0.8.0

- 心跳尾部追加 `u32 cause, u32 t_ms, f32 value`（len 16 → 28，旧上位机按长度读，不受影响）：板子**为什么**急停。
  `dzctl_estop_note(cause, t, v)` 只记第一个原因（之后的连锁急停不覆盖），`dzctl_estop_clear()` 在人发 `R` 时清。
  原因：1 手动 2 心跳超时（value=ms）3 堵转 4 欠压（V）5 过流（A）6 限位/超量程 7 自检失败（项数）8 异常复位安全态（复位原因）9 传感器故障。
  接入：apps/include/link_app.h（所有 link_app 板子）、car_2wd、examples/2026H_ball/io。中文说明在侧车 `ESTOP_CAUSES`。
## 0.10.0

- 运行模式：心跳 status bit14 `DZCTL_HB_STANDALONE`（1 脱机 / 0 联机），bit15 `DZCTL_HB_SA_RUNNING`（脱机已启动）。
- 'M' 切模式：`{'M', mode, DZCTL_MODE_MAGIC=0xA5}`，板回 `{'M', rc}`（0 已切并写 flash，1 没停稳，2 无 flash，3 写失败，4 缺确认字节）。
  模式只由人切换（界面确认卡 / 板上长按），固件从不自动切；模式单独存 flash，与参数无关。
## 0.11.0

- 心跳尾部再追加 `u32 selftest_mask, u32 selftest_t_ms, u32 params_hash`（len 28 → 40）：
  自检失败项 bit (code−1)（1 子系统 2 参数 3 flash 4 传感器 5 电源），t_ms = 0 表示应用没报自检；
  params_hash = RAM 参数 FNV-1a 32；status bit16 `DZCTL_HB_PARAMS_DIRTY` = RAM 与 flash 那份不一致。

## 0.9.0

- 脱机运行：心跳 status bit11 = 上电自检失败（同时以原因 7 急停锁存），bit12-13 = 上电参数来源（0 flash / 1 没存过→默认 / 2 损坏或结构变了→默认 / 3 无 flash）。
  `'W'` 存参数后板回 `DATA 0x7E len=2 {'W', 结果}`（0 已写入 1 没停稳拒写 2 无 flash 3 写失败）。侧车 `save_params()`（WS op `save_params`）。示例：apps/car_2wd。

## 0.12.0 通用运行时（每个应用默认都有）

自检、运行模式、存参、重跑自检从 car_2wd 挪进通用运行时 `apps/include/dz_runtime.h`（`link_app.h` 已集成；car_2wd、2026H io 直接用）。
应用只注册自己的自检项：`dzctl_selftest_register(code, fn)`（fn 返回 true = 通过；code 1..32，同 (code,fn) 重复注册只算一次，最多 `DZCTL_ST_MAX`=8 项）。
通用项：参数越界（code 2）由运行时自己查。

命令字节（上位机 → 板，DATA id=0x7E）：

| 命令 | 字节 | 板回（DATA 0x7E） | 说明 |
|---|---|---|---|
| 存参 | `57`（'W'） | `57 rc`：0 已写 1 没停稳 2 无 flash 3 写失败 | 只在停稳时写 |
| 切模式 | `4D mode A5`（'M'，0 联机 1 脱机） | `4D rc`：0 已切 1 没停稳 2 无 flash 3 写失败 4 确认字节/模式非法 | 只有 3 字节的 'M' 归运行时；2 字节 'M' 留给应用/仿真钩子 |
| 重跑自检 | `48`（'H'） | `48 m0 m1 m2 m3`：u32 LE 失败 mask（bit = code−1） | 同时刷新心跳 selftest_mask / t_ms；不用 'S'（2026H 的 'S' 是停止） |

心跳 status（同 0.10/0.11）：bit14 脱机、bit15 脱机已启动、bit 8..9 参数来源、PARAMS_DIRTY、SELFTEST_FAIL；尾部 selftest_mask / t / params_hash。
上电自检不过 → 急停锁存（原因 SELFTEST），'R' 解除。脱机模式：不要求心跳；link_app 应用不收上位机设定值。侧车：`Session.run_selftest()`（WS op `run_selftest`）。

## 0.13.0 阶跃实验 step_result / 参数校验 param_reject / 心跳 bit17（#38）

兼容性：只新增。0.12 上位机不发 0x7B 就看不到差别；参数写入新增 PARAM_ACK status 5（被拒，回读值 = 旧值），旧上位机会把它当未知状态。
`dzctl_handle()` 仍按 0.12 夹到范围（库内兼容）；应用改用 `dzctl_handle_checked()`：**不夹**，越界一律拒。

### 参数校验（编译进固件，来自 app.yaml link.params）

| reason | 值 | 条件 |
|---|---|---|
| range | 1 | 不在 [min, max] |
| type | 2 | NaN / ±Inf；整型参数给了小数 |
| state | 3 | 急停锁存中，或阶跃实验进行中（参数锁定） |
| step | 4 | \|新 − 旧\| > max_delta（app.yaml `max_delta`，缺省 = max − min 即不限制） |

被拒时板回两帧：PARAM_ACK（status 5，f32 = 当前值）+ DATA id=0x7A param_reject：

| 偏移 | 类型 | 字段 |
|---|---|---|
| 0 | u8 | 参数下标 |
| 1 | u8 | reason（上表） |
| 2 | f32 | 请求值 |
| 6 | f32 | 当前值 |
| 10 | char[≤16] | 参数名（ASCII，不补 0，长度 = len − 10） |

### 阶跃实验（DATA id=0x7B）

上位机 → 板 开始（12 B）：u8 ch、u8 0、u16 iter、f32 target、u32 dur_ms（200..30000）；空载荷 = 停止（中止，cause 0x80）。
板 → 上位机 应答（4 B）：u8 status（0 已开始 1 参数错 2 急停中 3 忙 4 不支持 5 脱机）、u8 ch、u16 iter。
开始即把 `sp[ch] = target`；实验中按遥测节拍取样（t − t0 ≤ dur），到时发 step_result（56 B，LE）：

| 偏移 | 类型 | 字段 | 说明 |
|---|---|---|---|
| 0 | u8 | proto | = 1 |
| 1 | u8 | metric_mode | 0 rel，1 abs |
| 2 | u8 | aborted | 1 = 中止 |
| 3 | u8 | abort_cause | 1..9 = 急停原因；0x80 = 上位机停止 / 实验中又发设定值 |
| 4 | u16 | iter | 上位机给的轮号（0 = 起始参数基线） |
| 6 | u16 | n | 样本数 |
| 8 | u32 | params_hash | CRC32/IEEE（= zlib.crc32）over 参数表顺序的 f32 LE；`tools/dzstep.py params_hash` |
| 12 | u32 | t0_ms | 开始时刻（板时钟） |
| 16 | f32 | setpoint | |
| 20 | f32 | initial | 第一个样本 y0 |
| 24 | f32 | overshoot | rel：(max(y−y0)/A − 1)·100 %，≥0；abs：max\|e\|（物理单位） |
| 28 | u32 | rise_ms | 10%→90%；abs 口径或没到 = 0xFFFFFFFF |
| 32 | u32 | settle_ms | 最后一次出带后第一个进带样本 − t0；带 = rel 2%\|A\| / abs abs_tol；末样本在带外 = 0xFFFFFFFF |
| 36 | f32 | ss_err | 末 20% 窗口 mean\|e\|；rel ÷\|A\|·100 %，abs 物理单位 |
| 40 | f32 | u_sat_ratio | \|u\| ≥ 0.99·u_max 的样本占比；没有 u 通道 = −1 |
| 44 | f32 | peak_abs_err | max\|e\| |
| 48 | f32 | band | 所用调节带（物理单位） |
| 52 | u8 | ch | |
| 53 | u8 | 保留 | 0 |
| 54 | u16 | 保留 | 0 |

A = setpoint − initial（分母一律用阶跃幅度，不用 \|setpoint\|）。\|A\| < max(0.01·range, abs_tol) 时用 abs 口径（如已在 0 附近再给 sp=0）。
range / abs_tol / y / u / u_max 来自 app.yaml `link.step`。心跳 status **bit17 DZCTL_HB_ITER_BUSY**：实验中 = 1；结果发出即清；急停锁存当拍强制 0（aborted 结果先于急停沿心跳发出）。
注意：心跳尾部 params_hash 仍是 0.12 的 FNV（不变），step_result 里的是 CRC32。
