# FFT Analysis 使用指南

FFT Analysis 位于 Module 层，统一保存 PA27、PB19、UART2 和 UART3 四种来源的
最新频谱结果。PA27/PB19 由 Waveform Measurement 收齐 ADC 窗口后执行本地
CMSIS-DSP Q15 FFT；UART2 每累计 64 个有符号采样执行一次本地 FFT；UART3 则接收
外部控制器已经计算好的 128 点频谱，不在下位机重复执行 FFT。

## 1. 数据链路和当前默认值

```text
PA27 / ADC0.0 / 1024 点 DMA ──本地 Hann FFT──┐
PB19 / ADC1.6 / 1024 点 DMA ──本地 Hann FFT──┤
UART2 / PB16 / 64 个 int16 ───本地 Hann FFT──├─ 独立 FFTAnalysisResult
UART3 / lspect*、spect*、spectrum / 128 点发布结果 ─┘
```

当前 `application/app_config.h` 的默认配置为：

- PA27：启用，1 MHz、1024 点，bin 间隔约 `976.5625 Hz`，范围 0～500 kHz；
- PB19：默认关闭；启用后的默认参数同为 1 MHz、1024 点；
- UART2：默认关闭；启用后按 100 samples/s、64 点分析，bin 间隔 1.5625 Hz；
- UART3 外部频谱：启用；`lspecta/lspectb` 接收 `start + 128 点 + end`，
  `specta/spectb` 接收 800 个裸数字，`spectrum` 接收 1024 个裸数字；后两类在接收
  期间按桶最大值压缩为 128 点。最终点 0～127 等间隔对应 0～500 kHz，再压缩为
  33 个显示频带；
- `APP_FFT_REMOVE_DC=1U`：本地 FFT 先减去本帧平均值，显示 bin 1～32；改为
  `0U` 才保留直流并显示 bin 0～31；
- 所有来源的交流主峰搜索都忽略第 0 点。

本地 FFT 的主峰频率会在最大 bin 左、中、右三个复数幅值之间做抛物线插值，减小
非整 bin 信号的频率量化误差；频谱柱仍保持原始 FFT 分辨率。UART3 外部频谱没有
本地下位机复数结果，主峰只能按 128 点中的最大非直流点换算。

## 2. 初始化与资源

FFT Analysis 由 Waveform Measurement Application 统一初始化，当前默认已经启用：

```c
#define APP_ENABLE_WAVEFORM_MEASUREMENT (1U)
```

初始化会准备最大 2048 点的共享 ADC/FFT 工作区。ADC DMA 可以先写入工作区，
Waveform Measurement 保存时域统计和最后 128 点后，再原地展开为复数输入。PA27
和 PB19 通过 `WaveformMeasurementRequestInput()` 按次启动；同步采集默认关闭，
打开 `APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE` 后两路才使用同一个触发窗口。

只有 `APP_ENABLE_UART2=1U` 时才创建 UART2 FFT 任务及三份 64 点静态缓冲区；关闭
UART2 会在编译期裁掉这些资源。UART3 的带 `start/end` 帧与固定长度裸数字流由
Serial Communication Application 分别解析；只有点数和结束条件完整满足后，才通过
`FFTAnalysisPublishExternalSpectrum()` 一次性发布。

Module 内部或独立测试代码仍可以直接调用：

```c
#include "modules/fft/fft_analysis.h"

if (!FFTAnalysisInit()) {
    /* 互斥量、共享工作区或可选 UART2 静态任务初始化失败。 */
}
```

## 3. 读取和发布结果

```c
FFTAnalysisResult result;

if (FFTAnalysisCopyLatestResult(
        FFT_ANALYSIS_INPUT_PB19, &result)) {
    /* peak_frequency_millihz 是 PB19 本地 FFT 的主峰频率。 */
    /* components[0..component_count-1] 是有效频率分量。 */
}
```

`FFT_ANALYSIS_INPUT_PA21` 只是 `FFT_ANALYSIS_INPUT_PB19` 的旧名称兼容别名，当前
硬件实际为 PB19/ADC1.6。四种来源各自保存独立快照：

- `point_count`：本次本地 FFT 点数；UART3 当前先把 800/1024 点裸响应压缩为
  128 点再发布，因此五种 UART3 频谱请求的该字段都为 `128U`；
- `sample_rate_hz`：本地分析采样率；UART3 按 0～500 kHz 横轴记录为 1 MHz；
- `source_sequence`：产生本结果的 ADC、UART2 帧或 UART3 事务序号；
- `sequence`：该来源每成功发布一份新结果递增一次；
- `magnitudes[0..32]`：用于显示的 DC + 32 个压缩频带；
- `components[]`：本地 FFT 最多 16 个有效局部峰；外部发布 API 也允许调用方附带
  最多 16 个分量，但当前 UART3 频谱事务传入 0 个，`compa/compb` 走独立文本页面，
  不会自动合并进 UART3 频谱快照。

UART2 采样由串口应用的样本订阅机制分发，Waveform Measurement 注册消费者后提交：

```c
(void)FFTAnalysisSubmitUART2Sample(sample);
```

每收齐 64 点生成一帧 FFT。UART2 帧本身不携带采样率，频率换算固定使用
`FFT_ANALYSIS_UART2_SAMPLE_RATE_HZ`，必须与发送端节拍一致。若
`APP_ENABLE_UART2=0U`，提交接口固定返回 `false`。

## 4. 显示菜单行为

OLED 和 TFT 共用同一套 `FFT SPECTRUM` 页面逻辑，只显示编译配置已经启用的来源。
当前默认可使用 PA27 本地 FFT，以及 UART3 的 `LSPECT A/B`、`SPECT A/B` 和
`SPECTRUM` 外部频谱；PB19 和 UART2 默认关闭。

- S1 短按：按 PA27 → PB19 → UART2 → UART3 的已启用来源顺序切换，并请求新一帧；
- S1 长按：保持当前来源，重新请求一帧；
- S2 短按：进入或翻页查看有效频率分量，末页后返回频谱柱；
- S2 长按：取消仍在等待的 UART3 请求并返回上一页。

本地 FFT 的分量列表每页最多显示 3 个频率，最多保留 16 个高于主峰 5% 的有效
局部峰。当前 UART3 频谱快照没有附带分量，因此 S2 分量页显示 `NO COMPONENT`；
`compa/compb` 的多行结果在 UART3 文本页面查看。取得结果后页面冻结，只有重新请求
或切换来源才更新。

ADC 频谱请求会复用同一输入正在执行的 Waveform Measurement。ADC 测量状态已经
`COMPLETE` 却没有新 FFT 时，页面报告 `FFTERR`。UART2 会等到新的 64 点；UART3
对 `lspect*` 会等待完整 128 点和 `end`，对裸频谱命令会等待各自固定点数；串口
事务状态会把 `error`、格式错误或本地超时转换为失败页面，不会永久停在
`WAITING FFT`。

## 5. 限制

- 本地 FFT 频率间隔为 `采样率 / 点数`；增加点数可缩小 bin 间隔，但会增加采集
  时间和 RAM 占用。
- PA27/PB19 输入必须位于 GND～VDDA，外部交流信号通常需要衰减、限幅和直流偏置。
- 当前 PA27 默认 1 MHz/1024 点窗口约为 1.024 ms；PB19 启用后的默认窗口相同。
  测几十或几百 Hz 时应降低对应 `APP_WAVEFORM_PA27_SAMPLE_RATE_HZ` 或
  `APP_WAVEFORM_PB19_SAMPLE_RATE_HZ`。
- 接近 500 kHz 的输入必须使用合适的模拟前端和抗混叠滤波；奈奎斯特理论上限不
  等于所有接线和负载条件下都能准确测量。
- 若 COMP 阈值不在波形范围内，Waveform Measurement 会使用本地 FFT 主峰作为
  频率回退值。第二路 ADC 在 PB19，而第二路 COMP 仍在 PA21，不能把 PA21 捕获结果
  当成 PB19 同引脚测量。
- UART2 发送节拍不均匀或与固定 100 samples/s 不一致时，显示频率会产生比例误差。
- UART3 频谱的横轴和峰值幅度取决于上位控制器协议；下位机只检查完整帧、压缩显示
  并保存结果，不会提高外部 128 点频谱的真实分辨率。
