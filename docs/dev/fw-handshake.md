# 固件握手 / 心跳字段（固件侧，嵌入式开发-2 维护）

给侧车对接用。events.md 归后端，这里只写固件发什么；侧车怎么转给界面由后端写进 events.md。

## schema 哈希（`schema_hash`，心跳第 1 个 u32 / `link_schema.json` 的 `hash`）

- 由 `tools/gen_link.py` 计算：遥测字段、参数表（类型/限幅/max_delta）、`step` 通道配置，**以及 `wd_timeout_ms`**（link.yaml `watchdog_ms`，默认 1500）。
- **变化（fw-wdhash）：`wd_timeout_ms` 现在在哈希里。** 两份只差 `watchdog_ms` 的声明，哈希不同。原因：看门狗阈值是烧进固件的行为（`LINK_WD_TIMEOUT_MS`），旧做法下侧车按哈希找 schema 时可能拿到另一块板的旧文件，`threshold_ms` 报错（后端 b89f6ec 定位的 test_e2e_robust 偶发失败）。
- 仍不进哈希（只给上位机看，改了不用重烧）：`default`、`desc`、`role`、`protect`、`cal`、`limits`、`relay`、`accept`、`loops`、`protect_fixed`。
- 影响：所有带 link 的应用哈希都变了，旧的 `link_schema.json` 缓存与新固件对不上，需要重新生成（`make` 会自动生成）。

## 一次性握手信息 `'I'`（dzctl 0.17.0 / PAL 1.9.0）

侧车连上后（收到第一帧心跳即可）发一次：`DATA id=0x7E(DZCTL_ID_CMD) len=1 {'I'}`；板回 `DATA id=0x7E len=23`（小端）：

| 偏移 | 类型 | 字段 | 说明 |
|---|---|---|---|
| 0 | u8 | `'I'` | 回包标记（0x49） |
| 1 | u8 | `info_ver` | 1；以后加字段只往后追加并升它 |
| 2 | u32 | `schema_hash` | 与心跳第 1 个 u32 相同 |
| 6 | u32 | `wd_timeout_ms` | 固件实际烧进去的链路看门狗（`LINK_WD_TIMEOUT_MS`）；0 = 应用没有 link 看门狗 |
| 10 | u8 | `uid_supported` | 1 = 读到了 MCU 唯一 ID；0 = 本芯片族/端口读不到（`pal_read_uid` 返回 `DZ_ENOTSUP`，如 MSPM0 预量产片、没实现的端口） |
| 11 | u32 | `board_uid_lo` | MCU 唯一 ID 的 64 位 FNV-1a，低 32 位 |
| 15 | u32 | `board_uid_hi` | 高 32 位；`uid_supported=0` 时 lo/hi 恒 0 |
| 19 | u32 | `fw_rev` | 同心跳第 3 个 u32 |

侧车建议报给界面：`board_uid: "0123456789abcdef"`（16 位小写十六进制）+ `uid_supported: true/false`。
- `uid_supported=false` → 界面明确写「这块板读不到芯片唯一 ID，无法自动判断是否换板」，不要静默 null。
- 2 s 内没收到 `'I'` 回包（旧固件 < dzctl 0.17.0）→ `board_uid: null, uid_supported: null`，文案「固件版本过旧，不支持板子识别」。
- 两块板同一份固件：`schema_hash` 相同、`board_uid` 不同。**不在 schema 哈希里**（运行时值）。只换电机/传感器时 UID 不变，靠每次上电的标定偏差检查（另做）。
- 报的是哈希，不是原始 UID。旧的 32 位 `board_uid`（心跳第 2 个 u32）保持不变，latch / lastsession 继续可用。
- 所有带 link 的应用都经 `apps/include/link_step.h` 的 `link_step_dispatch()` 回 `'I'`（link_app.h 应用和 car_2wd）。
- host-sim：`DZ_SIM_UID=<字符串>` 模拟不同的板（未设时固定 `"dz-host-sim"`）；`DZ_SIM_UID_UNSUPPORTED=1` 模拟读不到 UID。测试：`tools/test_board_uid.py`。

## 心跳（不变：负载 40 字节）

上一版（fw-wdhash 2216f76，dzctl 0.16.0）曾把 board_uid 追加进心跳（48 B），**已撤回**（0.17.0）：板 ID 是一次性信息，不该每 500 ms 重复发。心跳布局恢复为 dzctl 0.15 的 40 B。

实测（host-sim car_2wd / motor_pos，tools/test_board_uid.py）：
- 线上一帧 = 40 B 负载 + 9 B 帧开销（2 SOF + VER + KIND + ID + SEQ + LEN + 2 CRC，无转义）= **49 B**。
- 频率 **2.00 Hz**（每 500 ms；急停上升/下降沿各加发一帧）。
- 8N1 下 49 × 10 × 2 ≈ **980 bit/s** → **9600 baud 占 10.2%**，**115200 baud 占 0.85%**。（若按撤回前的 48 B 负载算是 57 B，9600 下 11.9%。）
