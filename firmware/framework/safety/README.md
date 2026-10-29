# framework/safety

多路堵转（algo/stall）+ 异常复位安全态 + 黑匣子记录，合成一个锁存。纯逻辑，主机测试直接跑。用法见 `safety.h` 头注释；范例：`apps/car_2wd`、`examples/2026H_ball`。

- 标志位与 dzctl 心跳 status 字同位：bit8 SAFE_BOOT、bit9 STALL。
- 黑匣子事件码在 `blackbox.h`：`BB_EV_RESET` / `BB_EV_STALL` / `BB_EV_CLEAR`（及 ESTOP、LINE_LOST）。
- 只有 RAM 环时，看门狗复位前的记录会丢；复位本身（原因）在上电时记，所以总能看到“上次为什么复位”。要保留复位前的记录，给 blackbox 接存储并在锁存时 `bb_freeze`。
