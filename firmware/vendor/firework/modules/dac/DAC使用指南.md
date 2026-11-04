# DAC Module 使用指南

`modules/dac/` 将PA15上的12位DAC0封装为线程安全的原始值、毫伏和百分比输出接口。
同目录的 `dac_output.c/.h` 使用 DAC 内部 Sample Timer、FIFO、DMA_CH0 和静态查找表
输出正弦波、方波、三角波和锯齿波，由 `application/waveform/waveform_output` 统一调用。

## 1. 硬件和量程

| 项目 | 当前配置 |
|---|---|
| 逻辑设备 | `DAC_DEVICE_OUTPUT_0` |
| 输出引脚 | PA15 |
| 原始范围 | `0～4095` |
| 标称参考 | `0～3300 mV` |
| 正弦/三角/锯齿波频率 | `1～62500 Hz`，每周期至少16点 |
| 方波频率 | `1～500000 Hz`，每周期至少2点且为偶数点 |
| 周期波形DAC更新率 | 固定 `APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ`，默认1 MSPS |
| DMA | DMA_CH0；内置波形和任意波形均使用双缓冲 |

输出实际精度受VDDA、DAC偏移、增益和负载阻抗影响。

## 2. 注册和初始状态

```c
#include "modules/dac/dac.h"

static DACInstance *dac;

bool ExampleDACInit(void)
{
    static const DACConfig config = {
        .initial_raw_value = 0U,
        .start_enabled = true
    };

    dac = DACRegister(DAC_DEVICE_OUTPUT_0, &config);
    return dac != NULL;
}
```

`start_enabled` 为 `false` 时会保存初值但关闭模拟输出。同一逻辑设备重复注册返回已有
实例，不会再次应用新的注册配置。

## 3. 设置输出

```c
(void)DACWriteRaw(dac, 2048U);        /* 约半量程。 */
(void)DACWriteMillivolts(dac, 1650U); /* 标称1.65V。 */
(void)DACWritePercent(dac, 50U);      /* 满量程50%。 */
```

毫伏和百分比接口会执行整数四舍五入，再写入12位原始值。参数超出合法范围时返回
`false`。

## 4. 启停和读取设置值

```c
uint16_t raw;
uint16_t millivolts;

(void)DACStop(dac);
(void)DACStart(dac); /* 恢复最近一次成功设置值。 */

(void)DACGetRawValue(dac, &raw);
(void)DACGetMillivolts(dac, &millivolts);

if (DACIsEnabled(dac)) {
    /* DAC当前已经启用。 */
}
```

读取接口返回软件保存的设置值，不是对PA15实际电压的测量。如需闭环确认，应将DAC
输出经过保护电阻接入ADC。

## 5. 线程和硬件注意事项

- 每个实例使用静态FreeRTOS互斥锁，可从不同任务调用。
- 接口可能阻塞等待互斥锁，不能在ISR中调用。
- PA15已用于DAC时，不能同时作为OLED I2C或普通GPIO。
- 不要直接驱动低阻负载、电机、继电器或大功率器件，应增加缓冲或驱动电路。
- PA15接ADC回环测试时，可串联 `100Ω～1kΩ` 保护电阻并确保共地。
- 输出接近0V或VDDA电源轨时，实际电压可能达不到理想值。
- 周期波形不由 FreeRTOS 任务逐点写 DAC。内置波形和任意波形均由 Sample Timer +
  连续双半区 DMA 表输出；DMA 硬件循环整个2048点区域，半程/完成中断只通知高优先级
  `DACRefill` 任务，由任务查表生成刚释放的1024点数据。块边界不再由CPU重装DMA，
  可避免1 MSPS下的FIFO欠载。若任务未在下一轮 DMA 前提交缓冲区，BSP会安全停止并累计
  `DACOutputGetStreamRefillMissCount()`，避免重放旧数据。
- 正弦、方波、三角波和锯齿波共用32位相位累加器，在所有输出频率下保持
  `APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ`（默认1 MSPS），外部滤波器不需要跟随
  输出频率切换。基础32点正弦表会在启动时插值为1024级幅值表，避免固定32级台阶。
- 任意波形会先归一化到1024级相位表，再根据其 `sample_rate_hz` 和点数计算相位
  步进；因此 DAC 更新率固定，但原波形播放时间和标称频率保持不变。
- 平滑波形每周期至少16点。`APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES=1U`
  时，方波的每个半周期固定使用整数个采样点，高、低电平长度相等，不会通过
  交替7/8个采样点来逼近频率，因此请求频率
  可能被量化；设为 `0U` 可恢复平均频率优先模式，但边沿可能抖动。可用
  `DACOutputGetActualFrequencyMillihz()` 查看量化后的实际频率。
- `DACOutputGetWaveformConfig()` 可读取当前周期波形的类型、请求频率和
  最小/最大电压；直流、任意波形或停止状态返回 `false`。
- 默认配置下平滑波形的 `62.5 kHz` 上限来自固定 `1 MSPS / 16点`，方波的
  `500 kHz` 上限来自 `1 MSPS / 2点`。降低固定采样率时，平滑波形上限会自动
  降为采样率的1/16，方波上限降为1/2。高频输出
  仍会受到 DAC 建立时间、输出缓冲、负载和外部滤波器影响，软件允许该频率不等于
  在所有负载下都能得到理想波形。
- DMA_CH0 已从 UART0 释放；UART0 调试发送继续使用轮询。UART1～UART3 分别使用
  DMA_CH1～DMA_CH3，UART2 RX 使用 DMA_CH4，ADC 使用 DMA_CH5/CH6。
