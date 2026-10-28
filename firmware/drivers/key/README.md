# key — 按键消抖与短按/长按

- `key_feed()` 纯逻辑可单测；`key_poll()` 读 `pal_gpio_read`（极性由 board.yaml 的 active 决定）。
- 建议在 10 ms 或更快的周期任务里调用。
- 【已实测】主机单测：抖动不出事件、短按松开时报一次、长按到时报一次、连发周期、计时回绕。
- 【未验证】真实按键上板。
- 参考：Jack Ganssle, *A Guide to Debouncing*（时间积分消抖）；P2 工程短按/长按设计（思路，非代码）。
