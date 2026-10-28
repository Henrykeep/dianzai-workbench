# MPU-6050 六轴 IMU（I2C）  `v1.0.0`

用的是 PAL I2C（`pal_i2c_mem_read/write`），所以 STM32（CubeMX 或 stm32f4-hal）和 MSPM0 上是同一份代码；总线和引脚写在 board.yaml 的 `resources.i2c` 里。

- 接口：`mpu6050_init/read/calib_gyro`，输出 m/s² 和 rad/s（已减零偏）
- 自检：`mpu6050_selftest()`（只测换算）；tests/host/test_imu.c 用仿真假芯片测完整的初始化和读数流程，包括读回校验失败、无应答、零偏标定
- 默认配置：±4 g、±1000 °/s、DLPF 3（约 43 Hz），输出 1 kHz

## 现场注意
- 模块上的 4.7 kΩ 上拉通常已经焊好；线超过 20 cm 时用 100 kHz（board.yaml 写 `speed_hz: 100000`）
- AD0 悬空时地址不确定，接地后地址为 0x68
- 初始化时读回不一致（EIO）：先查线和上拉，再查是不是两个模块地址冲突

## 验证状态
- **已实测（PC 主机）**：寄存器序列、换算、错误路径（tests/host/test_imu.c）
- **未验证**：真芯片上没测过（STM32 和 MSPM0 都没有上板）

## 参考来源
- InvenSense《MPU-6000/MPU-6050 Register Map and Descriptions》Rev 4.2，以及《Product Specification》Rev 3.4（量程和 LSB 取自这两份）。自写，没有参考 i2cdevlib 等代码。

## 直连路径：姿态 + 去重力（v0.6.0）
主控自己读 MPU6050（不经 imu_module/dzimu）时，用 `firmware/algo/attitude`（1.1.0）补上姿态和去重力：
```c
mpu6050_data_t d; float lin[3];
if (mpu6050_read(&imu, &d) == DZ_OK) {
    attitude_update(&att, d.acc, d.gyr, 0.001f);          /* 1 kHz */
    if (attitude_linear_acc(&att, d.acc, lin)) { /* lin = 运动加速度，m/s²，本体系 */ }
}
```
公式与 `dzimu_linear_acc` 相同。【仿真】host 单测：假 MPU6050 俯仰 10° 静止，去重力后三轴 < 0.02 m/s²；叠加 0.5 m/s² 前向加速度能分离出来。未上板。
