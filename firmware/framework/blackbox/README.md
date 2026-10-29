# blackbox — 黑匣子（RAM 环形日志 + 可选掉电冻结）  `v1.0.0`

出事时记事件（`bb_log`，O(1)），要留证据时 `bb_freeze` 写进存储，复位后 `bb_load_frozen` 读回、`bb_dump` 按行导出（`BB,t_ms,code,arg,a,b`）。
存储是回调（片内 flash 末页 / SPI flash / 模拟 EEPROM），本模块不含硬件代码，属 framework 层。

**铁律：存储失败永远不能挡住启动和控制。** `bb_init` 不碰存储；每次 freeze/load 的存储操作次数有上限，失败只计数返回错误码；
连续失败 3 次自动停用存储，RAM 日志照常；冻结区固定大小、先擦后写，不会“写满”，放不下只存最新的。

- 接口见 `blackbox.h`；自检 `bb_selftest()`；主机测试 tests/host/test_framework.c（含：擦失败/写失败/读坏数据/停用后不再碰存储/启动路径零存储操作）
- 导出：应用在 dzctl 单字节命令里接 `'F'` → `bb_dump`（照 DS 的 F 命令）。

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：环回绕、只存最新、校验、失败计数与自动停用、init 零存储操作。
- **【未测】上板**：片内 flash 擦写回调还没写（各板擦除粒度不同，留给移植层）；擦页耗时（F4 扇区擦可达 1 s 级）期间控制会停——freeze 只应在急停/停机后调用。

## 参考来源
- DS-land-and-air（实验室队友工程）`car/Hardware/app_line_follow_mission.c` 的 F 命令导出冻结日志；其 ESP32 端 NVS 写满导致启动卡住的教训。见 docs/参考来源.md。代码自写。
