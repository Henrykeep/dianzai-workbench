# Waveform Module 使用指南

`modules/waveform/` 提供绑定到通用 128×64 逻辑画布的滚动波形绘制器，包括 128 点历史缓冲、
量程映射、网格和相邻采样连线。

## 1. 注册波形实例

```c
#include "modules/waveform/waveform.h"

static WaveformInstance *waveform;

bool ExampleWaveformInit(DisplayInstance *display)
{
    static const WaveformConfig config = {
        .x = 0U,
        .y = 8U,
        .width = 128U,
        .height = 56U,
        .minimum = -2048,
        .maximum = 2047,
        .grid_enabled = true
    };

    waveform = WaveformRegister(display, &config);
    return waveform != NULL;
}
```

绘图区必须位于128×64范围内，宽度和高度至少为2，并且 `minimum < maximum`。当前只
提供一个静态Waveform实例。

## 2. 输入采样

```c
int16_t centered_sample = (int16_t)((int32_t)adc_raw - 2048);

(void)WaveformPushSample(waveform, centered_sample);
```

模块最多保存128点。缓冲区写满后，新数据覆盖最早的数据。超出配置量程的数据不会
被丢弃，绘制时会饱和到顶部或底部。

读取最近采样：

```c
int16_t latest;
(void)WaveformGetLatestSample(waveform, &latest);
```

## 3. 绘制和刷新

```c
if (WaveformRender(waveform)) {
    (void)DisplayUpdate(display);
}
```

`WaveformRender()` 只修改当前后端的本地帧缓冲，不立即发送总线数据。
可根据绘图区范围调用 `DisplayUpdatePages()` 进行局部刷新，减少 I2C/SPI 占用。

网格启用时会绘制中心水平点线和每16像素一列的垂直点阵。相邻采样列之间会连接
垂直线，避免快速跳变时出现明显断点。

## 4. 重置和修改量程

```c
(void)WaveformReset(waveform);
(void)WaveformSetRange(waveform, -1000, 1000);
```

重置只清除采样历史，不自动清屏。修改量程不会删除已有样本，下次绘制会按新范围
重新映射。

## 5. X轴时间含义

Waveform保存的是采样点，不直接保存时间。屏幕时间跨度近似为：

```text
时间跨度 = 显示点数 ÷ 实际送入Waveform的点频率
```

例如每1ms送入一个点、显示128点，满屏约表示128ms。如果Application每10个ADC点
抽取一个再送入，满屏时间会扩大到约1.28秒。

## 6. 任务和显示注意事项

- `WaveformPushSample()` 使用任务临界区保护历史缓冲，但不能从ISR调用。
- 波形绘制和屏幕刷新建议固定在同一个显示任务中完成。
- 屏幕刷新速度远低于 ADC 采样速度，应在 Application 中抽取数据或降低刷新帧率。
- 三点中值滤波适合去除孤立毛刺；卡尔曼滤波过强会让方波边沿变缓。
- 当前模块不自动获取ADC或UART数据，数据源选择属于Application层。
