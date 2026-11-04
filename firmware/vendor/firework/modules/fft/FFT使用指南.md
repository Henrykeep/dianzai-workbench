# FFT Module 使用指南

FFT Module 为 Application 提供 64～2048 点、Q15 实数输入频谱分析。实现使用
MSPM0 SDK 中的 CMSIS-DSP，不直接访问 DriverLib 或 ADC 外设，因此也可以被
其他 Application 复用。

## 1. 当前配置

| 项目 | 配置 |
| --- | --- |
| FFT 点数 | 64/128/256/512/1024/2048 |
| 输入数据 | N 个 `int16_t` Q15 实数样本，或 N 个无符号 ADC 原始样本 |
| 复数变换 | CMSIS-DSP `arm_cfft_q15()` |
| 幅值计算 | Q15 复数模长，结果原地写回复数工作区前半段 |
| 输出频带 | 33 个：直流 + 32 个压缩显示频带 |
| 窗函数 | 矩形窗或 Hann 窗 |
| 去直流 | 可配置，当前 FFT Analysis Module 默认启用 |
| 并发保护 | FreeRTOS 静态互斥锁 |

Q15 输入范围为 `-32768～32767`。输出幅值适合做相对比较、主峰搜索和
屏幕归一化显示；它没有直接校准为伏特、dBV 或 dBFS。

## 2. 频率换算

给定采样率 `Fs` 和 FFT 点数 `N`：

```text
bin 间隔 = Fs / N
bin k 的频率 = k × Fs / N
最高不混叠频率 = Fs / 2
```

例如 `Fs=1000 Hz`、`N=1024` 时，bin 间隔约为 `0.9766 Hz`，bin 512
对应 `500 Hz`。
`FFTResult.peak_frequency_millihz` 使用毫赫表示，并对最大 bin 左、中、右
三个幅值做定点抛物线插值，减小主峰不在整数 bin 中心时的量化误差。

## 3. 基本用法

```c
#include "modules/fft/fft.h"

static FFTInstance *fft;

bool MyFFTInit(void)
{
    static const FFTConfig config = {
        1000U,
        FFT_WINDOW_HANN,
        true
    };

    fft = FFTRegister(&config);
    return fft != NULL;
}

bool AnalyzeSamples(const int16_t samples[1024],
    FFTResult *result)
{
    return FFTAnalyzeQ15(
        fft, samples, 1024U, result);
}
```

`FFTAnalyzeQ15()` 要求样本数量是 64/128/256/512/1024/2048 之一，成功时返回：

- `magnitudes[0]`：直流分量。
- `magnitudes[1..32]`：把完整正频率半谱按区间最大值压缩成的 32 个显示频带。
- `peak_bin`：幅值最大的非直流 bin。
- `peak_magnitude`：主峰相对幅值。
- `peak_frequency_millihz`：经相邻三点抛物线插值后的主峰频率。
- `components[]`：完整半谱中不低于主峰5%的有效局部峰，最多保留最强16个，
  每项包含插值频率、幅值和原始 bin，并按频率升序排列。
- `component_count`：本帧实际提取到的有效频率分量数量。
- `point_count`：本次实际 FFT 点数。

## 4. 窗函数与去直流

`FFT_WINDOW_HANN` 会降低非整 bin 周期信号的频谱泄漏，适合通用频谱显示，
但会使主瓣变宽并改变幅值系数。`FFT_WINDOW_RECTANGULAR` 不修改样本，对刚好落在
bin 中心的信号分辨率更高，但对非整周期信号更容易泄漏。

Application 通过 `APP_FFT_REMOVE_DC=1U` 设置 `remove_dc=true`，此时会先
减去本次 N 点平均值，减少单电源 ADC 中点偏置对低频 bin 的影响。设置为 `0U`
可以保留直流分量，频谱页面会把 bin 0 显示为最左侧柱；设置为
`1U` 时页面保持从 bin 1 开始。两种设置的主峰搜索都跳过 bin 0。

## 5. 构建配置

CCS 工程已加入：

- CMSIS-DSP `Include` 目录。
- `ARM_MATH_CM0` 预定义符号。
- TI ARM Clang Cortex-M0+ 版 `arm_cortexM0l_math.a` 库。

如果新建另一个 CCS Build Configuration，需确认这三项也被继承，否则可能出现
`arm_cfft_q15` 或对应长度的 `arm_cfft_sR_q15_lenN` 未定义的链接错误。

## 6. 使用限制

- FFT 只能分析采样率一半以下的频率，输入端应根据带宽添加抗混叠低通滤波。
- 三点插值可以改善主峰估计，但不会增加 FFT 的真实频谱分辨率，也不等同于
  Capture 的周期测频精度。
- 当前为单个静态 FFT 实例。重复调用 `FFTRegister()` 会返回已有实例，不会重新配置。
- ADC DMA 可以与复数 FFT 共用工作区；共享期间必须通过 FFT Analysis 的预留接口
  串行化，不能同时执行 UART2 FFT。
- `FFTAnalyzeQ15()` 使用 FreeRTOS 互斥锁，应在任务上下文调用，不能在 ISR 中调用。
