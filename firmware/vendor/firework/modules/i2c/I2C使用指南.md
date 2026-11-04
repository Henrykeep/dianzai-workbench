# I2C Module 使用指南

`modules/i2c/` 提供线程安全的阻塞式 I2C Controller 读写接口。目前用于 SSD1306
OLED 和 MPU6050。

## 1. 当前总线配置

| 逻辑设备 | 外设 | SCL | SDA | 总线速度 |
|---|---|---|---|---|
| `I2C_DEVICE_OLED` | I2C0 | PA31 | PA28 | 400 kHz |
| `I2C_DEVICE_MPU6050` | I2C1 | PB2 | PB3 | 400 kHz |

SCL和SDA必须有上拉电阻。大多数OLED模块已经自带上拉；如果没有，通常可使用
`4.7kΩ～10kΩ` 上拉到3.3V。

## 2. 注册总线

```c
#include "modules/i2c/i2c.h"

static I2CInstance *i2c;

bool ExampleI2CInit(void)
{
    i2c = I2CRegister(I2C_DEVICE_OLED);
    return i2c != NULL;
}
```

同一逻辑设备重复注册返回已有实例。模块使用静态实例和静态互斥锁，不申请堆内存。

## 3. 写入7位地址设备

```c
static const uint8_t data[] = {0x00U, 0xAEU};

if (!I2CWrite(i2c, 0x3CU, data, sizeof(data))) {
    /* 地址未应答、总线超时或参数错误。 */
}
```

`target_address` 使用7位地址，例如SSD1306通常是 `0x3C` 或 `0x3D`，不要传已经左移
后的 `0x78` 或 `0x7A`。

## 4. 当前接口限制

- 提供纯写 `I2CWrite()`，以及“写命令/寄存器地址 + 重复起始 + 读数据”的
  `I2CWriteRead()`；不提供无前置写阶段的纯读便捷接口。
- 两种调用都以阻塞方式完成一整笔事务，成功返回 `true`。
- 地址大于 `0x7F`、任一必需缓冲区为空、长度为 0 或超过 `UINT16_MAX` 时返回
  `false`。
- BSP 内部具有有限等待次数；设备不应答、仲裁错误或总线卡死时会中止并尝试恢复，
  最终仍无法完成则返回失败。
- 总线互斥锁可避免多个任务的字节流交叉，但不能在ISR中调用。

读取 MPU6050 的 `WHO_AM_I` 寄存器示例：

```c
I2CInstance *mpu_i2c = I2CRegister(I2C_DEVICE_MPU6050);
uint8_t register_address = 0x75U;
uint8_t who_am_i;

if (mpu_i2c != NULL &&
    I2CWriteRead(mpu_i2c, 0x68U,
        &register_address, 1U, &who_am_i, 1U)) {
    /* 正常 MPU6050 的 who_am_i 为 0x68。 */
}
```

## 5. 常见问题

### 一直返回false

检查设备供电、共地、SCL/SDA是否接反、7位地址是否正确，以及上拉电阻是否存在。

### 总线被拉低

当前 BSP 在传输失败后会临时接管对应 SCL，最多发送 9 个恢复时钟，再恢复 SysConfig
引脚复用并重新初始化该 I2C 控制器。如果仍持续失败，应断电检查器件短路、上拉和
供电；从机状态无法恢复时再重新上电。

### 需要连接其他I2C器件

OLED 和 MPU6050 已经分别绑定到 I2C0 和 I2C1，应用代码应按设备注册对应逻辑实例，
不要把 MPU6050 注册成 `I2C_DEVICE_OLED`。
