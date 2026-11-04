# BSP ADC 使用指南

`bsp/adc` 负责 PA27/ADC0/DMA_CH5 和 PB19/ADC1.6/DMA_CH6 的一次性 DMA 采集。
两路共用同一套采集管理和高速 FFT 工作区，因此同一时刻只允许一路执行采集。

## 当前采集流程

1. `BSPADCRegister()` 只注册硬件映射，不启动 ADC。
2. `BSPADCStartDirectCapture()` 先重置 TIMG0、当前 ADC 和当前 DMA 通道。
3. 1 MHz 及更低速率使用 TIMG0 + `TRIGGER_NEXT` 精确逐点触发；4 MHz 按 TI 官方最高速率例程使用 `AUTO_NEXT` + FIFO + DMA；2 MHz 先采集 4 MSPS 原始数据，再原地每隔 2 点保留 1 点。
4. 最终 N 点全部完成后只触发一次 DMA 中断并执行完成回调。
5. `BSPADCFinishDirectCapture()` 关闭采样链并清理状态，不会强制回退到 1 MHz。

高速路径不再由 TIMG0 逐点触发。原实现在重复采集时可能出现
ADC 触发溢出，使有效采样率低于 FFT 使用的标称采样率，频率结果会被系统性放大。
当前 2/4 MHz 路径与 TI SDK 的 `adc12_max_freq_dma` 配置保持一致。

旧的 64 点 ping/pong 连续流接口及常驻缓冲区已经删除。

## 采样率

TIMG0 时钟为 4 MHz。支持的采样率必须满足：

```text
1 Hz <= sample_rate_hz <= 4 MHz
4 MHz % sample_rate_hz == 0
```

PA27 的应用配置限定为 1/2/4 MHz；默认 1 MHz。超过 1 MHz 时使用高速采样时间配置。

## 主要接口

```c
BSPADCInstance *adc = BSPADCRegister(BSP_ADC_CHANNEL_INPUT_0);

bool started = BSPADCStartDirectCapture(
    adc,
    samples,
    1024U, /* 缓冲区容量 */
    1024U,
    1000000UL,
    CaptureCompleteFromISR,
    NULL);

/* 完成回调唤醒任务后，由任务调用。 */
(void)BSPADCFinishDirectCapture(adc);
```

完成回调位于 DMA ISR 上下文，只能执行 ISR 安全操作。缓冲区必须在整个采集期间保持有效。2 MHz 会暂存双倍原始点，所以容量参数必须至少是最终点数的 2 倍。

## 硬件资源

| 输入 | ADC | DMA | 触发定时器 |
|---|---|---|---|
| PA27 | ADC0 MEM0/FIFO | CH5 | TIMG0（1 MHz 及更低）/ADC 连续转换（2/4 MHz） |
| PB19 / ADC1.6 | ADC1 MEM0/FIFO | CH6 | TIMG0（1 MHz 及更低）/ADC 连续转换（2/4 MHz） |

两路可以分别注册，但上层与 BSP 都按单路采集管理；若一路尚未完成或尚未执行 Finish，另一路启动会返回 `false`。

LaunchPad 的 PA21/VREF- 受板上 C7 交流旁路影响，当前 SysConfig 不再把它作为
ADC1 输入。PA21 仍用于 COMP2 捕获；不要因上层兼容枚举仍写 `PA21` 而把第二路
ADC 信号接错脚。
