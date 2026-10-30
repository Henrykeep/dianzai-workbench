# as5600 — AS5600 12 位磁编码器（I2C）

读 RAW ANGLE（0x0C），软件零点 / 方向，多圈展开，速度一阶低通，磁铁状态检查。给 `firmware/algo/foc` 做转子角。

## board.yaml
```yaml
i2c:
  - { name: ENC, instance: I2C1, scl: PB6, sda: PB7, speed_hz: 400000 }
```

## 用法
```c
as5600_init(&enc, &(as5600_cfg_t){ RES_I2C_ENC, +1, 0.005f });
if (as5600_check_magnet(&enc, NULL) != DZ_OK) { /* 磁铁没装 / 距离不对：别启动 FOC */ }
as5600_update(&enc, pal_micros());           /* 1 kHz 左右 */
float th = as5600_angle(&enc), w = as5600_velocity(&enc);
```
- 两次 `as5600_update` 之间转过不能超过半圈（2048 计数），否则多圈计数会错：3000 rpm 时至少 1.6 kHz。
- 磁铁径向充磁、离芯片 0.5~3 mm；`check_magnet` 返回 DZ_EFAIL 时看 status 的 ML/MH 位。

## 测试状态
- 【仿真】主机单测（假 AS5600 挂 host-sim I2C）：12 位拼接、跨零多圈（正反）、方向、零点、速度、磁铁三种状态、I2C 失败计数。
- 【未测】真芯片。
- 参考：pid_helper STM32F1 / ESP32-C3 例程 `as5600_dev.c`、SimpleFOC `MagneticSensorI2C`（见 docs/参考来源.md）。
