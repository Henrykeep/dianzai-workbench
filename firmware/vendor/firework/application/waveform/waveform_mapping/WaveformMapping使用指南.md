# Waveform Mapping 使用指南

`application/waveform/waveform_mapping` 把 PA27 每次单次测量发布的频率、波形类型和
电压范围，自动映射到编译配置选择的 AD9833、AD9850 或 PA15 DAC 输出后端。

```text
PA27 → Waveform Measurement → Waveform Mapping ─┬→ AD9833 VOUT
                                                  ├→ AD9850 SIN / SQ
                                                  └→ PA15 DAC0
```

映射 Application 不创建额外任务。初始化时订阅 PA27 测量结果，回调在
Waveform Measurement 任务上下文执行。任何途径完成一次 PA27 测量都会触发映射，
包括 OLED/TFT 共用波形页、FFT PA27 页面、`PA27 MAPPING` 菜单和直接调用
`WaveformMeasurementRequestInput()`。

## 1. 编译配置

配置位于 `application/app_config.h`：

```c
#define APP_ENABLE_WAVEFORM_MAPPING (1U)

#define APP_WAVEFORM_MAPPING_BACKEND_DAC    (1U)
#define APP_WAVEFORM_MAPPING_BACKEND_AD9833 (0U)
#define APP_WAVEFORM_MAPPING_BACKEND_AD9850 (0U)
```

- `APP_ENABLE_WAVEFORM_MAPPING=0U`：不订阅结果，也不会自动修改输出。
- `DAC=1U`：映射到 PA15，必须启用 Waveform Output 的 DAC 后端。
- `AD9833=1U`：映射到外接 AD9833 VOUT，必须启用 DDS 后端。
- `AD9850=1U`：映射到外接 AD9850，必须启用 AD9850 输出后端。
- 三个后端开关必须且只能有一个为 `1U`，否则编译期报错。

映射还要求启用 `APP_ENABLE_WAVEFORM_MEASUREMENT` 和
`APP_ENABLE_WAVEFORM_PA27`。依赖不满足时会在编译期给出错误。

## 2. 波形映射能力

| PA27识别类型 | AD9833 | AD9850 | PA15 DAC |
| --- | --- | --- | --- |
| `DC` | 不支持，停止输出 | 不支持，停止输出 | 写入测得的平均电压并切换为 DC 模式；不会自动启用已关闭的 DAC |
| `SINE` | 正弦波 | 设置频率，使用模块 SIN 引脚 | Timer + DMA 查表正弦波 |
| `SQUARE` | 约50%占空比方波 | 设置频率，使用模块 SQ 引脚 | 约50%占空比方波 |
| `TRIANGLE` | 三角波 | 不支持，停止输出 | 三角波 |
| `SAWTOOTH` | 不支持，停止输出 | 不支持，停止输出 | 锯齿波 |
| `HARMONIC` | 不支持，停止输出 | 不支持，停止输出 | 不支持，停止输出 |
| `UNKNOWN` | 不支持，停止输出 | 不支持，停止输出 | 不支持，停止输出 |

周期波形频率由 `frequency_millihz` 四舍五入为整数 Hz。PA27 的时钟校准和
前级降频还原已经在 Waveform Measurement 中完成，映射直接使用最终频率。
低频时优先使用 COMP + Timer Capture；FFT 主峰达到第 8 bin
以上后，以 2 个 FFT bin 和 2% 中的较大值作为容差。Capture 与 FFT
差异超过该容差时自动改用 FFT，避免高频丢边沿导致 DDS 输出错误频率。

AD9833 只复制频率和基础波形类型，输出相位固定为 0°，不能复制输入幅度、直流
偏置或任意占空比。它只接受 `SINE`、`SQUARE` 和 `TRIANGLE`；识别结果为
`SAWTOOTH`、`HARMONIC` 或 `UNKNOWN` 时会立即停止 AD9833，并把映射状态设为
`WAVEFORM_MAPPING_STATUS_UNSUPPORTED_WAVEFORM`。PA15 DAC 会使用本次测得的
最小、最大电压作为输出范围，并通过
硬件 Sample Timer + DMA 输出周期波形。正弦波、三角波和锯齿波上限为
`62500 Hz`，方波上限为 `500000 Hz`；映射结果会按识别出的波形分别限幅到对应
上限，不会因高频输入关闭 DAC。

PA15 DAC 的周期波形配置会直接启动硬件输出。DC 映射的当前实现只调用
`WaveformOutputDACSetMillivolts()`：该接口会停止正在运行的 DMA 周期波形、写入平均
电压并把逻辑模式切换为 DC，但不会调用 `WaveformOutputDACStart()`。因此：

- 如果 DAC 此前正在输出周期波形，写入 DC 电压后 PA15 会继续保持启用；
- 如果 DAC 此前处于关闭状态（包括系统刚初始化完成时），映射状态可以变为
  `WAVEFORM_MAPPING_STATUS_APPLIED`，但 PA15 仍然没有物理输出；
- 需要在关闭状态下输出该 DC 电压时，应用还必须调用
  `WaveformOutputDACStart()`。

AD9850 映射仅接受 `SINE` 和 `SQUARE`：二者都会把测得频率写入 AD9850；正弦波
应从模块的 `SIN` 引脚取出，方波应从 `SQ` 引脚取出。模块两个引脚的物理输出不由
软件开关切换，映射保存的是当前应使用的输出端。`DC`、三角波、锯齿波、谐波和未知
类型会停止 AD9850。频率高于 `APP_AD9850_MAXIMUM_FREQUENCY_HZ` 时同样停止输出，
不会截断到上限。

## 3. 显示菜单操作

启用映射后，主菜单增加：

```text
PA27 MAPPING
  MEASURE PA27
  OUTPUT OFF
```

页面标题会根据编译配置显示 `PA27 TO AD9833`、`PA27 TO AD9850` 或 `PA27 TO DAC`。
选择 `MEASURE PA27` 只表示测量请求成功启动；默认 1024 点/1 MHz 的原始采集
窗口约 1.024 ms，随后还需要 FFT 和任务处理时间，结果发布后自动更新输出。
选择 `OUTPUT OFF` 会停止当前映射后端。

## 4. 状态接口

```c
#include "application/waveform/waveform_mapping/waveform_mapping.h"

WaveformMappingStatus_e status = WaveformMappingGetStatus();
uint32_t sequence = WaveformMappingGetLastSequence();
```

| 状态 | 含义 |
| --- | --- |
| `WAVEFORM_MAPPING_STATUS_UNINITIALIZED` | 尚未初始化。 |
| `WAVEFORM_MAPPING_STATUS_READY` | 已订阅PA27结果，等待测量。 |
| `WAVEFORM_MAPPING_STATUS_APPLIED` | 最近一份结果已经成功写入所选后端；DAC DC 映射时不代表已关闭的 DAC 被自动启用。 |
| `WAVEFORM_MAPPING_STATUS_INVALID_RESULT` | 必需的有效位、幅值或结果来源不完整。 |
| `WAVEFORM_MAPPING_STATUS_UNSUPPORTED_WAVEFORM` | 所选后端不能生成该波形类型。 |
| `WAVEFORM_MAPPING_STATUS_FREQUENCY_OUT_OF_RANGE` | 频率为0或超出后端范围。 |
| `WAVEFORM_MAPPING_STATUS_OUTPUT_ERROR` | 后端停止、配置或启动失败。 |

`WaveformMappingGetLastSequence()` 返回最近处理的 PA27
`WaveformMeasurement.sequence`，可用于确认映射处理的是哪次测量。

## 5. 安全行为

遇到无效结果、不支持的波形、频率越界或硬件写入失败时，映射 Application 会
停止所选后端，避免继续输出上一份已经过期的波形。系统进入
`ApplicationEnterSafeState()` 时，Waveform Output 也会统一关闭 DAC、AD9833 和 AD9850。
