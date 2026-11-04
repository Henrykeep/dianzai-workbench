# Analog Capture Module 使用指南

本功能使用模拟比较器把周期模拟信号变成片内数字边沿，再由定时器捕获
相邻边沿的时间差。工程提供 PA27 和 PA21 两路独立捕获。

需要特别区分：当前第二路 ADC 已改为 **PB19 / ADC1.6**，而第二路比较器捕获仍是
**PA21 / COMP2**。只有 PA27 同时承载 ADC0 和 COMP0；PA21 不再与第二路 ADC 共用
外部输入。`ANALOG_CAPTURE_INPUT_PA21` 是真实的 PA21 捕获输入，不是 PB19 的别名。

## 1. 信号链路

```text
外部周期信号 → PA27 / COMP0 IN0- → Event channel 2 → TIMG12 4 MHz
外部周期信号 → PA21 / COMP2 IN1- → Event channel 3 → TIMG6 62.5 kHz
                         ↑
                   内部 DAC 比较阈值
```

默认阈值为 1650 mV。当信号穿越阈值时，比较器产生边沿；
两个相邻同向边沿形成一个完整周期。得到本次周期后会自动屏蔽该路
Capture 中断，下次 `AnalogCaptureStartInput()` 时再重新开启，因此高频
输入不会让 CPU 持续处理每一个边沿。

PA27 使用 32 位 TIMG12，时间分辨率为 0.25 us；PA21 使用 16 位 TIMG6，
时间分辨率为 16 us。需要更高频率精度时优先使用 PA27。

这不是引脚的模拟精度差异，而是捕获定时器配置不同。TIMG6 只有 16 位，
如果以 4 MHz 直接计数，最大只能覆盖约 16.384 ms 周期。当前使用
64 分频换取约 1.049 s 范围，因此分辨率变为 16 us。ADC 的点数、采样率和
12 位电压换算不属于 Capture Module，应分别查阅 ADC 文档。

## 2. 接线

| 测量输入 | 用途 | 注意事项 |
| --- | --- | --- |
| PA27 / J1_8 | ADC0 + COMP0 共用输入 | 外接信号前将 LaunchPad `J17 OFF` |
| PA21 | COMP2 捕获输入 | 当前不再作为第二路 ADC；请根据原理图确认测试点或引出位置 |
| PB19 | ADC1.6 输入 | 不属于本 Capture Module；列在此处仅用于避免与 PA21 混淆 |
| GND | 信号地 | 信号源与开发板必须共地 |

输入必须保持在 `0～VDDA` 范围。负电压、5 V 信号或带较大直流偏置的波形
必须先经过限幅、分压、隔直和偏置等调理。

## 3. 分路接口

```c
#include "modules/capture/analog_capture.h"

AnalogCaptureMeasurement measurement;

(void)AnalogCaptureSetInputThresholdMillivolts(
    ANALOG_CAPTURE_INPUT_PA21, 500U);

if (AnalogCaptureReadInputMeasurement(
        ANALOG_CAPTURE_INPUT_PA21, &measurement)) {
    uint32_t frequency_hz = measurement.frequency_millihz / 1000U;
    uint32_t period_us = measurement.period_microseconds;
}
```

可选输入：

```c
ANALOG_CAPTURE_INPUT_PA27
ANALOG_CAPTURE_INPUT_PA21
```

分路接口：

```c
bool AnalogCaptureStartInput(AnalogCaptureInput_e input);
bool AnalogCaptureStopInput(AnalogCaptureInput_e input);
bool AnalogCaptureSetInputThresholdMillivolts(
    AnalogCaptureInput_e input, uint16_t threshold_millivolts);
uint16_t AnalogCaptureGetInputThresholdMillivolts(
    AnalogCaptureInput_e input);
bool AnalogCaptureReadInputMeasurement(
    AnalogCaptureInput_e input, AnalogCaptureMeasurement *measurement);
bool AnalogCaptureIsInputRunning(AnalogCaptureInput_e input);
```

`AnalogCaptureReadInputMeasurement()` 在至少收到两个有效边沿后返回：

- `frequency_millihz`：频率，单位 0.001 Hz。
- `period_microseconds`：四舍五入后的周期，单位 us。
- `edge_count`：本次启动以来的累计边沿数。
- `sequence`：新完整周期的序号，可用于判断结果是否更新。

## 4. 聚合兼容接口

```c
bool AnalogCaptureInit(void);
bool AnalogCaptureStart(void);
bool AnalogCaptureStop(void);
bool AnalogCaptureSetThresholdMillivolts(uint16_t threshold_millivolts);
uint16_t AnalogCaptureGetThresholdMillivolts(void);
bool AnalogCaptureReadMeasurement(AnalogCaptureMeasurement *measurement);
bool AnalogCaptureIsRunning(void);
```

`Start`/`Stop`/`SetThreshold` 同时操作两路。为兼容旧调用，不带输入参数的
`GetThreshold` 和 `ReadMeasurement` 默认读取 PA27。新代码建议使用分路接口。

## 5. 显示菜单

OLED/TFT 共用的显示菜单不再单独提供 `FREQ CAPTURE` 页面。Capture 作为 Waveform
Measurement Application 的内部测频服务，初始化时只注册资源，
每次波形测量请求时才启动选中输入，完成后自动停止。
需要修改阈值或单独启停某一路时，请通过本节前面的分路接口操作。

## 6. Application 归属与排查

Analog Capture 是 Waveform Measurement Application 的内部测频服务，
不再单独暴露 Application 编译开关。启用：

```c
#define APP_ENABLE_WAVEFORM_MEASUREMENT (1U)
#define APP_ENABLE_WAVEFORM_PA27        (1U)
#define APP_ENABLE_WAVEFORM_PB19        (1U)
```

后，`WaveformMeasurementInit()` 会按两个输入开关调用
`AnalogCaptureInitInput()` 完成注册，随后立即停止。显示菜单选择输入时通过
Waveform Measurement 请求接口按次管理 Capture。关闭波形测量
Application 后，不会初始化 Capture。
SysConfig 生成的底层外设配置仍然存在；若产品还需要释放引脚和定时器，应为
该产品维护对应的 SysConfig 构建配置。

当前 Application 的第二路逻辑路径为了兼容旧结构，启用 PB19 ADC 时仍会注册
PA21/COMP2 捕获。如果被测信号只接到 PB19，PA21 捕获通常得不到有效周期，最终频率
应由 PB19 的 FFT 主峰回退得到；若希望使用 Capture 结果，必须把同一受保护信号同时
送到 PA21。不要把 PA21 捕获结果误认为来自 PB19 ADC。

- 阈值必须位于信号最低值和最高值之间，否则不会产生边沿。
- 修改阈值后需要重新收到两个边沿才能得到新周期。
- 每次启动只发布一份周期结果；如需新结果，再次调用分路启动接口。
- 工程启用了 30 mV 滞回和 500 ns 滤波；阈值附近噪声过大时仍需改善模拟前端。
- PA27 完整周期应小于 100 s，PA21 完整周期应小于 1 s。
