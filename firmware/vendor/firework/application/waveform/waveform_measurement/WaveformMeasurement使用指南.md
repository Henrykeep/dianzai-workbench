# Waveform Measurement 使用指南

`waveform_measurement` 把一次 ADC 采样窗口、FFT 分析和可选的 COMP + Timer 捕获
合并成统一的波形结果。初始化只注册资源并创建静态任务，不会在后台连续采集；
每次调用请求接口或进入显示页面才测量一次。

## 当前输入与接线

| 逻辑输入 | ADC 电压样本 | 可选周期捕获 | 当前默认 |
| --- | --- | --- | ---: |
| `PA27` | PA27 / ADC0.0 / DMA_CH5 | PA27 / COMP0 / TIMG12 | 开，1024 点、1 MHz |
| `PB19` | PB19 / ADC1.6 / DMA_CH6 | PA21 / COMP2 / TIMG6 | 关，启用后 1024 点、1 MHz |

第二路 ADC 已从旧设计的 PA21 改到 PB19。公开枚举
`WAVEFORM_MEASUREMENT_INPUT_PA21` 和旧 `APP_WAVEFORM_PA21_*` 宏仍作为 PB19 的
兼容别名，已有调用可以继续编译；新代码应使用
`WAVEFORM_MEASUREMENT_INPUT_PB19` 和 `APP_WAVEFORM_PB19_*`。

PA21 现在只用于 COMP2 捕获。若第二路同时需要 ADC 电压和硬件周期，外部应把同一
受保护信号同时送到 PB19 和 PA21；只接 PB19 时仍可通过 FFT 得到频率估计。

两路模拟输入都只能接受器件允许的单极性电压。负电压、高于 VDDA 的电压和高阻
高频源应先经过保护、偏置、衰减或缓冲。PA27 测外部信号前还要检查 J17 是否断开。

## 配置

当前单路配置：

```c
#define APP_ENABLE_WAVEFORM_MEASUREMENT (1U)

#define APP_ENABLE_WAVEFORM_PA27         (1U)
#define APP_WAVEFORM_PA27_SAMPLE_COUNT   (1024U)
#define APP_WAVEFORM_PA27_SAMPLE_RATE_HZ (1000000UL)

#define APP_ENABLE_WAVEFORM_PB19         (0U)
#define APP_WAVEFORM_PB19_SAMPLE_COUNT   (1024U)
#define APP_WAVEFORM_PB19_SAMPLE_RATE_HZ (1000000UL)

#define APP_FFT_REMOVE_DC                 (1U)
```

点数必须是 `64/128/256/512/1024/2048`。PA27 采样率为 1/2/4 MHz 三档；PB19
范围为 1～4 MHz且必须整除 4 MHz。采样窗口约为
`sample_count / sample_rate_hz`，FFT 原始间隔为
`sample_rate_hz / sample_count`。当前 PA27 窗口约 1.024 ms，bin 间隔约
976.5625 Hz。

前级频率比例和板级校准分别使用：

```c
APP_WAVEFORM_<PIN>_FREQUENCY_SCALE_NUMERATOR
APP_WAVEFORM_<PIN>_FREQUENCY_SCALE_DENOMINATOR
APP_WAVEFORM_<PIN>_FREQUENCY_CALIBRATION_NUMERATOR
APP_WAVEFORM_<PIN>_FREQUENCY_CALIBRATION_DENOMINATOR
```

最终频率会依次乘这两组比例。PA27 当前板级校准为 `125/124`，PB19 为 `1/1`。

## 一次请求的流程

```text
WaveformMeasurementRequestInput()
    ├─ 独占 ADC/FFT 工作区
    ├─ 启动对应 ADC DMA 和可选 COMP Capture
    ├─ ADC 收齐完整窗口
    ├─ 在 FFT 覆盖缓冲区前提取时域统计并保留最后 128 点
    ├─ 执行 FFT、选择频率来源、识别波形类型
    ├─ 发布结果并通知订阅者
    └─ 停止本次采集并释放共享资源
```

请求接口非阻塞：

```c
if (WaveformMeasurementRequestInput(
        WAVEFORM_MEASUREMENT_INPUT_PA27)) {
    /* 请求已启动，不代表结果已经完成。 */
}
```

同一路正在测量、共享 FFT 工作区被占用或功能未启用时会返回 `false`。用
`WaveformMeasurementGetRequestStatus()` 区分 `COLLECTING`、`COMPLETE`、
`START_FAILED`、`TIMEOUT`、`FFT_FAILED` 和 `CALCULATION_FAILED`；也可用
`WaveformMeasurementIsInputPending()` 查询是否仍在进行。

超时不是固定的单一毫秒值：代码按采样窗口估算总截止时间，并附加 1000 ms 余量；
若 1500 ms 内完全没有采样进度也会判定卡住。这样低速/长窗口不会被过早取消，
DMA 或中断失效时也不会让页面永久停在等待状态。

## 结果字段

`WaveformMeasurement` 的主要字段如下：

| 字段 | 单位/含义 |
| --- | --- |
| `minimum_millivolts` / `maximum_millivolts` | 本帧最小/最大电压，mV |
| `peak_to_peak_millivolts` | 峰峰值，mV |
| `average_millivolts` | 平均值，mV |
| `frequency_millihz` | 最终换算和校准后的频率，mHz |
| `period_microseconds` | 周期，us |
| `duty_cycle_permyriad` | 占空比，0～10000 对应 0～100% |
| `waveform_type` | DC、正弦、方波、三角、锯齿、谐波或未知 |
| `frequency_source` | Capture、FFT 或无有效来源 |
| `sample_count` / `sample_rate_hz` | 本次实际窗口参数 |
| `sequence` | 每次成功发布后递增 |
| `valid_mask` | 指明上述哪些字段有效 |
| `status` | `NOT_READY/PARTIAL/VALID/NO_SIGNAL` |

当前结果没有 RMS 字段。需要 RMS 时，应在 FFT 原地覆盖样本之前增加平方和统计，
并同步扩展结果结构、有效位、显示和上位机输出；不能把平均值当作 RMS。

读取前必须检查返回值、`status` 和 `valid_mask`：

```c
WaveformMeasurement result;

if (WaveformMeasurementCopyLatestInput(
        WAVEFORM_MEASUREMENT_INPUT_PA27, &result) &&
    (result.status == WAVEFORM_MEASUREMENT_STATUS_VALID) &&
    ((result.valid_mask & WAVEFORM_MEASUREMENT_VALID_FREQUENCY) != 0U)) {
    /* result.frequency_millihz 可用。 */
}
```

`WaveformMeasurementSetInput()` 只改变兼容读取接口
`WaveformMeasurementCopyLatest()` 的默认来源，不会停止另一输入、清除结果或发起测量。

## 频率来源选择

- 捕获结果足够新且与同一帧 FFT 基本一致时，使用 Capture；
- FFT 主峰低于第 8 bin 时，采样窗口内周期较少，仍优先相信有效 Capture；
- 更高频时，Capture 与 FFT 的差异不得超过 2 个 bin 或 2% 中的较大者；
- 捕获不可用或差异过大时回退到 FFT；
- 没有可靠交流分量时频率和周期有效位不置位。

PA27/TIMG12 为 4 MHz、0.25 us/tick；PA21/TIMG6 为 62.5 kHz、16 us/tick。
这里 PA21 只描述比较器捕获脚，不改变 PB19 是第二路 ADC 的事实。

## 波形类型识别

分类综合时域峰值分布、斜率/跳变、波峰因数和谐波能量，只适合基础稳态波形。
输入窗口周期太少、削顶、噪声大、前端带宽不足或混叠时可能得到 `HARMONIC` 或
`UNKNOWN`。类型识别用于菜单和 Mapping 的辅助决策，不能代替示波器或正式失真测量。

## 保留的最后 128 点

每次发布前保存本窗口最后最多 128 个原始 ADC 码。读取时必须携带本次结果的
`sequence`，并且该输入不能正在新测量：

```c
uint16_t samples[128];
size_t copied = 0U;
size_t first = result.sample_count > 128U
    ? result.sample_count - 128U : 0U;

(void)WaveformMeasurementCopyLatestInputSamples(
    result.source, result.sequence, first,
    samples, 128U, &copied);
```

序号不匹配时接口拒绝读取，避免把新结果元数据与旧样本混合。

## 结果订阅

最多可注册固定数量的观察者；相同 `callback/context` 重复注册视为成功：

```c
static void OnMeasurement(
    WaveformMeasurementInput_e input,
    const WaveformMeasurement *measurement,
    void *context)
{
    (void)input;
    (void)measurement;
    (void)context;
    /* 只做快速复制、置位或发送队列。 */
}

(void)WaveformMeasurementSubscribeResultReady(OnMeasurement, NULL);
```

普通请求的回调在 Waveform Measurement 任务上下文执行；外部样本分析的回调在调用
`WaveformMeasurementAnalyzeExternalSamples()` 的任务上下文执行。回调不得阻塞、
操作显示总线或再次发起可能争用同一工作区的分析。

## 外部样本分析

阈值触发等已经持有 ADC 数组的业务可以直接分析并发布：

```c
(void)WaveformMeasurementAnalyzeExternalSamples(
    WAVEFORM_MEASUREMENT_INPUT_PA27,
    samples, sample_count, sample_rate_hz, source_sequence);
```

时域统计使用全部真实样本；FFT 使用不超过实际点数的最大支持点数。少于 64 点时，
只为 FFT 补到 64 点，结果中的 `sample_count` 仍保留真实数量。外部样本没有同步
Capture 时，频率使用 FFT。

## 双路同步采集与相位

启用：

```c
#define APP_ENABLE_WAVEFORM_PA27 (1U)
#define APP_ENABLE_WAVEFORM_PB19 (1U)
#define APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE (1U)
#define APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE   (1U)
#define APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT   (1024U)
#define APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ (1000000UL)
```

同步模式中，无论请求哪一路，PA27/PB19 都使用同一 TIMG0 触发窗口采集并分别发布；
单路点数/速率不再决定本次硬件参数。调用
`WaveformMeasurementRequestSynchronizedPhase()` 后，在两路同一序列 FFT 完成时计算
主频相位差。

```c
WaveformSynchronizedPhaseMeasurement phase;

if (WaveformMeasurementCopyLatestSynchronizedPhase(&phase) &&
    phase.status == WAVEFORM_SYNCHRONIZED_PHASE_STATUS_VALID) {
    /* phase.phase_millidegrees：PB19 相对 PA27，正值表示超前。 */
}
```

两路主峰不一致、幅值过低或计算失败会分别得到
`FREQUENCY_MISMATCH`、`NO_SIGNAL` 或 `CALCULATION_FAILED`。固定相位偏差用
`APP_WAVEFORM_SYNCHRONIZED_PHASE_OFFSET_MILLIDEGREES` 校准。

## 显示页面操作

进入 PA27/PB19 波形或 FFT 页面会自动测量一次。波形页 S1 长按重测，S1 短按
切换 Y 轴量程，S2 短按切换来源；FFT 页 S1 长按重测，S1 短按切换来源，
S2 短按查看分量。两种页面均由 S2 长按返回。

## 调试与排查

可在 CCS Watch 中观察：

```text
waveform_measurement_request_statuses[0/1]
waveform_measurement_last_progress_ticks[0/1]
waveform_measurement_accepted_block_counts[0/1]
waveform_measurement_rejected_block_counts[0/1]
waveform_measurement_synchronized_phase_result
```

下标 0 为 PA27，下标 1 为 PB19；某些保留注释仍写 PA21。常见问题：

- PB19 没数据：确认 SysConfig 为 ADC1.6/PB19，不要按旧文档接 PA21；
- 一直 `TIMEOUT`：检查 TIMG0 触发、ADC/DMA 中断和采样进度计数；
- 频率跳变：检查 Capture 与 FFT 是否不一致、输入边沿是否有噪声或比较器阈值不合适；
- 频谱主峰偏移：检查采样率、窗口长度、混叠和前级频率比例；
- 第二路硬件频率无效：PB19 只提供 ADC，若需要 COMP 捕获还必须把信号接 PA21。
