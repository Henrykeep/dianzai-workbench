# ADC Sampling 使用指南

`modules/adc/adc_sampling.*` 为应用提供 PA27/ADC0.0、PB19/ADC1.6 两路统一的
一次性采样接口。枚举 `ADC_SAMPLING_INPUT_PA21` 只是兼容旧代码的别名，等同于
`ADC_SAMPLING_INPUT_PB19`，不表示当前 ADC 仍连接 PA21。

## 使用方式

```c
static uint16_t samples[1024];

(void)ADCSamplingInitInput(ADC_SAMPLING_INPUT_PA27);

bool started = ADCSamplingStartDirectInputCapture(
    ADC_SAMPLING_INPUT_PA27,
    samples,
    1024U, /* 缓冲区容量 */
    1024U,
    1000000UL,
    CaptureCompleteFromISR,
    NULL);

/* 完成回调通知任务，任务统一处理后执行： */
(void)ADCSamplingFinishDirectInputCapture(
    ADC_SAMPLING_INPUT_PA27);
```

`ADCSamplingInitInput()` 只注册资源，不会后台采样。一次 DMA 填满目标窗口，完成时
只产生一次中断。2 MHz 内部使用 4 MSPS 双倍原始点并二分频，因此调用方必须提供
至少 `sample_count * 2` 的缓冲区容量；2/4 MHz FIFO 路径还要求缓冲区按 32 位对齐，
原始搬运点数为偶数。结束后 ADC/DMA/TIMG0 保持停止，不会恢复旧流式模式。

## 应用层行为

- PA27 和 PB19 都由 Waveform Measurement 按各自 `sample_count` 配置按次采集。
- FFT、参数计算、屏幕绘制都在完整 N 点完成后进行。
- OLED/TFT 波形页从完整结果中取最后 128 点。
- 启用 JustFloat 时，UART2 同样在测量完成后发送最后 128 点。
- UART2 接收波形页是独立输入链路，仍按自己的 1024 点帧收齐后显示最后 128 点。

## 采样率限制

底层和 PB19 应用配置支持 `1～4000000 Hz`，且采样率必须整除 4 MHz；PA27 应用
配置限定为 1/2/4 MHz 三档。1 MHz 及更低档由 TIMG0 定时，2/4 MHz 使用 ADC FIFO
连续采集路径。`ADCSamplingGetSampleRateHz()` 返回板级默认值 1 MHz，不代表每次
调用只能使用该频率。

普通直接采集同一时刻只能启动一路；未完成时重复启动或并发启动另一路会返回
`false`。需要同一触发窗口的两路数据时，应使用
`ADCSamplingStartSynchronizedCapture()`，详见
[ADC同步采集使用指南](ADC同步采集使用指南.md)。PA27 的窗口比较器触发采集则使用
`ADCSamplingStartThresholdInputCapture()`，当前限制为不超过 1 MHz。
