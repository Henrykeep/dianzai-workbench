# ADC Module 使用指南

`modules/adc/adc.*` 是 BSP ADC 的线程安全封装，提供一次性 N 点 DMA、PA27
阈值触发、PA27/PB19 双路同步采集、采样率校验和原始值转毫伏接口；不提供后台
连续流读取。

```c
ADCInstance *adc = ADCRegister(ADC_DEVICE_INPUT_0);

bool started = ADCStartDirectCapture(
    adc, samples, 1024U, 1024U, 1000000UL,
    CaptureCompleteFromISR, NULL);

/* 测量任务处理完成后关闭硬件。 */
(void)ADCFinishDirectCapture(adc);
```

- `ADC_DEVICE_INPUT_0`：PA27 / ADC0.0 / DMA_CH5。
- `ADC_DEVICE_INPUT_1`：PB19 / ADC1.6 / DMA_CH6。
- `ADCIsSampleRateSupported()`：判断目标值是否不超过 4 MHz 且能整除 4 MHz 采样时钟。
- `ADCConvertRawToMillivolts()`：按 12 位满量程 4095、参考电压 3300 mV 换算。
- `ADCFinishDirectCapture()`：结束或中止采集，结束后保持停止。

阈值触发接口 `ADCStartThresholdTriggeredCapture()` 只支持 PA27，且采样率不能超过
板级默认 1 MHz。同步接口 `ADCStartSynchronizedCapture()` 同时采集 PA27 和 PB19，
当前也只使用不超过 1 MHz 的共享 TIMG0 定时触发路径。两种模式结束后分别调用
`ADCFinishThresholdTriggeredCapture()` 或 `ADCFinishSynchronizedCapture()` 回收硬件。

直接采集、阈值事件和同步完成回调均在 ADC/DMA ISR 中执行。回调中只应置标志或
通知任务，不要执行 FFT、串口发送或阻塞操作。
