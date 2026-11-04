# Capture Module 使用指南

`modules/capture` 把 BSP 的原始时间戳差值封装为线程安全的周期和频率接口，不向
Application 暴露 DriverLib 或具体定时器寄存器。

## 1. 注册

```c
#include "modules/capture/capture.h"

static CaptureInstance *capture_pa27;
static CaptureInstance *capture_pa21;

static bool ExampleCaptureInit(void)
{
    static const CaptureConfig config = {
        .threshold_millivolts = 330U,
        .start_enabled = true
    };

    capture_pa27 = CaptureRegister(
        CAPTURE_DEVICE_ANALOG_INPUT_0, &config);
    capture_pa21 = CaptureRegister(
        CAPTURE_DEVICE_ANALOG_INPUT_1, &config);
    return (capture_pa27 != NULL) && (capture_pa21 != NULL);
}
```

同一逻辑设备重复注册会返回已有实例，不会重新应用第二份注册配置。模块使用静态
实例和静态 FreeRTOS 互斥锁，不使用堆内存。

## 2. 读取结果

```c
CaptureMeasurement measurement;

if (CaptureReadMeasurement(capture_pa21, &measurement)) {
    uint32_t hz_integer = measurement.frequency_millihz / 1000U;
    uint32_t hz_fraction = measurement.frequency_millihz % 1000U;
    /* 结果为 hz_integer.hz_fraction Hz。 */
}
```

结果字段：

| 字段 | 含义 |
| --- | --- |
| `period_ticks` | 相邻边沿间的定时器 tick 数，单位随实例而异 |
| `frequency_millihz` | 频率，单位 0.001 Hz |
| `edge_count` | 本次启动后的累计边沿数 |
| `sequence` | 每生成一个新完整周期递增一次 |

频率采用 64 位中间值和整数四舍五入计算：

```text
frequency_millihz = round(timer_clock_hz × 1000 / period_ticks)
```

| 逻辑设备 | 引脚 | `timer_clock_hz` | tick 分辨率 |
| --- | --- | ---: | ---: |
| `CAPTURE_DEVICE_ANALOG_INPUT_0` | PA27 | 4,000,000 Hz | 0.25 us |
| `CAPTURE_DEVICE_ANALOG_INPUT_1` | PA21 | 62,500 Hz | 16 us |

这里的 PA21 是 `COMP2.IN1-` 的真实捕获引脚。当前第二路 ADC 已迁移到
PB19/ADC1.6，因此 `CAPTURE_DEVICE_ANALOG_INPUT_1` 与 `ADC_DEVICE_INPUT_1` 不再
指向同一个外部引脚；两者的枚举下标相同不代表信号来源相同。

可使用 `CaptureGetTimerClockHz()` 查询实例的时钟，不要在通用代码中固定按
4 MHz 解释 `period_ticks`。

读接口返回的是最近一次完整结果，并不会自动清除。轮询任务可保存 `sequence`，只在
序号变化时处理新数据。

## 3. 动态控制

```c
(void)CaptureSetThresholdMillivolts(capture_pa21, 500U);
(void)CaptureStop(capture_pa21);
(void)CaptureStart(capture_pa21);
```

- 阈值合法范围由 BSP 决定，当前为 `0～3300 mV`。
- `CaptureStart()` 会清空历史边沿和测量结果，并重新开启单次周期捕获。
- 收到两个有效边沿后会自动屏蔽本次中断，已测结果仍可读取。
- `CaptureStop()` 保留最近一次完整结果。
- 接口使用任务互斥锁，可以从多个任务调用，但不能在 ISR 中调用。

需要直接按 PA27/PA21 选择输入，并取得已换算的微秒周期时，使用同目录下的
`analog_capture.h`。它的聚合启停接口同时操作两路，分路读取使用
`AnalogCaptureReadInputMeasurement()`。
