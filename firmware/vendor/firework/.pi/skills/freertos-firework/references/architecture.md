# 项目架构速查

## 平台与启动

- 目标：TI MSPM0G3507，TI ARM Clang，FreeRTOS，CCS/SysConfig 工程。
- `main.c` 调用 `ApplicationInit()`，成功后由 `ApplicationStart()` 启动调度器；失败和
  Fault 进入安全关断。
- `application/application.c` 负责 BSP、串口、测量、输出、输入和显示菜单的初始化顺序。
- `application/app_config.h` 决定编译进产品的功能和参数。分析任一功能前先查其
  `APP_ENABLE_*` 条件。

## 分层所有权

| 层 | 职责 | 约束 |
| --- | --- | --- |
| `bsp/` | 寄存器、DriverLib、SysConfig 外设和中断 | 唯一可直接依赖 TI 硬件细节的层 |
| `modules/` | 可复用驱动封装、算法和通用服务 | 不直接包含 DriverLib/SysConfig 类型 |
| `application/` | 产品编排、任务、页面、通信和业务状态 | 通过 Module/BSP 公共接口组合能力 |

Application 任务的静态 TCB、栈和优先级统一在 `application/task/task_manager.*`。
新增 Application 任务必须扩展 `ApplicationTask_e`、配置静态资源并调用
`ApplicationTaskCreate()`。

## 常见链路

### UART3 页面

```text
MenuItem / CustomPage route
  -> DisplayMenuAction... / DisplayMenuRequest...
  -> SerialCommunicationUART3RequestData() 或 RequestPreparedData()
  -> UART3 RX task 按行解析、检查绝对截止时间
  -> 非频谱：128 点通过样本订阅送到 display_menu
  -> 频谱：FFTAnalysisPublishExternalSpectrum() 发布 UART3 快照
  -> DisplayMenuTask() 轮询事务状态并刷新页面
```

### 本地波形测量

```text
display_menu / other application request
  -> WaveformMeasurementRequestInput()
  -> PA27/PB19 ADC Sampling + DMA + FFT Analysis
  -> 可选 PA27/PA21 Analog Capture（第二路 ADC 与 Capture 不同脚）
  -> 测量任务发布完整结果快照
  -> 页面、映射或 UART2 JustFloat 订阅者消费
```

### 波形输出

```text
菜单/映射 -> application/waveform/waveform_output
          -> modules/dac 或 modules/dds
          -> bsp/dac 或 bsp/spi
```

## 资源与并发检查点

- UART、ADC、DMA、显示和输出都可能跨 ISR/任务上下文；先确认回调执行上下文。
- 大数组通常是静态缓冲或快照。不要在任务栈上复制整帧 FFT/ADC 数据。
- 共享状态沿用临界区、互斥锁、队列或“序列号 + 快照”设计。
- 页面退出要取消本地请求；异步上位机操作本身可能无法中止，所以必须丢弃迟到响应。
- 关闭输出、初始化失败、HardFault 和栈溢出都要保持安全态路径。
- 当前默认显示为 TFT、上电进入 MAIN MENU；PA27 默认 1024 点/1 MHz，PB19 默认关闭。

## 主要资料入口

- 总体架构：`docs/架构介绍与开发指南.md`
- Application：`application/README.md`、`application/编译配置使用指南.md`
- 任务：`application/task/README.md`
- Module/BSP：`modules/README.md`、`bsp/README.md`
- 各功能的中文使用指南位于对应源码目录，阅读后仍须回到当前源码核对。
