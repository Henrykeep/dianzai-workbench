# BSP I2C 使用指南

## 1. 硬件配置

| 逻辑通道 | 外设 | SCL | SDA | 总线速率 |
| --- | --- | --- | --- | --- |
| `BSP_I2C_CHANNEL_OLED` | I2C0 Controller | PA31 | PA28 | 400 kHz |
| `BSP_I2C_CHANNEL_MPU6050` | I2C1 Controller | PB2 | PB3 | 400 kHz |

OLED 和 MPU6050 使用两套独立的 I2C 外设及引脚。每套 I2C 总线都需要上拉电阻，
许多模块已经自带上拉。

## 2. 公开接口

```c
BSPI2CInstance *BSPI2CRegister(BSP_I2C_Channel_e channel);
bool BSPI2CWrite(BSPI2CInstance *instance, uint8_t target_address,
    const uint8_t *data, size_t size);
bool BSPI2CWriteRead(BSPI2CInstance *instance,
    uint8_t target_address, const uint8_t *write_data,
    size_t write_size, uint8_t *read_data, size_t read_size);
```

`BSPI2CWriteRead()` 使用重复起始条件完成“写寄存器地址/命令后读取”，适合 MPU6050；
写、读缓冲都必须有效，长度为 1～`UINT16_MAX`。

## 3. 基本使用

```c
static BSPI2CInstance *oled_i2c;

void I2CExample(void)
{
    static const uint8_t command[] = {0x00U, 0xAEU};

    oled_i2c = BSPI2CRegister(BSP_I2C_CHANNEL_OLED);
    if (oled_i2c == NULL) {
        return;
    }

    /* SSD1306 常用 7 位地址为 0x3C，实际以模块接法为准。 */
    (void)BSPI2CWrite(oled_i2c, 0x3CU,
        command, sizeof(command));
}
```

`target_address` 必须是 7 位地址，范围为 `0x00～0x7F`。不要传已经左移一位的 8 位地址 `0x78`。

数据指针不能为空，发送长度必须大于 0 且不超过 `UINT16_MAX`。

## 4. 阻塞发送流程

`BSPI2CWrite()` 会在调用线程中完成整个传输：

1. 等待 I2C Controller 空闲。
2. 复位旧传输状态并清空 TX FIFO。
3. 向 FIFO 填入首批数据并启动传输。
4. 轮询状态并继续补充 FIFO。
5. 等待停止条件完成并再次确认总线空闲。

发送期间调用者不会继续执行。调度器运行时，较长轮询会周期性 `taskYIELD()`，避免
无意义地独占同优先级 CPU；启动前仍使用有限次数轮询。较大的 OLED 帧缓冲刷新可能
占用较长时间，不应从中断服务函数调用。

## 5. 超时和错误恢复

每个等待阶段都有有限轮询次数。出现以下情况时接口返回 `false`：

- 参数非法
- 目标地址无应答
- 总线忙超时
- 发送过程出现 I2C 错误
- 传输完成等待超时

失败时 BSP 会终止当前 Controller 传输并清空 FIFO。若 SDA 被从设备卡在低电平，
还会临时把 SCL 当 GPIO 输出最多 9 个恢复时钟，再恢复 I2C 引脚复用并重新初始化
Controller；这只能恢复常见的半截字节状态，不能修复供电、地址或硬件短路。

如果持续失败，应检查：

- OLED 供电和公共地
- PA31/PA28 是否接反（OLED）；MPU6050 检查 PB2/PB3
- 7 位地址是 `0x3C` 还是 `0x3D`
- SCL/SDA 是否有上拉以及波形是否能拉高
- 是否有其他任务同时使用对应的 I2C 外设

## 6. 并发注意事项

BSP I2C 不带 FreeRTOS 互斥锁。多个任务直接调用会破坏同一次传输。应用层应优先通过 `modules/i2c` 访问，由模块层串行化总线操作。

同一总线上可以挂接多个不同地址的设备，但它们必须共享同一个受保护的 Controller 实例。
本工程的 OLED 和 MPU6050 不在同一总线上。

## 7. 扩展 DMA 或其他事务

当前已支持带重复起始的写后读。需要增加纯读、DMA 或异步事务时，应在 BSP 新增明确
接口，并同时配置：

- SysConfig 中 I2C0/I2C1 的 DMA/中断事件
- 读写状态机和超时恢复
- 总线互斥策略
- 完成回调的上下文规则

对 128×64 单色 OLED 而言，简单阻塞写通常已经足够；DMA 是否有收益取决于刷新频率和 CPU 占用要求。
