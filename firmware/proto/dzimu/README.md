# IMU 姿态模块帧 dzimu  `v1.0.0`

IMU 板（RoboMaster C 型板跑 `apps/imu_module`，或任何能发 dzframe 的板子）经串口给主控发加速度、角速度和横滚/俯仰。走 dzframe/1，DATA 通道 `0x20`，37 字节负载，字段定义见 `dzimu.h`。

- 接口：`dzimu_encode/dzimu_decode/dzimu_axis`
- 自检：`dzimu_selftest()`；tests/host/test_imu.c

## 验证状态
- **已实测（PC 主机）**：往返编解码、NaN 拒收、轴选择，以及 2026H 经仿真串口收帧
- **未验证**：真实串口

## 参考来源
- 自写；字段按 MAVLink `RAW_IMU`/`ATTITUDE` 消息的常见组合裁剪（mavlink.io），没有复制代码。
