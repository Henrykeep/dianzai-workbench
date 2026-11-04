# PA27/PB19 同步 ADC 配对采集

## 功能

`ADCSamplingStartSynchronizedCapture()` 会先配置 PA27（ADC0.0）和 PB19（ADC1.6）
的 DMA，再启动共享 TIMG0。只有两路 DMA 都完成后才调用回调，因此：

```text
pa27_samples[i] 与 pb19_samples[i] 属于同一个采样时刻
```

这为双通道相位差、增益比和同步波形比较提供了基础。

当 `APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE` 为 `1U` 时，
普通的 PA27/PB19 波形页面和 FFT 页面已经自动使用这条采集路径：从任一
页面发起测量，都会以本文件配置的公共点数和采样率同时采集两路，并分别发布
PA27、PB19 的测量结果。无需在菜单层额外调用本接口。

当前 `app_config.h` 默认将同步采集和同步相位都设为 `0U`，PB19 输入本身也默认
关闭；默认固件仍采用 PA27 单路按次采集。需要同步功能时必须显式打开 PB19、同步
采集，并按需打开同步相位三个开关。

## 使用步骤

1. 在 `application/app_config.h` 中确认 `APP_ENABLE_WAVEFORM_PA27` 和
   `APP_ENABLE_WAVEFORM_PB19` 都为 `1U`。
2. 在 `application/app_config.h` 中修改公共参数：

   ```c
   #define APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT   (1024U)
   #define APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ (1000000UL)
   ```

   两路使用同一个点数和采样率；再分配两个容量至少为该点数的 `uint16_t` 缓冲区。
3. 分别调用 `ADCSamplingInitInput(ADC_SAMPLING_INPUT_PA27)` 和
   `ADCSamplingInitInput(ADC_SAMPLING_INPUT_PB19)`。
4. 调用 `ADCSamplingStartSynchronizedCapture()`。
5. 在回调中只置位完成标志或发送任务通知，不要执行 FFT 等耗时处理。
6. 在任务上下文中处理两路缓冲区，完成后调用
   `ADCSamplingFinishSynchronizedCapture()` 回收硬件。

当前版本同步路径使用共享定时触发，采样率必须不超过板级默认采样率（当前
为 1 MHz），且必须满足底层采样率整除约束。2 MHz/4 MHz 的双路同步需要
进一步使用硬件 ADC 触发链或同步 AUTO_NEXT 配置，不能用两个软件启动替代。

## 示例

```c
static uint16_t pa27_samples[APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT];
static uint16_t pb19_samples[APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT];
static volatile bool pair_ready;

static void PairReady(uint32_t sequence, void *context)
{
    (void)sequence;
    (void)context;
    pair_ready = true;
}

/* 初始化阶段 */
(void)ADCSamplingInitInput(ADC_SAMPLING_INPUT_PA27);
(void)ADCSamplingInitInput(ADC_SAMPLING_INPUT_PB19);

/* 任务中启动一次 1024 点、1 MHz 配对采集 */
bool started = ADCSamplingStartSynchronizedCapture(
    pa27_samples, APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT,
    pb19_samples, APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT,
    APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT,
    APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ,
    PairReady, NULL);
```

回调执行后，任务确认 `pair_ready`，计算相位或其他指标，然后停止并回收
采集。若已开启 `APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE`，现有测量任务
会自动完成上述启动、处理和回收步骤；此示例仅用于独立模块调用或自定义功能页。

## 相位测量

将 `APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE` 设为 `1U`，显示菜单的
`FFT SPECTRUM -> PHASE PAIR` 会自动采集一帧配对数据并显示：

- `PB19 - PA27` 的主频相位差，单位为 0.001°；正值表示 PB19 超前；
- 两路主峰频率和采样点数必须一致，否则显示 `FREQ MISMATCH`；
- 任一路幅度过小会显示 `NO SIGNAL`，避免噪声被误判为相位；
- 可用 `APP_WAVEFORM_SYNCHRONIZED_PHASE_OFFSET_MILLIDEGREES` 做固定通道延迟校准。

代码调用方式如下：

```c
WaveformSynchronizedPhaseMeasurement phase;
(void)WaveformMeasurementRequestSynchronizedPhase();
/* 等待 PA27、PB19 请求都完成后： */
if (WaveformMeasurementCopyLatestSynchronizedPhase(&phase) &&
    (phase.status == WAVEFORM_SYNCHRONIZED_PHASE_STATUS_VALID)) {
    int32_t phase_millidegrees = phase.phase_millidegrees;
}
```
