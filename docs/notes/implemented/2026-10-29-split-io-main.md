# 2026H io 胶水：LINK 与 IMU 拆出 io_main.c

- **决定**：`io_link.c`（上位机链路，无 LINK 的板给空实现）、`io_imu.c`（UART 姿态模块 / MPU6050 直连 / 无），`io_main.c` 只剩电机、编码器、视觉、摆杆和主循环；内部接口 `io_parts.h`。io_main.c 的条件编译（#if/#ifdef/#elif）从 15 处降到 1 处（LED）。
- **为什么**：io_main.c 14 次修改、296 行、`#if` 多路并存，是新人和 AI 最常改错的地方（docs/27 G3）。
- **证据**：`make -C examples/2026H_ball/tests`、`make test`（侧车 e2e 用 host-sim 2026H_ball）、`make cross`；三条编译路径都编过：host-sim（LINK+UART IMU）、bldc-freertos（无 LINK、无 IMU，含 LINK=rtt）、MPU6050 路径用临时改宏单独 `-fsyntax-only`（没有任何现成板只带 I2C IMU 跑 2026H）。**[未测] 上板、Keil。**
- **代价**：函数不再是 static，二进制与拆分前不逐字节相同（行为相同由测试保证，不是 md5 保证）。
- **否决过**：把可选来源做成"注册表/函数指针表"代替 `#if`（docs/27 初稿建议）——对两三个可选外设是过度设计，读代码的人要多跳一层；按文件拆已经把 `#if` 收进各自文件。
