# BMI088 六轴 IMU（SPI）  `v1.0.0`

RoboMaster C 型板板载的 IMU。加速度计和陀螺仪各有一根片选，所以在 board.yaml 里写两条 `resources.spi`（共用 SPI1，CS 分别是 PA4 和 PB0），用 PAL SPI 访问。

- 接口：`bmi088_init/read/read_temp/calib_gyro`，输出 m/s² 和 rad/s
- 默认配置：±6 g、±1000 °/s，加速度 800 Hz、陀螺 1000 Hz
- 自检：`bmi088_selftest()`（换算）；tests/host/test_imu.c 用仿真假芯片测完整初始化，包括加速度计的哑读切换 SPI、哑字节、读回校验和片选接反的报错
- 典型用法：`apps/imu_module` 让 C 型板变成姿态模块，经串口发 dzimu 帧给主控

## 现场注意
- 加速度计上电后处于 I2C 模式：必须先哑读一次 CHIP_ID 才会切到 SPI 模式（驱动已经处理）
- 读到 ID=0xFF 或 0x00：多半是片选接反、SPI 模式不对，或者 IMU 供电没开
- C 型板有 IMU 加热电阻（TIM10_CH1 PF6），恒温能减小零偏漂移；本驱动不负责加热

## 验证状态
- **已实测（PC 主机）**：寄存器序列与换算（tests/host/test_imu.c）
- **未验证**：真 C 型板上没跑过

## 参考来源
- Bosch Sensortec《BMI088 Datasheet》BST-BMI088-DS001（寄存器、换算公式、SPI 哑字节、上电 I2C→SPI 切换）。自写，没有复制 DJI 例程或 Bosch API 的代码。
