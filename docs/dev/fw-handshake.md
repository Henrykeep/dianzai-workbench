# 固件握手 / 心跳字段（固件侧，嵌入式开发-2 维护）

给侧车对接用。events.md 归后端，这里只写固件发什么；侧车怎么转给界面由后端写进 events.md。

## schema 哈希（`schema_hash`，心跳第 1 个 u32 / `link_schema.json` 的 `hash`）

- 由 `tools/gen_link.py` 计算：遥测字段、参数表（类型/限幅/max_delta）、`step` 通道配置，**以及 `wd_timeout_ms`**（link.yaml `watchdog_ms`，默认 1500）。
- **变化（fw-wdhash）：`wd_timeout_ms` 现在在哈希里。** 两份只差 `watchdog_ms` 的声明，哈希不同。原因：看门狗阈值是烧进固件的行为（`LINK_WD_TIMEOUT_MS`），旧做法下侧车按哈希找 schema 时可能拿到另一块板的旧文件，`threshold_ms` 报错（后端 b89f6ec 定位的 test_e2e_robust 偶发失败）。
- 仍不进哈希（只给上位机看，改了不用重烧）：`default`、`desc`、`role`、`protect`、`cal`、`limits`、`relay`、`accept`、`loops`、`protect_fixed`。
- 影响：所有带 link 的应用哈希都变了，旧的 `link_schema.json` 缓存与新固件对不上，需要重新生成（`make` 会自动生成）。

## 板子身份 `board_uid`（换板指纹，dzctl 0.16.0 / PAL 1.9.0）

- 心跳末尾追加 `u32 lo, u32 hi`（偏移 40、44，心跳 len 48）= MCU 出厂唯一 ID 的 **64 位 FNV-1a**（`pal_read_uid()` → `pal_uid64()`）。
- 侧车建议报给界面：`board_uid: "0123456789abcdef"`（16 位小写十六进制，`(hi<<32)|lo`）；值为 0 或心跳 len < 48（旧固件）→ `null`（未知），不猜。
- **不在 schema 哈希里**：同一份固件烧到两块板，`schema_hash` 相同、`board_uid` 不同。换板判定看它；只换电机/传感器时 UID 不变，靠每次上电的标定偏差检查（另做）。
- 报的是哈希，不是原始 UID。
- 旧的 32 位 `board_uid`（心跳第 2 个 u32，0.3.0 起）保持不变，latch / lastsession 继续可用。
- host-sim：`DZ_SIM_UID=<任意字符串>` 模拟不同的板；未设时固定为 `"dz-host-sim"` 的哈希。测试：`tools/test_board_uid.py`。
