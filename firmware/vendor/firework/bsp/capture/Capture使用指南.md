# BSP Capture 使用指南

`bsp/capture` 封装两路模拟比较器时间戳捕获。第一路 PA27 与 ADC0 共脚；第二路
捕获仍在 PA21，但当前第二路 ADC 已迁移到 PB19，因此不再共脚：

```text
PA27 / COMP0 IN0-
        ↓ 与内部 8 位 DAC 阈值比较
COMP0 输出边沿
        ↓ Event Fabric channel 2
TIMG12 CC0 Trigger Capture
        ↓
相邻时间戳差值

PA21 / COMP2 IN1-
        ↓ 与内部 8 位 DAC 阈值比较
COMP2 输出边沿
        ↓ Event Fabric channel 3
TIMG6 CC0 Trigger Capture
        ↓
相邻时间戳差值
```

## 1. SysConfig 配置

| 项目 | 当前配置 |
| --- | --- |
| 输入 0 | PA27 / COMP0 IN0- / Event channel 2 / TIMG12 |
| 输入 1 | PA21 / COMP2 IN1- / Event channel 3 / TIMG6 |
| 比较器模式 | 两路均为 Fast Mode |
| 正输入 | VDDA 参考的内部 8 位 DAC |
| 迟滞 | 30 mV |
| 数字滤波 | 500 ns |
| 事件 | COMP 输出上升边沿 |
| 输入 0 计时 | TIMG12，32 位，4 MHz，每 tick 0.25 us，100 s 回卷 |
| 输入 1 计时 | TIMG6，16 位，62.5 kHz，每 tick 16 us，1 s 回卷 |

因为外部信号接在比较器负输入，COMP 输出上升表示输入从高于阈值下降到低于阈值。
对周期信号而言，测量下降过阈值或上升过阈值所得周期相同。

## 2. 接口

```c
BSPCaptureInstance *BSPCaptureRegister(BSP_Capture_Device_e device);
bool BSPCaptureStart(BSPCaptureInstance *instance);
bool BSPCaptureStop(BSPCaptureInstance *instance);
bool BSPCaptureSetThresholdMillivolts(
    BSPCaptureInstance *instance, uint16_t threshold_millivolts);
bool BSPCaptureReadMeasurement(BSPCaptureInstance *instance,
    BSPCaptureMeasurement *measurement);
uint16_t BSPCaptureGetThresholdMillivolts(
    const BSPCaptureInstance *instance);
bool BSPCaptureIsRunning(const BSPCaptureInstance *instance);
uint32_t BSPCaptureGetTimerClockHz(
    const BSPCaptureInstance *instance);
```

`BSPCaptureReadMeasurement()` 返回最近两个有效边沿之间的 tick 数、累计边沿数和
结果序号。第一次边沿只建立起始时间戳，第二次边沿得到完整周期后，
BSP 会立即屏蔽本次定时器捕获中断。下次调用 `BSPCaptureStart()` 会清空
旧状态并重新使能中断。

## 3. 阈值

软件将 `0～3300 mV` 四舍五入映射到 `0～255` DAC 码：

```text
DAC code = round(threshold_mV × 255 / 3300)
```

这里的 3300 mV 是标称值，实际比较阈值随开发板 VDDA 变化。若需要更高绝对精度，
应测量实际 VDDA，并按实际参考电压换算 DAC 码。

修改阈值会丢弃上一半周期，防止用两个不同阈值的边沿拼成错误结果。

## 4. ISR 与并发

TIMG12/TIMG6 ISR 都只读取 CC0 时间戳、计算整数 tick 差值并发布各自快照。
每次 `Start` 最多处理两个有效上升沿，不会随输入频率持续产生 CPU 中断。
应用读取快照时使用很短的全局中断临界区，不在 ISR 中调用 FreeRTOS、
浮点运算或串口发送。

BSP 自身不提供任务互斥；多任务调用请使用 `modules/capture`。

## 5. 硬件限制

- PA27、PA21 电压必须在器件允许的模拟输入范围内，不能直接接负电压或高于 VDDA。
- 第二路若要同时得到 ADC 电压和硬件周期，应把同一受保护信号同时送到
  PB19/ADC1.6 和 PA21/COMP2；只接 PA21 不会产生当前第二路 ADC 数据。
- LaunchPad 的 PA27 可通过 J17 连接板载光电二极管 D1；测量外部信号时应将
  `J17 OFF`，避免板载电路影响输入。
- 输入 0 完整周期应小于 100 s；输入 1 使用 1 s 回卷的 TIMG6，完整周期应小于 1 s。
- PA21/TIMG6 的 16 us 分辨率低于 PA27/TIMG12 的 0.25 us；需要最高测频精度时优先 PA27。
- TIMG6 使用 64 分频是范围与精度的取舍。若不分频，16 位计数器在
  4 MHz 下只能覆盖约 16.384 ms；64 分频后可覆盖约 1.049 s，
  但分辨率降为 16 us。
- 高频极限主要取决于比较器、500 ns 滤波、事件通路和定时器 tick
  分辨率。高频或噪声较大的信号应使用示波器核对结果。
- 30 mV 迟滞和 500 ns 滤波可抑制阈值附近抖动，但不会替代正确的模拟调理。
