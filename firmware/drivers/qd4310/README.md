# qd4310 — QD4310 串口无刷驱动器

按协议描述重写（P1/P2 工程阅读整理的帧格式，见 docs/12），**未拷贝厂商例程**；P2 的好设计（只发不等、滑窗+CRC 重同步、在线超时、发送忙计数）按思路重做。

- 下行：`qd4310_set_angle_deg/speed/current/enable`，经 `pal_uart_write`（非阻塞）。
- 上行：周期任务里调 `qd4310_poll()`，`qd4310_online()` 判断链路。
- 角度用 u16 编码 0..65535 ↔ 0..360°，避开官方例程 int16 溢出问题。
- 【已实测】主机单测：CRC-8/SMBUS 校验值 0xF4、编码字节序、缩放钳位、滑窗重同步（垃圾字节、假帧头、CRC 错）、在线超时。
- 【未验证】实物：CRC 初值 0x00 为推断；status 位含义未知；921600 波特率下的时序。**上板前先用逻辑分析仪抓一帧官方上位机的命令核对 CRC。**
- 参考：CRC 目录 reveng “CRC-8/SMBUS”（https://reveng.sourceforge.io/crc-catalogue/1-15.htm）。
