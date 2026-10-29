# keypad4x4 — 4×4 矩阵键盘  `v1.0.0`

逐行扫描 + 每键独立消抖，给出按下/松开/保持位图，键位 `1 2 3 A / 4 5 6 B / 7 8 9 C / * 0 # D`。配 framework/menu 做板上菜单。

board.yaml 片段（引脚按自己的板改）：
```yaml
gpio:
  - { name: KP_R0, pin: PA0, dir: out, active_low: true }   # ×4 行；建议开漏 + 上拉
  - { name: KP_C0, pin: PA4, dir: in,  active_low: true, pull: up }   # ×4 列
```

- 每 5..10 ms 调 `kp_process(&k, 经过的毫秒, &ev)`；`kp_char(kp_first(ev.pressed))` 得字符。
- **多键同按**：非选中行是推挽高电平时，两行经按键短接——行脚配开漏最稳；只按单键的菜单用法没问题。
- 主机测试 tests/host/test_signal.c（host-sim 读钩子模拟真实矩阵：按住某键时只有对应行被选中才读到列有效）

## 验证状态
- **已实测（PC 主机）**：扫描到正确键位、抖动 < 消抖时间不报、按下/松开各报一次、双键同按、GPIO 失败返回错误。
- **【未测】上板**（行开漏/推挽两种接法都没在实物上试）。

## 参考来源
LP-MSPM0G3507_freertos_firework@ede35a2 `modules/matrix_keypad/matrix_keypad.c`（MIT，阡陌）直接移植（见文件头）。
