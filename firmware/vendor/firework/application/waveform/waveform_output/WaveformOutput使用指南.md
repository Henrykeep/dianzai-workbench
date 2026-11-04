# Waveform Output 使用指南

`application/waveform/waveform_output` 是工程统一的波形输出 Application，负责初始化并
管理 PA15 DAC、外接 AD9833 DDS 和 AD9850 三个可选后端。本 Application 统一它们的
编译配置、初始化和业务接口；实际应用一次只接 AD9833 或 AD9850 中的一个模块。

## 1. 输出后端

| 后端 | 输出位置 | 能力 |
| --- | --- | --- |
| PA15 DAC0 | PA15 | 正弦/三角/锯齿波1～62.5 kHz，方波1～500 kHz |
| AD9833 DDS | 模块 VOUT；PB9/PB8/PB6 为控制线 | 正弦、三角波、方波，频率和相位控制 |
| AD9850 | 模块 SIN/SQ；PB9/PB8/PB5/PA1 为控制线 | 正弦与方波，默认上限40 MHz |

DAC0 的外部输出脚固定为 PA15。PA15 原来用于 OLED SCL，因此本工程已经将
OLED 已改到独立的 I2C0 PA31/PA28。烧录新程序前需要同步修改实物接线：

```text
OLED SCL -> PA31
OLED SDA -> PA28
DAC OUT  -> PA15
GND      -> 被测设备 GND
```

MPU6050 不使用 OLED 的 I2C 引脚；其独立 I2C1 接线为 `PB2=SCL`、`PB3=SDA`。

PA15 是模拟输出，不能直接驱动电机、继电器、蜂鸣器或其他大电流负载。需要带载时，
应在后级增加运算放大器或专用驱动电路。

## 2. 分层结构

```text
application/waveform/waveform_output  统一业务接口、配置和初始化
        ├─ modules/dac/dac_output  PA15 周期波形与缓冲区回填任务
        │       └─ modules/dac     线程安全 DAC 和单位换算
        └─ modules/dds/dds_output  AD9833 便捷输出服务
                └─ modules/dds     通用 DDS 和芯片后端
        ↓
BSP DAC / SPI
        ↓
TI DriverLib + SysConfig
```

Application 和 Module 层不直接访问 DriverLib。以后更换引脚、参考源或 DAC 外设时，
只需修改 SysConfig 和 BSP 映射。

## 3. 编译配置与初始化

`ApplicationInit()` 已经调用：

```c
if (!WaveformOutputInit()) {
    return FRAMEWORK_STATUS_ERROR;
}
```

配置位于 `application/app_config.h`：

```c
#define APP_ENABLE_WAVEFORM_OUTPUT     (1U)
#define APP_ENABLE_WAVEFORM_OUTPUT_DAC (1U)
#define APP_ENABLE_WAVEFORM_OUTPUT_DDS (0U)
#define APP_ENABLE_WAVEFORM_OUTPUT_AD9850 (0U)
```

三个输出后端使用独立的 `1U/0U` 开关。总开关为 `0U` 时会自动屏蔽全部后端；
总开关为 `1U` 时至少启用一个后端。初始化只写入默认参数并准备资源：DAC 模拟输出
保持关闭，AD9833 保持 RESET/SLEEP，AD9850 保持 RESET。

```c
(void)WaveformOutputDACSetMillivolts(1650U);
```

应用发生错误或调度器未能启动时，可调用 `WaveformOutputStopAll()` 按 DDS、DAC
逆序关闭全部后端；顶层 `Application` 已自动执行该安全处理。

## 4. DAC Application 接口

应用通常只需要包含：

```c
#include "application/waveform/waveform_output/waveform_output.h"
```

### 按毫伏设置

```c
/* 标称输出约 1.20 V。 */
if (!WaveformOutputDACSetMillivolts(1200U)) {
    /* 未初始化或参数超过 3300 mV。 */
}
```

合法范围为 `0～3300 mV`。该数值按 3.3 V 标称 VDDA 换算，真实输出会随实际
VDDA、负载和 DAC 误差变化。

### 按原始值设置

```c
/* 12 位半量程，标称约 1.65 V。 */
(void)WaveformOutputDACSetRaw(2048U);
```

合法范围为 `0～4095`。换算关系为：

```text
输出电压 ≈ 原始值 × VDDA / 4095
原始值   ≈ 目标毫伏 × 4095 / 3300
```

### 按百分比设置

```c
/* 标称输出满量程的 25%。 */
(void)WaveformOutputDACSetPercent(25U);
```

合法范围为 `0～100`。

### 输出周期波形

```c
static const WaveformOutputDACConfig waveform_config = {
    WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE,
    10U,   /* 10 Hz */
    500U,  /* 最低 0.5 V */
    2800U  /* 最高 2.8 V */
};

(void)WaveformOutputDACConfigure(&waveform_config);
```

支持以下模式：

```c
WAVEFORM_OUTPUT_DAC_MODE_SINE
WAVEFORM_OUTPUT_DAC_MODE_SQUARE
WAVEFORM_OUTPUT_DAC_MODE_TRIANGLE
WAVEFORM_OUTPUT_DAC_MODE_SAWTOOTH
```

四种内置波形统一使用固定采样率双缓冲 DDS：默认由
`APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ=1000000UL` 保持1 MSPS，正弦波的32点
基础表会先插值成1024级幅值表。正弦波、三角波和锯齿波的频率合法范围为
`1～62500 Hz`，每周期不少于16点；方波为 `1～500000 Hz`。当
`APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES=1U` 时，方波每个半周期固定使用整数个
采样点，高、低电平长度相等；请求频率可能被量化。设为 `0U` 会恢复平均频率
优先模式。
最小和最大电压必须满足 `0 <= minimum < maximum <= 3300 mV`。四种波形的周期都可
跨越多个1024点 DMA 缓冲区，并在合法频率范围内保持固定更新率。硬件定时器决定采样
时刻，`DACRefill` 任务只在收到 DMA 缓冲区完成通知后生成下一块数据，不用任务延时控制
采样周期。

请求频率不一定能由固定采样率和相位步进完全表示。调用
`WaveformOutputDACGetActualFrequencyMillihz()` 可以读取实际硬件输出频率。
`WaveformOutputDACGetStreamRefillMissCount()` 返回回填任务未赶上下一轮 DMA 而触发安全
停机的累计次数；正常运行应保持为0。

调用 `WaveformOutputDACSetRaw()`、`WaveformOutputDACSetMillivolts()` 或
`WaveformOutputDACSetPercent()` 会停止周期波形并切回直流模式。

### 启停和读取设置值

```c
uint16_t raw_value;
uint16_t millivolts;
WaveformOutputDACConfig waveform_config;

(void)WaveformOutputDACStop();
(void)WaveformOutputDACStart();

(void)WaveformOutputDACGetRaw(&raw_value);
(void)WaveformOutputDACGetMillivolts(&millivolts);
(void)WaveformOutputDACGetConfig(&waveform_config);

if (WaveformOutputDACIsEnabled()) {
    /* DAC 当前已启用。 */
}
```

读取接口返回的是软件最近一次成功设置的值，不是通过 ADC 测得的 PA15 实际电压。

## 5. DDS 与 AD9850 Application 接口

### AD9833

```c
(void)WaveformOutputDDSSetFrequency(100000UL);
(void)WaveformOutputDDSSetPhase(90U);
(void)WaveformOutputDDSSetWaveform(
    WAVEFORM_OUTPUT_DDS_WAVEFORM_TRIANGLE);
(void)WaveformOutputDDSStop();
(void)WaveformOutputDDSStart();
```

AD9833 参考时钟默认从 `bsp/board_config.h` 读取 25 MHz，频率范围为 1 Hz～MCLK/2，相位范围为
0～359°。DDS 的 VOUT 是带直流偏置的小幅模拟输出，不是 PA15 DAC，也不是
3.3 V 逻辑输出；需要指定幅值、偏置或负载能力时应增加外部调理电路。

### AD9850

```c
(void)WaveformOutputAD9850SetFrequency(1000000UL);
(void)WaveformOutputAD9850SetWaveform(
    WAVEFORM_OUTPUT_AD9850_WAVEFORM_SINE);
(void)WaveformOutputAD9850Start();

WaveformOutputAD9850State state;
(void)WaveformOutputAD9850GetState(&state);
(void)WaveformOutputAD9850Stop();
```

频率下限为 1 Hz，上限由 `APP_AD9850_MAXIMUM_FREQUENCY_HZ` 决定，当前为 40 MHz；
参考时钟当前为 125 MHz。`SINE`/`SQUARE` 表示业务应观察模块的 SIN/SQ 物理输出端，
不是软件在两个脚之间切换模拟开关。PB9/PB8 与 AD9833 共用，PB5 为 FQ_UD，PA1
为 RESET。默认两个外部 DDS 后端都关闭，通常只安装并启用实际连接的一种。

## 6. 显示菜单控制

主菜单会按编译开关显示 DAC、AD9833 和 AD9850 的独立物理输出页面。当前默认只有
`DAC OUTPUT`：

```text
DAC OUTPUT
  OUTPUT OFF
  DC LEVEL
    0.50V / 1.00V / 1.65V / 2.50V / 3.00V
  LOWER LIMIT
    0.00 / 0.50 / 1.00 / 1.50 / 2.00 / 2.50 / 2.80 / 3.00 / 3.30 V
  UPPER LIMIT
    0.00 / 0.50 / 1.00 / 1.50 / 2.00 / 2.50 / 2.80 / 3.00 / 3.30 V
  SINE / TRIANGLE / SAWTOOTH
    1 / 10 / 100 Hz，1 / 5 / 10 / 20 / 31.25 / 62.5 kHz
  SQUARE
    上述档位，另含 500 kHz
```

周期波形默认使用 `0.50～2.80 V`。上下限可分别设置为菜单中的档位，
但必须满足 `0 <= 下限 < 上限 <= 3.30 V`；无效组合会拒绝保存。
输出周期波形时修改任一上下限会立即重新生成 DMA 查找表，并保持当前波形和频率。
选择直流或周期波形后只显示结果，不会自动跳转到 PA27 页面。
PA27 默认为 1024 点/1 MHz。回环测试前应将 LaunchPad `J17 OFF`，
避免板载光电二极管影响 PA27。

波形页面中：S1 短按向上切换 Y 轴量程，S1 长按重新测量当前来源，S2 短按
循环切换数据来源，S2 长按返回。当前没有 X 轴倍率切换。

`DDS OUTPUT` 页面继续提供启停、正弦/三角/方波、1 Hz～1 MHz 常用频率和
0/45/90/180/270° 相位预设。上电初始化保持 RESET/SLEEP；波形、频率和相位
菜单只修改配置，选择 `OUTPUT ON` 后才开始输出。DDS 已经输出时修改参数会
立即生效。菜单只调用 `WaveformOutput...()`，不直接依赖 Module。

启用 `APP_ENABLE_WAVEFORM_MAPPING` 后，主菜单还会出现 `PA27 MAPPING`。
它发起一次 PA27 测量，并在结果发布后自动更新配置选择的 DAC、AD9833 或 AD9850 后端；
详细限制见 `application/waveform/waveform_mapping/WaveformMapping使用指南.md`。

## 7. Module 接口

周期 DAC 服务位于 `modules/dac/dac_output.h`，DDS 便捷服务位于
`modules/dds/dds_output.h`。一般 Application 不应直接包含它们；只有新的
波形输出业务确实需要绕过统一门面时才直接调用 Module。

更底层的通用 DAC 注册接口仍位于 `modules/dac/dac.h`：

```c
static const DACConfig config = {
    0U,     /* initial_raw_value */
    true    /* start_enabled */
};

DACInstance *dac = DACRegister(DAC_DEVICE_OUTPUT_0, &config);
if (dac != NULL) {
    (void)DACWriteMillivolts(dac, 2500U);
}
```

同一逻辑设备重复注册时会返回已有实例。Module 使用静态互斥锁保护写入和状态修改，
可在不同 FreeRTOS 任务中调用，但不要在中断服务函数中调用这些接口。

## 8. 输出精度说明

- 电压换算以 `3300 mV` 为标称参考；如果板上 VDDA 不是精确 3.3 V，输出会同比变化。
- DAC 在接近 0 V 和 VDDA 的电源轨附近存在输出摆幅限制，满量程不等于一定能精确
  达到 3.300 V。
- 负载阻抗过低会导致输出下降。测量时建议先使用万用表或高阻输入示波器。
- 需要精确输出时，应测量实际 VDDA，并根据实测结果做软件校准。

## 9. 常见问题

### DAC 有输出，但 OLED 不亮

确认 OLED SCL 已从原来的 PA15 改接到 PA31。PA15 现在专用于 DAC0，不能继续作为
OLED 时钟脚。

### 设置 3300 mV 后测不到精确 3.3 V

这是参考电压误差、DAC 增益/偏移误差和输出摆幅共同造成的正常现象。先测量 VDDA，
并确保 PA15 没有连接低阻负载。

### 调用设置函数返回 false

检查是否已经调用 `WaveformOutputInit()`，并确认原始值不超过 `4095`、毫伏值不超过
`3300`、百分比不超过 `100`。

## 10. UART0 调试输出

统一 Application 的调试开关位于 `waveform_output.c`：

```c
#define WAVEFORM_OUTPUT_DEBUG_OUTPUT_ENABLED (1U)
```

启用后会输出 Application 初始化、就绪或错误提示，例如：

```text
WAVEFORM OUTPUT INIT
WAVEFORM OUTPUT READY DAC
```

DAC 波形由硬件 Sample Timer 和 DMA 输出，不会逐点打印。关闭该开关不影响 DAC
输出，并且该开关仍受 `app_config.h` 中 `APP_ENABLE_UART0_DEBUG` 总开关控制。
