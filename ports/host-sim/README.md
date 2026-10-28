# PC 仿真移植层  `v1.0.0`

PAL 的 PC 实现 + 电机/编码器一阶模型，用于在没有硬件时跑通应用逻辑与单测。

- 接口：实现 pal.h；`host_sim.h` 绑定仿真对象
- 自检：—
- 版本规则：见 docs/03-模块三件套与版本.md（删改声明 = MAJOR，新增 = MINOR，iface_hash 强制）

## 验证状态（实验是检验真理的唯一标准）
- **已实测（PC 主机）**：全部主机测试在其上运行（ASan/UBSan）
- **未验证**：仿真模型参数与真实电机的吻合度**未验证**

## 参考来源
- —

## I2C / SPI（2.0.0）
- `host_sim_i2c_attach` / `host_sim_spi_attach` 用来挂“假芯片”回调（见 tests/host/test_imu.c 里的假 MPU6050 和假 BMI088）。
- 没挂芯片时，I2C 返回 EIO（无应答），SPI 读到全 0xFF（MISO 悬空）。
- `host_sim_fail_next(HS_FAIL_I2C / HS_FAIL_SPI, n)` 可以注入超时。
