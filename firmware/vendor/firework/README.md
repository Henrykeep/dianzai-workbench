# LP-MSPM0G3507 FreeRTOS Firework

这是一个面向 TI LP-MSPM0G3507 开发板的 FreeRTOS 工程，按照
`BSP → Module → Application` 三层结构组织，包含多串口通信、OLED/TFT 可选显示、
板载按键菜单、ADC 采样、FFT 频谱、DAC/PWM/DDS 输出、舵机/TB6612 电机控制、模拟频率捕获和 LED 示例。

## 功能概览

- FreeRTOS 任务调度和静态模块实例
- UART0 调试输出
- UART1、UART3 中断接收，UART2 固定双字节 DMA 接收
- UART1、UART2、UART3 独立 DMA 发送
- UART1 帧协议解析
- UART2 带 `AA/55` 帧标志的大端 `int16_t` 波形采样接收
- UART3 既支持可选的 `AA + int16_t + 55` 大端采样流，也支持以 `\r\n` 结尾的
  上位机命令；当前菜单已接入波形、频谱、幅频、相频和文本控制页面
- UART3 数据页覆盖 21 条命令：模型/扫频准备、帧式或固定长度裸数字响应、
  `error`、协议错误、取消和本地超时均有明确状态
- I2C0 驱动 0.96 寸 SSD1306 OLED，I2C1 独立驱动 MPU6050
- SPI0 驱动 1.8 寸 128×160 ST7735S TFT，与 OLED 编译期二选一
- 通用多级菜单、自动滚动和动作回调；当前默认使用 TFT，并从主菜单启动，
  也可在编译期切换 OLED 或电赛自定义首页
- PA27 当前默认 1024 点/1 MHz 按键单次测量；第二路物理 ADC 输入为
  PB19/ADC1.6，当前默认关闭；UART2 独立输入收满 1024 点后显示最后 128 点
- PA18、PB21 板载按键防抖及长短按识别
- PB0/PB7/PB12/PB13 与 PA13/PA12/PA29/PA30 组成的 4×4 矩阵键盘扫描和独立防抖
- PA27/PB19 双路 12 位 ADC：按次由 DMA 直接采满配置窗口，处理后保持停止；
  两路最高均支持 4 MHz
- CMSIS-DSP 最大 2048 点 Q15 ADC FFT；UART2 独立输入 FFT 为 64 点
- 双路统一波形输入：PA27/PB19 独立采样并测幅值/占空比；可选的比较器捕获
  仍使用 PA27/PA21，因此第二路需要精确硬件测频时要把同一信号同时送到 PB19 和 PA21
- PA27、PB19 可通过 `APP_ENABLE_WAVEFORM_PA27/PB19` 分别启用或关闭；旧的
  `PA21` 配置名和枚举只作为源码兼容别名保留
- UART2 以 VOFA+ JustFloat 格式发送 PA27/PB19 ADC 原始码或自定义浮点数据源
- PA15 12位DAC，正弦/三角/锯齿波最高62.5kHz、方波最高500kHz，采用Timer + DMA查找表输出
- PA23 通用 PWM 输出，支持运行时修改频率、占空比和启停状态
- PA23、PA24 双路 `ServoControl` RTOS 控制，共用 50 Hz 周期并可独立设角度、启停和查询状态
- PA17/PA16 双路 TB6612 电机 PWM，支持平滑正反转、滑行/制动和紧急待机
- SPI1 控制 AD9833 DDS，支持正弦/三角/方波、频率、相位和启停菜单
- AD9850 可选后端与 AD9833 共用 PB9/PB8，并使用 PB5 FQ_UD、PA1 RESET；默认关闭
- PA27/COMP0/TIMG12 与 PA21/COMP2/TIMG6 分别测量两路模拟周期信号频率
- 独立 LED、RGB LED 闪烁示例

## 软件架构

```text
Application：业务逻辑、菜单内容、FreeRTOS 任务
       ↓
Module：ADC、Capture、DAC、DDS、FFT、Button、Matrix Keypad、Display、Menu、OLED、TFT、Serial、SPI、PWM、Servo、LED、I2C
       ↓
BSP：ADC、GPIO、UART、I2C、SPI、PWM 板级封装
       ↓
TI DriverLib + SysConfig
       ↓
MSPM0G3507
```

主要目录：

```text
application/
├── app_config.h            应用功能编译开关
├── communication/         通信相关 Application
│   └── serial_communication/ 串口通信和 ADC JustFloat 业务
├── control/               舵机、电机等执行机构控制 Application
│   ├── servo_control/     PA23/PA24 双路舵机平滑移动控制任务
│   └── motor_control/     TB6612 双路直流电机平滑调速任务
├── input/                 按键等输入设备 Application
│   └── matrix_keypad_input/ 4×4 矩阵键盘扫描和事件队列任务
├── menu/                   菜单相关 Application
│   ├── display_menu/       OLED/TFT 共用页面和按键任务
│   ├── oled_menu/          SSD1306 菜单入口
│   └── tft_menu/           ST7735S 菜单入口与接线指南
├── task/                   Application RTOS 任务统一管理
└── waveform/               波形相关 Application
    ├── waveform_mapping/   PA27 测量结果自动映射
    ├── waveform_measurement/ 基础波形参数测量应用
    └── waveform_output/    DAC 和 DDS 统一波形输出应用

modules/
├── adc/                    PA27/PB19 ADC 采样实例和数值换算
├── capture/                COMP+Timer 捕获服务和频率换算
├── dac/                    线程安全 DAC、数值换算和周期波形输出
├── dds/                    通用 DDS、AD9833 后端和便捷输出服务
├── fft/                    CMSIS-DSP FFT 和双路 ADC 频谱分析服务
├── button/                 按键防抖和长短按
├── i2c/                    线程安全 I2C 接口
├── led/                    LED 控制和 Blinky 静态任务
├── menu/                   通用菜单状态和渲染
├── matrix_keypad/          4×4 矩阵键盘扫描、独立防抖和按键事件
├── display/                OLED/TFT 通用 128×64 逻辑显示接口
├── oled/                   SSD1306 注册、初始化、帧缓冲和绘图
├── tft/                    ST7735S 初始化、RGB565 转换和绘图
├── pwm/                    通用 PWM 控制和 PA23 便捷输出
├── servo/                  基于 PA23/PA24 PWM 的双路 50 Hz 舵机控制
├── tb6612/                 TB6612 双路电机方向、占空比和待机控制
├── serial/                 串口队列和发送接口
├── spi/                    线程安全 SPI 总线接口
└── waveform/               实时波形缓存和绘制

bsp/
├── board_config.h          SysConfig 未导出的板级时钟与外部 DDS MCLK
├── adc/                    TIMG0 触发、ADC0/ADC1 一次性 N 点 DMA
├── capture/                双 COMP 事件和双 Timer 时间戳捕获封装
├── dac/                    DAC0 与 PA15 模拟输出封装
├── gpio/                   GPIO 输入输出封装
├── i2c/                    MSPM0 I2C Controller 封装
├── pwm/                    MSPM0 定时器 PWM 封装
├── tb6612/                 TIMA1 电机 PWM 与方向/STBY GPIO 封装
├── spi/                    SPI1 DDS 与 SPI0 TFT 阻塞发送封装
└── uart/                   MSPM0 UART 和 DMA 封装
```

更详细的分层规则请阅读
[架构介绍与开发指南](docs/架构介绍与开发指南.md)。

## 外设和引脚

| 外设 | 引脚 | 用途 |
| --- | --- | --- |
| GPIOA | PA0 | 独立 LED，开漏输出 |
| GPIOB | PB22 | RGB 蓝灯 |
| GPIOB | PB26 | RGB 红灯 |
| GPIOB | PB27 | RGB 绿灯 |
| UART0 | PA10 | 调试串口 TX，115200-8-N-1 |
| UART1 | PA8 / PA9 | TX / RX，115200-8-N-1 |
| UART2 | PB15 / PB16 | TX / RX，115200-8-N-1 |
| UART3 | PA26 / PA25 | TX / RX，115200-8-N-1 |
| I2C0 | PA31 / PA28 | OLED SCL / SDA，400 kHz |
| I2C1 | PB2 / PB3 | MPU6050 SCL / SDA，400 kHz |
| SPI0 | PB18 / PB17 | TFT SCLK / MOSI，8 MHz Mode 0 |
| GPIOB | PB20 / PB1 / PB4 | TFT CS / DC / RESET |
| ADC0 通道 0 / COMP0 IN0- | PA27 | 统一波形输入 0，ADC 测幅值、COMP 测周期 |
| ADC1 通道 6 | PB19 | 第二路 ADC 波形输入，当前默认关闭 |
| COMP2 IN1- | PA21 | 第二路可选硬件周期捕获；不是当前 ADC1 输入 |
| DAC0 | PA15 | 12 位模拟输出，参考电压为 VDDA/VSSA |
| TIMG0 | 内部事件 | 1 MHz 同步触发 ADC0 和 ADC1 |
| TIMG12 | 内部事件 | 4 MHz、32 位 COMP0 边沿时间戳捕获 |
| TIMG6 | 内部事件 | 62.5 kHz、16 位 COMP2 边沿时间戳捕获 |
| TIMG7 CCP0 | PA23 | PWM/舵机复用输出；通用 PWM 默认 1 kHz、50%，舵机固定 50 Hz |
| TIMG7 CCP1 | PA24 | 第二路舵机 PWM 输出；与 CCP0 共用 50 Hz 周期、脉宽独立 |
| TIMA1 CCP0 / CCP1 | PA17 / PA16 | TB6612 PWMA / PWMB，默认 20 kHz |
| GPIOB | PB10 / PB11 | TB6612 AIN1 / AIN2 |
| GPIOB | PB14 / PB23 / PB25 | TB6612 BIN1 / BIN2 / STBY |
| SPI1 | PB9 / PB8 | AD9833 SCLK / SDATA，1 MHz Mode 2 |
| GPIOB | PB6 | AD9833 FSYNC，低电平有效 |
| GPIOB / GPIOA | PB5 / PA1 | AD9850 FQ_UD / RESET，可选且默认关闭 |
| GPIO | PB0/PB7/PB12/PB13 | 4×4 矩阵键盘 R1/R2/R3/R4 行输出 |
| GPIO | PA13/PA12/PA29/PA30 | 4×4 矩阵键盘 C1/C2/C3/C4 列输入上拉 |
| GPIOA | PA18 | 板载 S1，菜单下一项/确认 |
| GPIOB | PB21 | 板载 S2，菜单上一项/返回 |
| DEBUGSS | PA20 / PA19 | SWCLK / SWDIO |

DAC0 的 12 位片外模拟输出保留在 PA15。第二路 ADC 在当前 SysConfig 中使用
PB19/ADC1.6；旧版代码曾把它称为 PA21，因此公开 API 中仍保留少量 `PA21`
兼容名字。PA21 现在只用于 COMP2 周期捕获，不应再接作 ADC1 输入。

两路 ADC 采样率和 12 位电压分辨率相同，但 COMP 周期捕获精度不同：
PA27/TIMG12 是 4 MHz、0.25 us/tick；PA21/TIMG6 为了让 16 位计数器覆盖约
1 s 周期，使用 64 分频后为 62.5 kHz、16 us/tick。

## OLED 接线

工程支持常见的 0.96 寸、128×64、I2C SSD1306 OLED，7 位地址为 `0x3C`；
当前编译默认使用 TFT，切换到 OLED 时再按下表接线并修改显示开关。

| OLED | LP-MSPM0G3507 |
| --- | --- |
| VCC | 3V3 |
| GND | GND |
| SCL | PA31 |
| SDA | PA28 |

SCL 和 SDA 必须有上拉电阻。多数 OLED 模块已经带上拉；如果没有，可分别使用
约 4.7 kΩ 电阻上拉到 3.3 V。

MPU6050 使用独立的 I2C1：SCL 接 PB2，SDA 接 PB3；它不与 OLED 共用 I2C 引脚。
MPU6050 的 7 位地址为 `0x68` 或 `0x69`。两组 I2C 的 SCL/SDA 都必须有上拉电阻。

注意：为给 OLED 腾出 I2C0 的 PA28/PA31，TIMG7 双路 PWM/舵机已迁移到 PA23/PA24。

OLED 详细接口和排查方法见
[OLED 使用指南](modules/oled/OLED使用指南.md)。

## 1.8 寸 TFT 接线

当前支持常见的 128×160 ST7735S SPI 模块：`PB18=SCK`、`PB17=MOSI`、
`PB20=CS`、`PB1=DC`、`PB4=RESET`，另接 `3V3`、`GND` 和背光。
完整接线、OLED/TFT 切换方法和故障排查见
[TFT 菜单与接线指南](application/menu/tft_menu/TFT菜单与接线指南.md)。

## AD9833 DDS 接线

| AD9833 | LP-MSPM0G3507 |
| --- | --- |
| SCLK | PB9 |
| SDATA | PB8 |
| FSYNC | PB6 |
| GND | GND |

默认按带 25 MHz 晶振的常见 AD9833 模块配置，PB7 不连接。模块晶振不同应修改
`bsp/board_config.h` 中的 `BSP_BOARD_DDS_REFERENCE_CLOCK_HZ`，也可由构建配置覆盖
`DDS_OUTPUT_REFERENCE_CLOCK_HZ`。MCLK 与
SPI SCLK 相互独立；VOUT 是小幅模拟
输出而不是 3.3 V 逻辑电平，实际负载可能需要缓冲、滤波或放大。

## 菜单按键

| 按键 | 短按 | 长按 |
| --- | --- | --- |
| S1 / PA18 | 下一项 | 确认、进入或执行；对比度项保持调整 |
| S2 / PB21 | 上一项 | 返回上一层 |

- 软件防抖时间：30 ms
- 长按触发时间：800 ms
- PA18 高电平有效，请检查板载 S1 对应的 J8 跳线
- PB21 低电平有效，SysConfig 已配置内部上拉

通用菜单扩展方法见
[OLED 菜单使用指南](application/menu/oled_menu/OLED菜单使用指南.md)。

波形页支持 PA27、可选 PB19、UART2，以及 UART3 上位机返回的多种曲线；详细用法见
[OLED 实时波形使用指南](application/menu/oled_menu/OLED实时波形使用指南.md)。

`DAC OUTPUT` 菜单支持关闭输出、选择固定直流电压，以及输出1/10/100Hz、
1/5/10/20/31.25/62.5kHz正弦波、方波、三角波和锯齿波；方波额外提供
500kHz档位。1Hz～1kHz选择成功后会自动进入ADC回环波形页面；更高频率应使用
示波器观察PA15。

`DDS OUTPUT` 菜单支持 AD9833 启停、正弦/三角/方波、1 Hz～1 MHz 预设频率和
0/45/90/180/270° 预设相位。

PA27/PA21 的 COMP + Timer Capture 由每次波形测量请求按需启动，用于提高
频率和周期的测量精度，不再单独显示在菜单中。这里的 PA21 是 COMP2 输入；
第二路电压样本来自 PB19。默认比较阈值为 1.65 V，需要调整时通过 Analog
Capture API 设置。PA27 默认可连接板载光电二极管；测量外部信号前应断开 J17。

`FFT SPECTRUM` 菜单可选 PA27、可选 PB19、UART2 或 UART3 频谱，显示 32 个
单边频谱柱和主峰频率；本地 ADC/UART2 结果可分页查看最多 16 个有效频率分量。
PA27 当前默认使用 1 MHz/1024 点，可观察 0～500 kHz，原始 bin 间隔约
976.6 Hz；PB19 启用后的默认值相同。UART3 数据频谱当前不附带分量列表，
`compa`/`compb` 的分量结果通过 UART3 文本页面显示。
UART2 默认按 100 samples/s 换算，可观察 0～50 Hz。高频模拟输入需要低阻抗
驱动或缓冲，并按目标带宽配置抗混叠滤波。

## 开发环境

- 开发板：LP-MSPM0G3507
- MCU：MSPM0G3507
- IDE：Code Composer Studio Theia
- 编译器：TI ARM Clang
- SDK：MSPM0 SDK 2.11.00.07
- RTOS：FreeRTOS

## 编译和运行

1. 在 CCS Theia 中导入本工程。
2. 在 `application/app_config.h` 或当前 Build Configuration 的预定义符号中选择
   本项目需要的功能。
3. 确认 MSPM0 SDK 和配套 FreeRTOS 构建库已经安装；构建会自动检查外部
   `FreeRTOSConfig.h` 的断言安全态配置及静态库是否已重建。
4. 打开 `blink_led.syscfg`，检查器件和引脚配置。
5. 执行 Project → Clean，然后执行 Project → Build。
6. 连接 LP-MSPM0G3507，下载并运行生成的程序。

工程初始化顺序：

```text
BSPInit()
SerialCommunicationInit()
WaveformMeasurementInit()[APP_ENABLE_WAVEFORM_MEASUREMENT]
  ├─ ADCSamplingInitInput()   [已启用 PA27/PB19，注册后停止]
  ├─ FFTAnalysisInit()
  └─ AnalogCaptureInitInput() [逻辑输入 0/1 对应 PA27/PA21 COMP，注册后停止]
ADCJustFloatInit()      [APP_ENABLE_ADC_JUSTFLOAT]
WaveformOutputInit()    [APP_ENABLE_WAVEFORM_OUTPUT]
  ├─ DACOutputInit()    [APP_ENABLE_WAVEFORM_OUTPUT_DAC]
  └─ DDSOutputInit()    [APP_ENABLE_WAVEFORM_OUTPUT_DDS]
WaveformMappingInit()   [APP_ENABLE_WAVEFORM_MAPPING]
ServoControlInit()      [APP_ENABLE_SERVO_CONTROL，初始输出由启动标志控制]
TB6612ControlInit()     [APP_ENABLE_MOTOR_CONTROL，上电保持 STBY 低]
OLEDMenuInit() / TFTMenuInit() [显示二选一]
  ├─ OLEDDisplayInit() / TFTDisplayInit()
  ├─ DisplayMenuInit()
  └─ PWMOutputInit()    [APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT]
vTaskStartScheduler()
```

所有输出后端遵循安全启动：BSP 会先停止 SysConfig 默认活动的 ADC/COMP/DAC/PWM，
并无条件让外部 AD9833 进入复位休眠；DAC、DDS、TB6612、舵机和通用 PWM 在显式设置或
启动前保持关闭。
ADC DMA 完成后通知测量任务累计，收齐每路配置点数后对完整窗口执行 FFT；
JustFloat 也按块唤醒。UART1～UART3 DMA 发送具有超时恢复，
UART2/UART3 波形采样按订阅分发，Application 任务全部使用静态栈。

UART1～UART3 也分别由 `APP_ENABLE_UART1`～`APP_ENABLE_UART3` 控制。完整说明见
[Application 编译配置使用指南](application/编译配置使用指南.md)。

如果所选显示后端初始化失败，`ApplicationInit()` 会返回错误，程序不会
进入 FreeRTOS 调度器。此时应按所选屏幕检查供电、接线和配置开关。

## UART0 调试输出

串口和显示菜单 Application 提供调试输出开关。正常上电时可能看到：

```text
DISPLAY MENU INIT
DISPLAY MENU READY
```

具体开关和串口接口说明见
[UART DMA 发送接口使用指南](application/communication/serial_communication/UART_DMA发送接口使用指南.md)。

## 相关资料

- [工程架构说明](docs/架构介绍与开发指南.md)
- [Application 编译配置使用指南](application/编译配置使用指南.md)
- [ADC 采样使用指南](modules/adc/ADC采样使用指南.md)
- [ADC FFT 频谱使用指南](modules/fft/FFT分析使用指南.md)
- [波形参数测量使用指南](application/waveform/waveform_measurement/WaveformMeasurement使用指南.md)
- [Waveform Output 使用指南](application/waveform/waveform_output/WaveformOutput使用指南.md)
- [Blinky 使用指南](modules/led/Blinky使用指南.md)
- [OLED 使用指南](modules/oled/OLED使用指南.md)
- [OLED 菜单使用指南](application/menu/oled_menu/OLED菜单使用指南.md)
- [OLED 实时波形使用指南](application/menu/oled_menu/OLED实时波形使用指南.md)
- [TFT 菜单与接线指南](application/menu/tft_menu/TFT菜单与接线指南.md)
- [PWM Output 使用指南](modules/pwm/PWMOutput使用指南.md)
- [Servo Module 使用指南](modules/servo/Servo使用指南.md)
- [舵机控制任务使用指南](application/control/servo_control/舵机控制任务使用指南.md)
- [电机控制任务使用指南](application/control/motor_control/电机控制任务使用指南.md)
- [DDS Module 使用指南](modules/dds/DDS使用指南.md)
- [COMP + Timer Capture 使用指南](modules/capture/AnalogCapture使用指南.md)
- [UART DMA 发送接口使用指南](application/communication/serial_communication/UART_DMA发送接口使用指南.md)
- [UART3 上位机通信协议](tools/uart3_host_simulator/UART3上位机通信协议.md)
- [TI LP-MSPM0G3507 产品页面](https://www.ti.com/tool/LP-MSPM0G3507)

## 许可证

工程中来源于 TI MSPM0 SDK 示例的代码继续遵循其原始许可条款；新增业务代码请
根据项目实际发布需求补充明确的开源许可证。
