/* 阅读配置时建议先看功能总开关，再看该功能对应的硬件和参数配置。 */
#ifndef APP_CONFIG_H
#define APP_CONFIG_H

/**
 * @file app_config.h
 * @brief Application 层功能开关和产品参数的统一入口。
 *
 * 快速上手
 * --------
 * 1. 初次使用时，优先只修改各节开头的 APP_ENABLE_* 总开关。
 * 2. 确认功能可以运行后，再调整采样率、舵机脉宽等参数。
 * 3. 修改后执行 Project Clean 和完整 Build；配置冲突会在编译期直接报错。
 * 4. CCS 可以用 -D宏名=值覆盖这里的默认值；因为每项都有 #ifndef，
 *    无需维护多份 app_config.h。
 *
 * 数值约定
 * --------
 * - ENABLED/APP_ENABLE_*：只允许 0U（关闭）或 1U（开启）。
 * - *_HZ：频率，单位 Hz；*_US：时间，单位 us；*_DEGREES：角度，单位度。
 * - OUTPUT_0/OUTPUT_1：逻辑通道 0/1，具体引脚写在对应配置节中。
 * - 本文件只选择 Application；真正的外设引脚和时钟仍由 blink_led.syscfg 配置。
 *
 * 当前默认启动内容
 * ----------------
 * - PA15 DAC 输出服务，初始化后保持安全关闭；
 * - PA23/PA24 两路舵机当前关闭，舵机任务自动裁剪；
 * - 4×4 矩阵键盘扫描任务（10 ms 周期）；
 * - OLED 菜单，上电进入 MAIN MENU；
 * - UART、ADC 波形测量/映射、MPU6050、Servo Control 和电机默认关闭；
 * - 菜单通用 PWM 页面因舵机关闭而自动启用。
 *
 * 主要依赖和冲突
 * --------------
 * - ADC JustFloat 必须启用 UART2，并启用所选 PA27/PB19 输入。
 * - Waveform Mapping 依赖 Waveform Measurement、PA27 和所选输出后端。
 * - OLED 和 TFT 必须且只能选择一种显示后端。
 * - Servo Control 与菜单的通用 PWM 共用 TIMG7，不能同时启用。
 * - 详细配置示例见 application/编译配置使用指南.md。
 */

/* 仅供本文件编译期校验使用，文件末尾会取消定义。 */
#define APP_CONFIG_IS_BOOLEAN(value) \
    (((value) == 0U) || ((value) == 1U))

/* ========================================================================== */
/* 1. Waveform Measurement：PA27/PA21 波形测量                              */
/* application/waveform/waveform_measurement/                                */
/* ========================================================================== */

/* 总开关：组合 ADC Sampling、FFT、COMP + Timer Capture 和测量任务。 */
#ifndef APP_ENABLE_WAVEFORM_MEASUREMENT
#define APP_ENABLE_WAVEFORM_MEASUREMENT (1U)
#endif

/**
 * 两路同步 ADC 配对采集接口开关：
 * 1U 时保留 PA27/PB19 共用 TIMG0 触发的同步采集配置；0U 时不启用。
 * 当前同步路径用于一次性配对采集，采样率上限为共享定时器默认 1 MHz，
 * 两个缓冲区同一索引对应同一采样时刻，适合后续相位差测量。
 * 开启后，PA27/PB19 波形页和 FFT 页的任意一次测量都会自动改为双路
 * 配对采集；单路的采样点数和采样率配置不参与实际采样。
 */
#ifndef APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE
#define APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE (0U)
#endif

/**
 * 双路同步相位测量开关：
 * 1U：每次同步采集后计算“PB19 相对 PA27”的主频相位差；
 * 0U：保留双路同步采集，但不计算和显示相位差。
 * 正值表示 PB19 超前 PA27，负值表示 PB19 滞后 PA27。
 */
#ifndef APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE
#define APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE (0U)
#endif

/*
 * 相位固定偏差校准，单位 0.001°，允许范围 -180000～180000。
 * 例如实测同相信号始终为 +2.350°，可填 (-2350) 进行归零。
 */
#ifndef APP_WAVEFORM_SYNCHRONIZED_PHASE_OFFSET_MILLIDEGREES
#define APP_WAVEFORM_SYNCHRONIZED_PHASE_OFFSET_MILLIDEGREES (0)
#endif

/* 双路同步采集的公共采样点数；PA27 和 PB19 必须使用相同数量。 */
#ifndef APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT
#define APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT (1024U)
#endif

/* 双路同步采集的公共采样率；当前同步触发路径最高支持 1 MHz。 */
#ifndef APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ
#define APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ (1000000UL)
#endif

/**
 * FFT 去直流开关，统一作用于 PA27、PA21 和 UART2：
 * 1U：FFT 前减去本帧平均值，推荐用于带直流偏置的单电源 ADC 信号。
 * 0U：保留直流分量，频谱页最左侧显示 bin 0。
 * 两种设置的主峰搜索都跳过 bin 0，避免直流改变标题中的交流频率。
 */
#ifndef APP_FFT_REMOVE_DC
#define APP_FFT_REMOVE_DC (1U)
#endif

/* ------------------------------ 输入 0：PA27 ------------------------------ */

/* PA27 = ADC0.0 + COMP0/TIMG12；也可在测量关闭时单独供 JustFloat 使用。 */
#ifndef APP_ENABLE_WAVEFORM_PA27
#define APP_ENABLE_WAVEFORM_PA27 (1U)
#endif

/* 单次测量及 FFT 点数：只允许 64～2048 范围内的 2 的幂。 */
#ifndef APP_WAVEFORM_PA27_SAMPLE_COUNT
#define APP_WAVEFORM_PA27_SAMPLE_COUNT (1024U)
#endif

/**
 * PA27高速采样率：可选 1000000/2000000/4000000 Hz，默认 1 MHz。
 * 三档都使用一次性连续 N 点 DMA；提高采样率会扩大可观察带宽，但相同点数下
 * 采集窗口会缩短、FFT bin 间隔会增大。
 */
#ifndef APP_WAVEFORM_PA27_SAMPLE_RATE_HZ
#define APP_WAVEFORM_PA27_SAMPLE_RATE_HZ (1000000UL)
#endif

/**
 * 模拟前级频率比例：原始频率 = 测得频率 × NUMERATOR / DENOMINATOR。
 * 例如前级把频率除以 10，应配置为 10UL / 1UL。
 */
#ifndef APP_WAVEFORM_PA27_FREQUENCY_SCALE_NUMERATOR
#define APP_WAVEFORM_PA27_FREQUENCY_SCALE_NUMERATOR (1UL)
#endif

#ifndef APP_WAVEFORM_PA27_FREQUENCY_SCALE_DENOMINATOR
#define APP_WAVEFORM_PA27_FREQUENCY_SCALE_DENOMINATOR (1UL)
#endif

/**
 * 板级测量校准：校准频率 = 比例换算后频率 × NUMERATOR / DENOMINATOR。
 * 当前开发板按 500 Hz 输入测得约 496 Hz，使用 125/124 修正。
 */
#ifndef APP_WAVEFORM_PA27_FREQUENCY_CALIBRATION_NUMERATOR
#define APP_WAVEFORM_PA27_FREQUENCY_CALIBRATION_NUMERATOR (125UL)
#endif

#ifndef APP_WAVEFORM_PA27_FREQUENCY_CALIBRATION_DENOMINATOR
#define APP_WAVEFORM_PA27_FREQUENCY_CALIBRATION_DENOMINATOR (124UL)
#endif

/* ------------------------------ 输入 1：PB19 ------------------------------ */

/* PB19 = ADC1.6；避开 LaunchPad 上被 C7 交流旁路到 GND 的 PA21/VREF-。 */
#ifndef APP_ENABLE_WAVEFORM_PB19
#ifdef APP_ENABLE_WAVEFORM_PA21
#define APP_ENABLE_WAVEFORM_PB19 (APP_ENABLE_WAVEFORM_PA21)
#else
#define APP_ENABLE_WAVEFORM_PB19 (0U)
#endif
#endif

/* 仅同步模式关闭时使用的 PB19 点数/采样率。 */
#ifndef APP_WAVEFORM_PB19_SAMPLE_COUNT
#ifdef APP_WAVEFORM_PA21_SAMPLE_COUNT
#define APP_WAVEFORM_PB19_SAMPLE_COUNT (APP_WAVEFORM_PA21_SAMPLE_COUNT)
#else
#define APP_WAVEFORM_PB19_SAMPLE_COUNT (1024U)
#endif
#endif

#ifndef APP_WAVEFORM_PB19_SAMPLE_RATE_HZ
#ifdef APP_WAVEFORM_PA21_SAMPLE_RATE_HZ
#define APP_WAVEFORM_PB19_SAMPLE_RATE_HZ (APP_WAVEFORM_PA21_SAMPLE_RATE_HZ)
#else
#define APP_WAVEFORM_PB19_SAMPLE_RATE_HZ (1000000UL)
#endif
#endif

/**
 * PB19 前级频率换算比例：用于还原外部前级分频或倍频造成的频率变化。
 * 换算频率 = 测量频率 × NUMERATOR / DENOMINATOR；默认 1/1 表示不换算，
 * 分母必须非零。例如前级把频率除以 10，应配置为 10UL / 1UL。
 */
#ifndef APP_WAVEFORM_PB19_FREQUENCY_SCALE_NUMERATOR
#define APP_WAVEFORM_PB19_FREQUENCY_SCALE_NUMERATOR (1UL)
#endif

#ifndef APP_WAVEFORM_PB19_FREQUENCY_SCALE_DENOMINATOR
#define APP_WAVEFORM_PB19_FREQUENCY_SCALE_DENOMINATOR (1UL)
#endif

/**
 * PB19 测量时钟校准比例：用于补偿定时器时钟或采样周期误差。
 * 最终频率会乘以 CALIBRATION_NUMERATOR / DENOMINATOR；默认 1/1 表示不校准，
 * 分母必须非零。应使用标准频率实测值与系统测量值确定这组比例。
 */
#ifndef APP_WAVEFORM_PB19_FREQUENCY_CALIBRATION_NUMERATOR
#define APP_WAVEFORM_PB19_FREQUENCY_CALIBRATION_NUMERATOR (1UL)
#endif

#ifndef APP_WAVEFORM_PB19_FREQUENCY_CALIBRATION_DENOMINATOR
#define APP_WAVEFORM_PB19_FREQUENCY_CALIBRATION_DENOMINATOR (1UL)
#endif

/* 旧 PA21 宏仅保留给内部 API 和已有工程兼容；新配置请使用 PB19 宏。 */
#ifndef APP_ENABLE_WAVEFORM_PA21
#define APP_ENABLE_WAVEFORM_PA21 (APP_ENABLE_WAVEFORM_PB19)
#endif
#ifndef APP_WAVEFORM_PA21_SAMPLE_COUNT
#define APP_WAVEFORM_PA21_SAMPLE_COUNT (APP_WAVEFORM_PB19_SAMPLE_COUNT)
#endif
#ifndef APP_WAVEFORM_PA21_SAMPLE_RATE_HZ
#define APP_WAVEFORM_PA21_SAMPLE_RATE_HZ (APP_WAVEFORM_PB19_SAMPLE_RATE_HZ)
#endif
#ifndef APP_WAVEFORM_PA21_FREQUENCY_SCALE_NUMERATOR
#define APP_WAVEFORM_PA21_FREQUENCY_SCALE_NUMERATOR \
    (APP_WAVEFORM_PB19_FREQUENCY_SCALE_NUMERATOR)
#endif
#ifndef APP_WAVEFORM_PA21_FREQUENCY_SCALE_DENOMINATOR
#define APP_WAVEFORM_PA21_FREQUENCY_SCALE_DENOMINATOR \
    (APP_WAVEFORM_PB19_FREQUENCY_SCALE_DENOMINATOR)
#endif
#ifndef APP_WAVEFORM_PA21_FREQUENCY_CALIBRATION_NUMERATOR
#define APP_WAVEFORM_PA21_FREQUENCY_CALIBRATION_NUMERATOR \
    (APP_WAVEFORM_PB19_FREQUENCY_CALIBRATION_NUMERATOR)
#endif
#ifndef APP_WAVEFORM_PA21_FREQUENCY_CALIBRATION_DENOMINATOR
#define APP_WAVEFORM_PA21_FREQUENCY_CALIBRATION_DENOMINATOR \
    (APP_WAVEFORM_PB19_FREQUENCY_CALIBRATION_DENOMINATOR)
#endif

/* ========================================================================== */
/* 2. Serial Communication：UART 与 ADC JustFloat                            */
/* application/communication/serial_communication/                           */
/* ========================================================================== */

/* UART0：PA10，系统调试发送；关闭后所有 Application 调试日志静默丢弃。 */
#ifndef APP_ENABLE_UART0_DEBUG
#define APP_ENABLE_UART0_DEBUG (1U)
#endif

/* UART1：PA8/PA9；开启后创建 UART1 接收任务。 */
#ifndef APP_ENABLE_UART1
#define APP_ENABLE_UART1 (0U)
#endif

/* UART2：PB15/PB16；开启后创建 UART2 接收任务，也是 VOFA+ 输出口。 */
#ifndef APP_ENABLE_UART2
#define APP_ENABLE_UART2 (0U)
#endif

/* UART3 总开关：PA26(TX)/PA25(RX)，开启后创建 UART3 收发和接收任务。 */
#ifndef APP_ENABLE_UART3
#define APP_ENABLE_UART3 (1U)
#endif

/* UART3 是否解析 AA + int16 大端 + 55 二进制波形帧。 */
#ifndef APP_ENABLE_UART3_BINARY_WAVEFORM
#define APP_ENABLE_UART3_BINARY_WAVEFORM (1U)
#endif

/* UART3 是否解析逐行 ASCII 电压，例如 0.57385\r\n。 */
#ifndef APP_ENABLE_UART3_ASCII_WAVEFORM
#define APP_ENABLE_UART3_ASCII_WAVEFORM (1U)
#endif

/* UART3 是否启用 HELLO/PING 等文本命令处理和 UART0 调试提示。 */
#ifndef APP_ENABLE_UART3_TEXT_COMMAND
#define APP_ENABLE_UART3_TEXT_COMMAND (1U)
#endif

/* UART3 曲线页面进入或重新采集时，是否自动发送所选 l 前缀请求。 */
#ifndef APP_ENABLE_UART3_WAVEFORM_REQUEST
#define APP_ENABLE_UART3_WAVEFORM_REQUEST (1U)
#endif

/* UART3 外部波形固定按 128 点组成一帧，与显示宽度一一对应。 */
#ifndef APP_UART3_WAVEFORM_SAMPLE_COUNT
#define APP_UART3_WAVEFORM_SAMPLE_COUNT (128U)
#endif

/**
 * UART3 波形显示是否减去当前完整帧的平均值（去除直流分量）：
 * 1U：仅在显示端将 128 点减去平均值，使波形围绕中线显示；
 * 0U：按接收到的原始电压值显示，中线继续严格表示 0 V。
 * 此开关不修改 UART3 原始接收数据，也不影响频谱和峰值数据。
 */
#ifndef APP_ENABLE_UART3_WAVEFORM_DISPLAY_REMOVE_DC
#define APP_ENABLE_UART3_WAVEFORM_DISPLAY_REMOVE_DC (0U)
#endif

/**
 * UART3 外部频谱和峰值数据开关：
 * 1U：频谱页发送 lspecta/lspectb，并解析 start + 128 点 + end 响应；
 * 0U：不创建 UART3 频谱菜单项，也不发布外部频谱结果。
 */
#ifndef APP_ENABLE_UART3_SPECTRUM
#define APP_ENABLE_UART3_SPECTRUM (1U)
#endif

/* 外部频谱固定接收 128 个非负十进制点，再压缩成 OLED 的 32 个频带。 */
#ifndef APP_UART3_SPECTRUM_POINT_COUNT
#define APP_UART3_SPECTRUM_POINT_COUNT (128U)
#endif

/* components 响应最多保留的峰值数量，与参考项目保持为 3 个。 */
#ifndef APP_UART3_SPECTRUM_MAX_COMPONENT_COUNT
#define APP_UART3_SPECTRUM_MAX_COMPONENT_COUNT (3U)
#endif

/* spectrum 的横轴上限；第 0 点为 0 Hz，最后一点为 500 kHz。 */
#ifndef APP_UART3_SPECTRUM_MAX_FREQUENCY_HZ
#define APP_UART3_SPECTRUM_MAX_FREQUENCY_HZ (500000UL)
#endif

/* 每次 ADC 采满并统一处理完整窗口后，把最后 128 点经 UART2 发给 VOFA+。 */
#ifndef APP_ENABLE_ADC_JUSTFLOAT
#define APP_ENABLE_ADC_JUSTFLOAT (0U)
#endif

/**
 * JustFloat 上电数据源：0U=PA27，1U=PA21。
 * 未显式定义时优先选择已启用的 PA27；运行后仍可通过 API 切换数据源。
 */
#ifndef APP_ADC_JUSTFLOAT_DEFAULT_SOURCE
#if APP_ENABLE_WAVEFORM_PA27 != 0U
#define APP_ADC_JUSTFLOAT_DEFAULT_SOURCE (0U)
#elif APP_ENABLE_WAVEFORM_PA21 != 0U
#define APP_ADC_JUSTFLOAT_DEFAULT_SOURCE (1U)
#else
/* 保留确定值；如果启用 JustFloat，文件末尾会报告输入未启用。 */
#define APP_ADC_JUSTFLOAT_DEFAULT_SOURCE (0U)
#endif
#endif

/* ========================================================================== */
/* 3. Waveform Output：PA15 DAC、AD9833 与 AD9850                            */
/* application/waveform/waveform_output/                                     */
/* ========================================================================== */

/* 总开关：统一初始化和安全关闭当前选中的输出后端。 */
#ifndef APP_ENABLE_WAVEFORM_OUTPUT
#define APP_ENABLE_WAVEFORM_OUTPUT (1U)
#endif

/* PA15 / DAC0 独立选择开关。 */
#ifndef APP_ENABLE_WAVEFORM_OUTPUT_DAC
#define APP_ENABLE_WAVEFORM_OUTPUT_DAC (1U)
#endif

/**
 * DAC 周期波形固定更新率。正弦、方波、三角波、锯齿波和任意波形均使用
 * 双缓冲连续 DDS，因此都保持该 DAC 更新率，便于使用固定截止频率的外部
 * 重建低通滤波器。任意波形元数据中的采样率仍用于保持原播放速度。
 * 默认 1 MSPS；只能选择 DAC Sample Timer 支持的离散档位。
 */
#if !defined(APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ) && \
    defined(APP_DAC_SINE_FIXED_SAMPLE_RATE_HZ)
#define APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ \
    (APP_DAC_SINE_FIXED_SAMPLE_RATE_HZ)
#endif
#ifndef APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ
#define APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ (1000000UL)
#endif
/* 兼容已经使用过的旧正弦波专用宏。新代码请使用上面的通用宏。 */
#ifndef APP_DAC_SINE_FIXED_SAMPLE_RATE_HZ
#define APP_DAC_SINE_FIXED_SAMPLE_RATE_HZ \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ)
#endif

/**
 * DAC 方波稳定周期开关：
 * 1U：强制每个半周期使用固定整数个采样点，高/低电平等长、边沿稳定；无法精确
 *     表示的请求频率会量化到最近可实现值（例如 126.1 kHz -> 125 kHz）。
 * 0U：使用32位相位累加器优先保证平均频率接近请求值，但非整数周期可能产生1个
 *     DAC 采样间隔的边沿抖动，示波器上可能看到重叠边沿。
 */
#ifndef APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES
#define APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES (0U)
#endif

/* AD9833 / SPI1（PB9 SCLK、PB8 SDATA、PB6 FSYNC）独立选择开关。 */
#ifndef APP_ENABLE_WAVEFORM_OUTPUT_DDS
#define APP_ENABLE_WAVEFORM_OUTPUT_DDS (0U)
#endif

/**
 * AD9850 独立选择开关。
 * 接线：PB9=SCLK/W_CLK、PB8=SDATA/D7、PB5=FQ_UD、PA1=RESET。
 * AD9850 与 AD9833 共用 PB9/PB8；当前实际应用一次只接其中一个模块，
 * 因此只需启用与当前接线模块对应的一个输出开关。
 */
#ifndef APP_ENABLE_WAVEFORM_OUTPUT_AD9850
#define APP_ENABLE_WAVEFORM_OUTPUT_AD9850 (0U)
#endif

/**
 * 任意波形 Flash 槽位服务：每个槽位最多 1024 点，加载后由 DAC 模块的
 * 固定更新率双缓冲路径播放；关闭 DAC 后该服务也会自动关闭。
 */
#ifndef APP_ENABLE_ARBITRARY_WAVEFORM
#define APP_ENABLE_ARBITRARY_WAVEFORM (0U)
#endif

/* Flash 槽位数量和每槽最大采样点数；仅启用服务时由链接脚本预留存储区。 */
#ifndef APP_ARBITRARY_WAVEFORM_SLOT_COUNT
#define APP_ARBITRARY_WAVEFORM_SLOT_COUNT (2U)
#endif
#ifndef APP_ARBITRARY_WAVEFORM_MAX_SAMPLES
#define APP_ARBITRARY_WAVEFORM_MAX_SAMPLES (1024U)
#endif

/**
 * PA27 阈值触发保存：ADC12 窗口比较器等待绝对电压超过阈值，
 * ADC 中断启动 DMA 采集固定时长并保存到任意波形 Flash 槽位；
 * DMA 完成后必须等信号回落才重新允许下一次触发。
 */
#ifndef APP_ENABLE_PA27_THRESHOLD_TRIGGER
#define APP_ENABLE_PA27_THRESHOLD_TRIGGER (0U)
#endif
#ifndef APP_PA27_TRIGGER_THRESHOLD_MILLIVOLTS
#define APP_PA27_TRIGGER_THRESHOLD_MILLIVOLTS (1000U)
#endif
#ifndef APP_PA27_TRIGGER_SAMPLE_RATE_HZ
#define APP_PA27_TRIGGER_SAMPLE_RATE_HZ (1000000UL)
#endif
#ifndef APP_PA27_TRIGGER_CAPTURE_DURATION_US
#define APP_PA27_TRIGGER_CAPTURE_DURATION_US (200U)
#endif

/* 常见 AD9850 模块为 125 MHz 晶振；实际晶振不同须按模块标称值修改。 */
#ifndef APP_AD9850_REFERENCE_CLOCK_HZ
#define APP_AD9850_REFERENCE_CLOCK_HZ (125000000UL)
#endif

/* 菜单/API 允许的最高输出频率；不得超过参考时钟的一半。 */
#ifndef APP_AD9850_MAXIMUM_FREQUENCY_HZ
#define APP_AD9850_MAXIMUM_FREQUENCY_HZ (40000000UL)
#endif

/**
 * 总开关优先级最高：关闭时自动屏蔽两个后端。
 * 因此只需把 APP_ENABLE_WAVEFORM_OUTPUT 改为 0U，无需同步修改各个后端。
 */
#if APP_ENABLE_WAVEFORM_OUTPUT == 0U
#undef APP_ENABLE_WAVEFORM_OUTPUT_DAC
#define APP_ENABLE_WAVEFORM_OUTPUT_DAC (0U)
#undef APP_ENABLE_WAVEFORM_OUTPUT_DDS
#define APP_ENABLE_WAVEFORM_OUTPUT_DDS (0U)
#undef APP_ENABLE_WAVEFORM_OUTPUT_AD9850
#define APP_ENABLE_WAVEFORM_OUTPUT_AD9850 (0U)
#endif

#if APP_ENABLE_WAVEFORM_OUTPUT_DAC == 0U
#undef APP_ENABLE_ARBITRARY_WAVEFORM
#define APP_ENABLE_ARBITRARY_WAVEFORM (0U)
#endif

#if APP_ENABLE_ARBITRARY_WAVEFORM == 0U
#undef APP_ENABLE_PA27_THRESHOLD_TRIGGER
#define APP_ENABLE_PA27_THRESHOLD_TRIGGER (0U)
#endif

/* ========================================================================== */
/* 4. Waveform Mapping：把 PA27 测量结果自动映射到输出                        */
/* application/waveform/waveform_mapping/                                    */
/* ========================================================================== */

/* 总开关：订阅每次 PA27 测量结果；该 Application 不创建新任务。 */
#ifndef APP_ENABLE_WAVEFORM_MAPPING
#define APP_ENABLE_WAVEFORM_MAPPING (0U)
#endif

/* 映射后端 1：DAC；三项中必须且只能有一个为 1U。 */
#ifndef APP_WAVEFORM_MAPPING_BACKEND_DAC
#define APP_WAVEFORM_MAPPING_BACKEND_DAC (0U)
#endif

/* 映射后端 2：AD9833；三项中必须且只能有一个为 1U。 */
#ifndef APP_WAVEFORM_MAPPING_BACKEND_AD9833
#define APP_WAVEFORM_MAPPING_BACKEND_AD9833 (0U)
#endif

/* 映射后端 3：AD9850；仅支持正弦波映射到 SIN、方波映射到 SQ。 */
#ifndef APP_WAVEFORM_MAPPING_BACKEND_AD9850
#define APP_WAVEFORM_MAPPING_BACKEND_AD9850 (0U)
#endif

/* 没有输出后端时映射没有执行对象，跟随输出总开关自动关闭。 */
#if APP_ENABLE_WAVEFORM_OUTPUT == 0U
#undef APP_ENABLE_WAVEFORM_MAPPING
#define APP_ENABLE_WAVEFORM_MAPPING (0U)
#endif

/* ========================================================================== */
/* 5. Servo Control：PA23/PA24 双路舵机                                      */
/* application/control/servo_control/                                        */
/* ========================================================================== */

/**
 * 总允许开关：有任一路输出开启时创建 20 ms ServoControl 任务。
 * 两路输出都为 0U 时会自动关闭该开关，无需再手动同步修改。
 */
#ifndef APP_ENABLE_SERVO_CONTROL
#define APP_ENABLE_SERVO_CONTROL (0U)
#endif

/* --------------------- 舵机 0：PA23 / TIMG7 CCP0 ------------------------- */

#ifndef APP_ENABLE_SERVO_CONTROL_OUTPUT_0
#define APP_ENABLE_SERVO_CONTROL_OUTPUT_0 (0U)
#endif

/* 1U=初始化后立即输出 50 Hz 控制脉冲；0U=等待 ServoControlStartDevice()。 */
#ifndef APP_SERVO_CONTROL_OUTPUT_0_START_ENABLED
#define APP_SERVO_CONTROL_OUTPUT_0_START_ENABLED (0U)
#endif

/* 1U=启动后在 0°和最大角度间往返；0U=停留/移动到 API 指定目标。 */
#ifndef APP_SERVO_CONTROL_OUTPUT_0_AUTO_SWEEP_ENABLED
#define APP_SERVO_CONTROL_OUTPUT_0_AUTO_SWEEP_ENABLED (0U)
#endif

#ifndef APP_SERVO_CONTROL_OUTPUT_0_INITIAL_ANGLE_DEGREES
#define APP_SERVO_CONTROL_OUTPUT_0_INITIAL_ANGLE_DEGREES (90U)
#endif

/* --------------------- 舵机 1：PA24 / TIMG7 CCP1 ------------------------- */

#ifndef APP_ENABLE_SERVO_CONTROL_OUTPUT_1
#define APP_ENABLE_SERVO_CONTROL_OUTPUT_1 (0U)
#endif

#ifndef APP_SERVO_CONTROL_OUTPUT_1_START_ENABLED
#define APP_SERVO_CONTROL_OUTPUT_1_START_ENABLED (0U)
#endif

#ifndef APP_SERVO_CONTROL_OUTPUT_1_AUTO_SWEEP_ENABLED
#define APP_SERVO_CONTROL_OUTPUT_1_AUTO_SWEEP_ENABLED (0U)
#endif

#ifndef APP_SERVO_CONTROL_OUTPUT_1_INITIAL_ANGLE_DEGREES
#define APP_SERVO_CONTROL_OUTPUT_1_INITIAL_ANGLE_DEGREES (90U)
#endif

/* ---------------------------- 两路共用参数 ------------------------------- */

/**
 * 角度到高电平脉宽的线性映射端点。500～2500 us 只是常见初始值，
 * 不保证适合所有舵机；首次接入应从 1500 us 中位附近逐步校准机械范围。
 */
#ifndef APP_SERVO_CONTROL_MINIMUM_PULSE_WIDTH_US
#define APP_SERVO_CONTROL_MINIMUM_PULSE_WIDTH_US (500U)
#endif

#ifndef APP_SERVO_CONTROL_MAXIMUM_PULSE_WIDTH_US
#define APP_SERVO_CONTROL_MAXIMUM_PULSE_WIDTH_US (2500U)
#endif

#ifndef APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES
#define APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES (180U)
#endif

/* 每个 20 ms 周期每路最多变化 2°，默认命令速度约为 100°/s。 */
#ifndef APP_SERVO_CONTROL_STEP_DEGREES
#define APP_SERVO_CONTROL_STEP_DEGREES (2U)
#endif

/* 两路都未选择时自动裁剪舵机任务、静态栈和 TCB，避免无效配置报错。 */
#if (APP_ENABLE_SERVO_CONTROL == 1U) && \
    (APP_ENABLE_SERVO_CONTROL_OUTPUT_0 == 0U) && \
    (APP_ENABLE_SERVO_CONTROL_OUTPUT_1 == 0U)
#undef APP_ENABLE_SERVO_CONTROL
#define APP_ENABLE_SERVO_CONTROL (0U)
#endif

/* ========================================================================== */
/* 6. TB6612 Control：双路直流电机                                           */
/* application/control/motor_control/                                        */
/* ========================================================================== */

/**
 * 电机控制 Application 总开关。开启后由 ApplicationInit() 创建固定周期控制任务；
 * 上电仍保持 TB6612 的 STBY 低电平，必须下发非零目标速度才会运行。
 *
 * 旧工程也可以继续定义 APP_ENABLE_TB6612_CONTROL；当两个宏只定义一个时，另一
 * 个会自动同步。新代码建议使用通用的 APP_ENABLE_MOTOR_CONTROL。
 */
#ifndef APP_ENABLE_MOTOR_CONTROL
#ifdef APP_ENABLE_TB6612_CONTROL
#define APP_ENABLE_MOTOR_CONTROL (APP_ENABLE_TB6612_CONTROL)
#else
#define APP_ENABLE_MOTOR_CONTROL (0U)
#endif
#endif

#ifndef APP_ENABLE_TB6612_CONTROL
#define APP_ENABLE_TB6612_CONTROL (APP_ENABLE_MOTOR_CONTROL)
#endif

/* PA17/PWMA 与 PA16/PWMB 的 PWM 频率；TB6612 推荐使用不易听见的 20 kHz。 */
#ifndef APP_TB6612_PWM_FREQUENCY_HZ
#define APP_TB6612_PWM_FREQUENCY_HZ (20000UL)
#endif

/* MotorControlTask 控制周期，单位 ms。 */
#ifndef APP_TB6612_CONTROL_PERIOD_MS
#define APP_TB6612_CONTROL_PERIOD_MS (10U)
#endif

/* 每个任务周期允许变化的速度百分比；5U 配合 10 ms 时约 200 ms 完成 0～100%。 */
#ifndef APP_TB6612_SPEED_STEP_PERCENT
#define APP_TB6612_SPEED_STEP_PERCENT (5U)
#endif

/* 速度目标变为 0 时：0U=滑行停止并进入待机，1U=短路制动并保持驱动唤醒。 */
#ifndef APP_TB6612_DEFAULT_BRAKE_ON_STOP
#define APP_TB6612_DEFAULT_BRAKE_ON_STOP (0U)
#endif

/* 电机接线方向与逻辑正方向相反时设为 1U，无需交换电机线。 */
#ifndef APP_TB6612_MOTOR_A_REVERSED
#define APP_TB6612_MOTOR_A_REVERSED (0U)
#endif

#ifndef APP_TB6612_MOTOR_B_REVERSED
#define APP_TB6612_MOTOR_B_REVERSED (0U)
#endif

/* ========================================================================== */
/* 7. Input：MPU6050 和 4×4 矩阵键盘                                      */
/* application/input/                                                       */
/* ========================================================================== */

/**
 * 独立开关：开启后初始化 I2C1（PB2 SCL、PB3 SDA）上的 MPU6050，并创建周期读取任务。
 * 传感器未接好时任务会每 500 ms 自动重试，不阻止其他任务和菜单启动。
 */
#ifndef APP_ENABLE_MPU6050_INPUT
#define APP_ENABLE_MPU6050_INPUT (0U)
#endif

/* MPU6050 任务读取周期，单位 ms；10 ms 对应最高约 100 次读取/秒。 */
#ifndef APP_MPU6050_INPUT_PERIOD_MS
#define APP_MPU6050_INPUT_PERIOD_MS (10U)
#endif

/* 启用外部 InvenSense DMP；启用后输入任务发布四元数和姿态角。默认关闭以控制 Flash 占用。 */
#ifndef APP_ENABLE_MPU6050_DMP
#define APP_ENABLE_MPU6050_DMP (0U)
#endif

/* DMP FIFO 输出频率，范围 1～200 Hz；100 Hz 与默认 10 ms 任务周期匹配。 */
#ifndef APP_MPU6050_DMP_RATE_HZ
#define APP_MPU6050_DMP_RATE_HZ (100U)
#endif

/* ------------------------- Matrix Keypad -------------------------------- */

/**
 * 总开关：注册矩阵键盘 Module，并创建一个固定周期的 MatrixKeypad 任务。
 * 0U 时不创建任务、不分配任务栈和事件队列；SysConfig 中的引脚仍保持预留。
 */
#ifndef APP_ENABLE_MATRIX_KEYPAD
#define APP_ENABLE_MATRIX_KEYPAD (1U)
#endif

/* 扫描周期，单位 ms；推荐 5～10 ms，驱动内部对每个键独立进行 30 ms 防抖。 */
#ifndef APP_MATRIX_KEYPAD_SCAN_PERIOD_MS
#define APP_MATRIX_KEYPAD_SCAN_PERIOD_MS (10U)
#endif

/**
 * 矩阵键盘按下值通过 UART3 输出开关：
 * 1U：每个新按下键发送“键值字符 + NUL”，例如按 5 发送 {'5', '\0'}；
 * 0U：只保留原有键盘事件队列，不通过 UART3 发送。
 */
#ifndef APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT
#define APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT (1U)
#endif

/* ========================================================================== */
/* 8. Display Menu：OLED/TFT 二选一、按键和可选通用 PWM 页面                 */
/* application/menu/                                                         */
/* ========================================================================== */

/**
 * 显示后端必须且只能选择一个：
 * - OLED：SSD1306，I2C0（PA31 SCL、PA28 SDA）；
 * - TFT：ST7735S 1.8 寸，SPI0（PB18 SCLK、PB17 MOSI、PB20 CS、
 *   PB1 DC、PB4 RESET）。
 * 两种显示共用 PA18/PB21 按键和相同的页面逻辑。
 */
#ifndef APP_ENABLE_OLED_MENU
#define APP_ENABLE_OLED_MENU (0U)
#endif

#ifndef APP_ENABLE_TFT_MENU
#define APP_ENABLE_TFT_MENU (1U)
#endif

/**
 * 上电初始页面：
 * - MAIN：原有 MAIN MENU；
 * - CUSTOM：application/menu/custom_page/ 中的电赛自定义页面。
 * 自定义页长按 S2 可随时返回主菜单。
 */
#ifndef APP_DISPLAY_MENU_START_PAGE_MAIN
#define APP_DISPLAY_MENU_START_PAGE_MAIN (1U)
#endif

#ifndef APP_DISPLAY_MENU_START_PAGE_CUSTOM
#define APP_DISPLAY_MENU_START_PAGE_CUSTOM (0U)
#endif

/**
 * 显示菜单的通用 PWM 页面使用 PA23/TIMG7。
 * 默认规则：Servo Control 开启时关闭；否则自动开启。
 */
#ifndef APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT
#if APP_ENABLE_SERVO_CONTROL != 0U
#define APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT (0U)
#else
#define APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT (1U)
#endif
#endif

/* 舵机总开关优先级更高，开启时无需再手动关闭菜单 PWM。 */
#if APP_ENABLE_SERVO_CONTROL != 0U
#undef APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT
#define APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT (0U)
#endif

/* ========================================================================== */
/* 9. 编译期配置检查：出现 #error 时按消息检查上面的宏                        */
/* ========================================================================== */

/* -------------------------- Waveform Measurement ------------------------- */

#if !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_WAVEFORM_MEASUREMENT) || \
    !APP_CONFIG_IS_BOOLEAN( \
        APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE) || \
    !APP_CONFIG_IS_BOOLEAN( \
        APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_WAVEFORM_PA27) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_WAVEFORM_PA21) || \
    !APP_CONFIG_IS_BOOLEAN(APP_FFT_REMOVE_DC)
#error "Waveform Measurement enable values must be 0U or 1U"
#endif

#if (APP_ENABLE_WAVEFORM_SYNCHRONIZED_PHASE != 0U) && \
    (APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE == 0U)
#error "Synchronized phase measurement requires synchronized capture"
#endif

#if (APP_WAVEFORM_SYNCHRONIZED_PHASE_OFFSET_MILLIDEGREES < -180000) || \
    (APP_WAVEFORM_SYNCHRONIZED_PHASE_OFFSET_MILLIDEGREES > 180000)
#error "Synchronized phase offset must be -180000..180000 millidegrees"
#endif

#if (APP_ENABLE_WAVEFORM_SYNCHRONIZED_CAPTURE != 0U) && \
    ((APP_ENABLE_WAVEFORM_MEASUREMENT == 0U) || \
     (APP_ENABLE_WAVEFORM_PA27 == 0U) || \
     (APP_ENABLE_WAVEFORM_PA21 == 0U))
#error "Synchronized capture requires Measurement, PA27 and PB19"
#endif

#if (APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT < 64U) || \
    (APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT > 2048U) || \
    ((APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT & \
        (APP_WAVEFORM_SYNCHRONIZED_SAMPLE_COUNT - 1U)) != 0U)
#error "Synchronized sample count must be a power of two from 64 to 2048"
#endif

#if (APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ == 0UL) || \
    (APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ > 1000000UL) || \
    ((BSP_BOARD_ADC_SAMPLE_TIMER_CLOCK_HZ % \
        APP_WAVEFORM_SYNCHRONIZED_SAMPLE_RATE_HZ) != 0UL)
#error "Synchronized sample rate must be 1..1000000 Hz and divide the ADC timer clock"
#endif

#if (APP_ENABLE_WAVEFORM_MEASUREMENT != 0U) && \
    (APP_ENABLE_WAVEFORM_PA27 == 0U) && \
    (APP_ENABLE_WAVEFORM_PA21 == 0U)
#error "APP_ENABLE_WAVEFORM_MEASUREMENT requires PA27 or PA21"
#endif

#if (APP_WAVEFORM_PA27_SAMPLE_COUNT < 64U) || \
    (APP_WAVEFORM_PA27_SAMPLE_COUNT > 2048U) || \
    ((APP_WAVEFORM_PA27_SAMPLE_COUNT & \
         (APP_WAVEFORM_PA27_SAMPLE_COUNT - 1U)) != 0U) || \
    (APP_WAVEFORM_PA21_SAMPLE_COUNT < 64U) || \
    (APP_WAVEFORM_PA21_SAMPLE_COUNT > 2048U) || \
    ((APP_WAVEFORM_PA21_SAMPLE_COUNT & \
         (APP_WAVEFORM_PA21_SAMPLE_COUNT - 1U)) != 0U)
#error "Waveform sample counts must be 64/128/256/512/1024/2048"
#endif

#if ((APP_WAVEFORM_PA27_SAMPLE_RATE_HZ != 1000000UL) && \
     (APP_WAVEFORM_PA27_SAMPLE_RATE_HZ != 2000000UL) && \
     (APP_WAVEFORM_PA27_SAMPLE_RATE_HZ != 4000000UL))
#error "APP_WAVEFORM_PA27_SAMPLE_RATE_HZ must be 1000000/2000000/4000000 Hz"
#endif

#if (APP_WAVEFORM_PA21_SAMPLE_RATE_HZ == 0UL) || \
    (APP_WAVEFORM_PA21_SAMPLE_RATE_HZ > 4000000UL) || \
    ((4000000UL % APP_WAVEFORM_PA21_SAMPLE_RATE_HZ) != 0UL)
#error "APP_WAVEFORM_PA21_SAMPLE_RATE_HZ must be 1..4000000 Hz and divide 4000000 Hz"
#endif

#if (APP_WAVEFORM_PA27_FREQUENCY_SCALE_NUMERATOR == 0UL) || \
    (APP_WAVEFORM_PA27_FREQUENCY_SCALE_DENOMINATOR == 0UL) || \
    (APP_WAVEFORM_PA21_FREQUENCY_SCALE_NUMERATOR == 0UL) || \
    (APP_WAVEFORM_PA21_FREQUENCY_SCALE_DENOMINATOR == 0UL)
#error "Waveform frequency scale values must be non-zero"
#endif

#if (APP_WAVEFORM_PA27_FREQUENCY_CALIBRATION_NUMERATOR == 0UL) || \
    (APP_WAVEFORM_PA27_FREQUENCY_CALIBRATION_DENOMINATOR == 0UL) || \
    (APP_WAVEFORM_PA21_FREQUENCY_CALIBRATION_NUMERATOR == 0UL) || \
    (APP_WAVEFORM_PA21_FREQUENCY_CALIBRATION_DENOMINATOR == 0UL)
#error "Waveform frequency calibration values must be non-zero"
#endif

/* -------------------------- Serial Communication ------------------------- */

#if !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART0_DEBUG) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART1) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART2) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART3) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART3_BINARY_WAVEFORM) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART3_ASCII_WAVEFORM) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART3_TEXT_COMMAND) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART3_WAVEFORM_REQUEST) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART3_WAVEFORM_DISPLAY_REMOVE_DC) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_UART3_SPECTRUM) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_ADC_JUSTFLOAT) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_MPU6050_INPUT) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_MPU6050_DMP)
#error "Serial Communication enable values must be 0U or 1U"
#endif

#if APP_MPU6050_INPUT_PERIOD_MS == 0U
#error "APP_MPU6050_INPUT_PERIOD_MS must be greater than 0"
#endif

#if (APP_MPU6050_DMP_RATE_HZ == 0U) || \
    (APP_MPU6050_DMP_RATE_HZ > 200U)
#error "APP_MPU6050_DMP_RATE_HZ must be between 1 and 200 Hz"
#endif

#if APP_UART3_WAVEFORM_SAMPLE_COUNT != 128U
#error "APP_UART3_WAVEFORM_SAMPLE_COUNT must be 128"
#endif

#if APP_UART3_SPECTRUM_POINT_COUNT != 128U
#error "APP_UART3_SPECTRUM_POINT_COUNT must be 128"
#endif

#if (APP_UART3_SPECTRUM_MAX_COMPONENT_COUNT == 0U) || \
    (APP_UART3_SPECTRUM_MAX_COMPONENT_COUNT > 16U)
#error "APP_UART3_SPECTRUM_MAX_COMPONENT_COUNT must be between 1 and 16"
#endif

#if APP_UART3_SPECTRUM_MAX_FREQUENCY_HZ == 0UL
#error "APP_UART3_SPECTRUM_MAX_FREQUENCY_HZ must be greater than 0"
#endif

#if (APP_ENABLE_UART3_BINARY_WAVEFORM != 0U) && \
    (APP_ENABLE_UART3 == 0U)
#error "APP_ENABLE_UART3_BINARY_WAVEFORM requires APP_ENABLE_UART3"
#endif

#if (APP_ENABLE_UART3_ASCII_WAVEFORM != 0U) && \
    (APP_ENABLE_UART3 == 0U)
#error "APP_ENABLE_UART3_ASCII_WAVEFORM requires APP_ENABLE_UART3"
#endif

#if (APP_ENABLE_UART3_TEXT_COMMAND != 0U) && \
    (APP_ENABLE_UART3 == 0U)
#error "APP_ENABLE_UART3_TEXT_COMMAND requires APP_ENABLE_UART3"
#endif

#if (APP_ENABLE_UART3_WAVEFORM_REQUEST != 0U) && \
    (APP_ENABLE_UART3 == 0U)
#error "APP_ENABLE_UART3_WAVEFORM_REQUEST requires APP_ENABLE_UART3"
#endif

#if (APP_ENABLE_UART3_SPECTRUM != 0U) && \
    ((APP_ENABLE_UART3 == 0U) || \
     (APP_ENABLE_WAVEFORM_MEASUREMENT == 0U))
#error "APP_ENABLE_UART3_SPECTRUM requires UART3 and Waveform Measurement"
#endif

#if APP_ADC_JUSTFLOAT_DEFAULT_SOURCE > 1U
#error "APP_ADC_JUSTFLOAT_DEFAULT_SOURCE must be 0U or 1U"
#endif

#if (APP_ENABLE_ADC_JUSTFLOAT != 0U) && (APP_ENABLE_UART2 == 0U)
#error "APP_ENABLE_ADC_JUSTFLOAT requires APP_ENABLE_UART2"
#endif

#if (APP_ENABLE_ADC_JUSTFLOAT != 0U) && \
    (APP_ENABLE_WAVEFORM_MEASUREMENT == 0U)
#error "APP_ENABLE_ADC_JUSTFLOAT requires APP_ENABLE_WAVEFORM_MEASUREMENT"
#endif

#if (APP_ENABLE_ADC_JUSTFLOAT != 0U) && \
    (APP_ADC_JUSTFLOAT_DEFAULT_SOURCE == 0U) && \
    (APP_ENABLE_WAVEFORM_PA27 == 0U)
#error "JustFloat PA27 source requires APP_ENABLE_WAVEFORM_PA27"
#endif

#if (APP_ENABLE_ADC_JUSTFLOAT != 0U) && \
    (APP_ADC_JUSTFLOAT_DEFAULT_SOURCE == 1U) && \
    (APP_ENABLE_WAVEFORM_PA21 == 0U)
#error "JustFloat PA21 source requires APP_ENABLE_WAVEFORM_PA21"
#endif

/* ----------------------------- Waveform Output --------------------------- */

#if !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_WAVEFORM_OUTPUT) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_WAVEFORM_OUTPUT_DAC) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_WAVEFORM_OUTPUT_DDS) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_WAVEFORM_OUTPUT_AD9850) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_ARBITRARY_WAVEFORM) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_PA27_THRESHOLD_TRIGGER) || \
    !APP_CONFIG_IS_BOOLEAN( \
        APP_DAC_SQUARE_FORCE_INTEGER_EVEN_SAMPLES)
#error "Waveform Output enable values must be 0U or 1U"
#endif

#if (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 500UL) && \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 1000UL) && \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 2000UL) && \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 4000UL) && \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 8000UL) && \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 16000UL) && \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 100000UL) && \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 200000UL) && \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 500000UL) && \
    (APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ != 1000000UL)
#error "APP_DAC_WAVEFORM_FIXED_SAMPLE_RATE_HZ is not supported by DAC Sample Timer"
#endif

#if (APP_PA27_TRIGGER_THRESHOLD_MILLIVOLTS == 0U) || \
    (APP_PA27_TRIGGER_THRESHOLD_MILLIVOLTS > 3300U) || \
    (APP_PA27_TRIGGER_SAMPLE_RATE_HZ == 0UL) || \
    (APP_PA27_TRIGGER_SAMPLE_RATE_HZ > 1000000UL) || \
    ((APP_PA27_TRIGGER_CAPTURE_DURATION_US * \
        APP_PA27_TRIGGER_SAMPLE_RATE_HZ) % 1000000UL != 0UL) || \
    (((APP_PA27_TRIGGER_CAPTURE_DURATION_US * \
        APP_PA27_TRIGGER_SAMPLE_RATE_HZ) / 1000000UL) < 2U) || \
    (((APP_PA27_TRIGGER_CAPTURE_DURATION_US * \
        APP_PA27_TRIGGER_SAMPLE_RATE_HZ) / 1000000UL) > \
        APP_ARBITRARY_WAVEFORM_MAX_SAMPLES)
#error "PA27 trigger parameters are invalid"
#endif

#if (APP_ENABLE_PA27_THRESHOLD_TRIGGER != 0U) && \
    ((APP_ENABLE_WAVEFORM_MEASUREMENT == 0U) || \
     (APP_ENABLE_WAVEFORM_PA27 == 0U) || \
     (APP_ENABLE_ARBITRARY_WAVEFORM == 0U) || \
     (APP_ENABLE_WAVEFORM_OUTPUT_DAC == 0U))
#error "PA27 threshold trigger requires PA27 measurement, DAC and arbitrary waveform"
#endif

#if (APP_ARBITRARY_WAVEFORM_SLOT_COUNT == 0U) || \
    (APP_ARBITRARY_WAVEFORM_SLOT_COUNT > 3U) || \
    (APP_ARBITRARY_WAVEFORM_MAX_SAMPLES < 2U) || \
    (APP_ARBITRARY_WAVEFORM_MAX_SAMPLES > 1024U)
#error "Arbitrary waveform slots must be 1..3 and samples must be 2..1024"
#endif

#if (APP_ENABLE_WAVEFORM_OUTPUT != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DAC == 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DDS == 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 == 0U)
#error "APP_ENABLE_WAVEFORM_OUTPUT requires DAC, AD9833 or AD9850"
#endif

#if (APP_AD9850_REFERENCE_CLOCK_HZ == 0UL) || \
    (APP_AD9850_MAXIMUM_FREQUENCY_HZ == 0UL) || \
    (APP_AD9850_MAXIMUM_FREQUENCY_HZ > \
        (APP_AD9850_REFERENCE_CLOCK_HZ / 2UL))
#error "AD9850 frequency configuration is invalid"
#endif

/* ----------------------------- Waveform Mapping -------------------------- */

#if !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_WAVEFORM_MAPPING) || \
    !APP_CONFIG_IS_BOOLEAN(APP_WAVEFORM_MAPPING_BACKEND_DAC) || \
    !APP_CONFIG_IS_BOOLEAN(APP_WAVEFORM_MAPPING_BACKEND_AD9833) || \
    !APP_CONFIG_IS_BOOLEAN(APP_WAVEFORM_MAPPING_BACKEND_AD9850)
#error "Waveform Mapping enable/backend values must be 0U or 1U"
#endif

#if (APP_ENABLE_WAVEFORM_MAPPING != 0U) && \
    ((APP_WAVEFORM_MAPPING_BACKEND_DAC + \
        APP_WAVEFORM_MAPPING_BACKEND_AD9833 + \
        APP_WAVEFORM_MAPPING_BACKEND_AD9850) != 1U)
#error "Waveform Mapping must select exactly one of DAC, AD9833 or AD9850"
#endif

#if (APP_ENABLE_WAVEFORM_MAPPING != 0U) && \
    ((APP_ENABLE_WAVEFORM_MEASUREMENT == 0U) || \
     (APP_ENABLE_WAVEFORM_PA27 == 0U))
#error "APP_ENABLE_WAVEFORM_MAPPING requires Measurement and PA27"
#endif

#if (APP_ENABLE_WAVEFORM_MAPPING != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT == 0U)
#error "APP_ENABLE_WAVEFORM_MAPPING requires APP_ENABLE_WAVEFORM_OUTPUT"
#endif

#if (APP_ENABLE_WAVEFORM_MAPPING != 0U) && \
    (APP_WAVEFORM_MAPPING_BACKEND_DAC != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DAC == 0U)
#error "DAC mapping requires APP_ENABLE_WAVEFORM_OUTPUT_DAC"
#endif

#if (APP_ENABLE_WAVEFORM_MAPPING != 0U) && \
    (APP_WAVEFORM_MAPPING_BACKEND_AD9833 != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_DDS == 0U)
#error "AD9833 mapping requires APP_ENABLE_WAVEFORM_OUTPUT_DDS"
#endif

#if (APP_ENABLE_WAVEFORM_MAPPING != 0U) && \
    (APP_WAVEFORM_MAPPING_BACKEND_AD9850 != 0U) && \
    (APP_ENABLE_WAVEFORM_OUTPUT_AD9850 == 0U)
#error "AD9850 mapping requires APP_ENABLE_WAVEFORM_OUTPUT_AD9850"
#endif

/* ------------------------------ Servo Control ---------------------------- */

#if !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_SERVO_CONTROL) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_SERVO_CONTROL_OUTPUT_0) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_SERVO_CONTROL_OUTPUT_1) || \
    !APP_CONFIG_IS_BOOLEAN(APP_SERVO_CONTROL_OUTPUT_0_START_ENABLED) || \
    !APP_CONFIG_IS_BOOLEAN(APP_SERVO_CONTROL_OUTPUT_1_START_ENABLED) || \
    !APP_CONFIG_IS_BOOLEAN( \
        APP_SERVO_CONTROL_OUTPUT_0_AUTO_SWEEP_ENABLED) || \
    !APP_CONFIG_IS_BOOLEAN( \
        APP_SERVO_CONTROL_OUTPUT_1_AUTO_SWEEP_ENABLED)
#error "Servo Control enable values must be 0U or 1U"
#endif

#if (APP_SERVO_CONTROL_MINIMUM_PULSE_WIDTH_US == 0U) || \
    (APP_SERVO_CONTROL_MAXIMUM_PULSE_WIDTH_US <= \
        APP_SERVO_CONTROL_MINIMUM_PULSE_WIDTH_US) || \
    (APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES == 0U) || \
    (APP_SERVO_CONTROL_OUTPUT_0_INITIAL_ANGLE_DEGREES > \
        APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES) || \
    (APP_SERVO_CONTROL_OUTPUT_1_INITIAL_ANGLE_DEGREES > \
        APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES) || \
    (APP_SERVO_CONTROL_STEP_DEGREES == 0U) || \
    (APP_SERVO_CONTROL_STEP_DEGREES > \
        APP_SERVO_CONTROL_MAXIMUM_ANGLE_DEGREES)
#error "Servo Control angle, pulse width or step configuration is invalid"
#endif

/* ----------------------------- TB6612 Control ---------------------------- */

#if !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_MOTOR_CONTROL) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_TB6612_CONTROL) || \
    !APP_CONFIG_IS_BOOLEAN(APP_TB6612_DEFAULT_BRAKE_ON_STOP) || \
    !APP_CONFIG_IS_BOOLEAN(APP_TB6612_MOTOR_A_REVERSED) || \
    !APP_CONFIG_IS_BOOLEAN(APP_TB6612_MOTOR_B_REVERSED)
#error "TB6612 Control enable/reverse values must be 0U or 1U"
#endif

#if APP_ENABLE_MOTOR_CONTROL != APP_ENABLE_TB6612_CONTROL
#error "APP_ENABLE_MOTOR_CONTROL and APP_ENABLE_TB6612_CONTROL must match"
#endif

#if (APP_TB6612_PWM_FREQUENCY_HZ < 100UL) || \
    (APP_TB6612_PWM_FREQUENCY_HZ > 100000UL)
#error "APP_TB6612_PWM_FREQUENCY_HZ must be 100..100000 Hz"
#endif

#if (APP_TB6612_CONTROL_PERIOD_MS == 0U) || \
    (APP_TB6612_CONTROL_PERIOD_MS > 1000U) || \
    (APP_TB6612_SPEED_STEP_PERCENT == 0U) || \
    (APP_TB6612_SPEED_STEP_PERCENT > 100U)
#error "TB6612 period must be 1..1000 ms and speed step must be 1..100 percent"
#endif

/* ------------------------------ Matrix Keypad ---------------------------- */

#if !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_MATRIX_KEYPAD) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT)
#error "Matrix Keypad enable values must be 0U or 1U"
#endif

#if (APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT != 0U) && \
    ((APP_ENABLE_MATRIX_KEYPAD == 0U) || (APP_ENABLE_UART3 == 0U))
#error "APP_ENABLE_MATRIX_KEYPAD_UART3_OUTPUT requires Matrix Keypad and UART3"
#endif

#if (APP_MATRIX_KEYPAD_SCAN_PERIOD_MS == 0U) || \
    (APP_MATRIX_KEYPAD_SCAN_PERIOD_MS > 1000U)
#error "APP_MATRIX_KEYPAD_SCAN_PERIOD_MS must be 1..1000 ms"
#endif

/* ------------------------------- Display Menu ---------------------------- */

#if !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_OLED_MENU) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_TFT_MENU) || \
    !APP_CONFIG_IS_BOOLEAN(APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT)
#error "Display Menu enable values must be 0U or 1U"
#endif

#if !APP_CONFIG_IS_BOOLEAN(APP_DISPLAY_MENU_START_PAGE_MAIN) || \
    !APP_CONFIG_IS_BOOLEAN(APP_DISPLAY_MENU_START_PAGE_CUSTOM)
#error "Display Menu start-page values must be 0U or 1U"
#endif

#if (APP_DISPLAY_MENU_START_PAGE_MAIN + \
        APP_DISPLAY_MENU_START_PAGE_CUSTOM) != 1U
#error "Select exactly one start page: MAIN or CUSTOM"
#endif

#if (APP_ENABLE_OLED_MENU + APP_ENABLE_TFT_MENU) != 1U
#error "Select exactly one display: OLED or TFT"
#endif

#if (APP_ENABLE_SERVO_CONTROL != 0U) && \
    (APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT != 0U)
#error "Servo Control conflicts with Display Menu PWM Output on TIMG7"
#endif

#undef APP_CONFIG_IS_BOOLEAN

#endif
