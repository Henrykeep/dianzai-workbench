# BSP 初始化指南

## 1. BSP 的作用

BSP（Board Support Package，板级支持包）负责把 MSPM0G3507 的真实外设、引脚和 TI DriverLib 封装成项目内部统一接口。

本项目只有 BSP 层可以直接包含以下内容：

- `ti_msp_dl_config.h`
- TI DriverLib 头文件
- SysConfig 生成的外设宏
- 芯片寄存器和中断号

`modules/` 和 `application/` 应使用 BSP 提供的接口，不应绕过 BSP 直接操作寄存器。

## 2. 初始化入口

公开接口位于 `bsp/bsp.h`：

```c
bool BSPInit(void);
void BSPDelayMilliseconds(uint32_t milliseconds);
bool BSPFlashEraseMainSector(uint32_t address);
bool BSPFlashProgramMain64WithECC(
    uint32_t address, const uint32_t words[2]);
void BSPEnterSafeState(void);
```

`BSPInit()` 首次调用先执行公共初始化：

```c
SYSCFG_DL_initPower();
SYSCFG_DL_GPIO_init();
SYSCFG_DL_SYSCTL_init();
```

随后按 `app_config.h` 的功能开关调用对应的 SysConfig 外设初始化函数，使链接器可移除
关闭功能的初始化代码；DMA 会在 DAC、ADC 或任一 DMA 串口启用时初始化。AD9833 的
SPI 例外地始终初始化，以便上电主动发送休眠控制字。最后停止 SysConfig 默认启用的
ADC 转换、比较器、DAC 和 PWM 活动输出。返回 `true` 才表示基础配置和安全态都已建立。

## 3. 调用顺序

应在注册任何功能模块以及启动 FreeRTOS 调度器之前调用一次：

```text
main()
  └─ ApplicationInit()
       ├─ BSPInit()
       ├─ 注册并初始化各 modules/application 实例
       └─ 创建任务
  └─ vTaskStartScheduler()
```

典型代码：

```c
Framework_Status_e ApplicationInit(void)
{
    if (!BSPInit()) {
        return FRAMEWORK_STATUS_ERROR;
    }

    /* BSP 初始化完成后才能注册 GPIO、UART、ADC 等模块。 */
    return FRAMEWORK_STATUS_OK;
}
```

`BSPInit()` 使用 `UNINITIALIZED/INITIALIZING/READY/FAILED` 一次性状态。READY 后
重复调用会直接返回 `true`，不会再次复位硬件；初始化中重入或首次失败后返回 `false`。

## 4. `BSPInit()` 会做什么

它负责完成硬件基础配置，但不等于启动所有业务功能。

例如：

- ADC 的时钟、引脚、触发事件和 DMA 路由由 SysConfig 准备；BSP 入口会关闭生成代码
  默认打开的转换/DMA，一次性采集仍需调用 `BSPADCStartDirectCapture()` 或同步采集接口。
- COMP 的配置和事件路由由 SysConfig 准备；BSP 入口会先关闭比较器，捕获应用调用
  `BSPCaptureStart()` 后才启用。
- DAC 外设由 SysConfig 生成代码启用，但 BSP 入口会立刻关闭，模拟输出仍需调用
  `BSPDACSetEnabled()`。
- PWM 定时器和引脚复用由 SysConfig 准备，但输出仍需调用 `BSPPWMSetEnabled()`。
- SPI1 和 FSYNC 由 SysConfig 准备；BSP 入口会无条件向外部 AD9833 发送
  `RESET + SLEEP1 + SLEEP12`，再关闭 SPI，避免 MCU 单独复位时保留旧波形。
- UART 硬件由 SysConfig 准备，接收回调和 DMA 状态由 `BSPUARTRegister()` 注册。

`BSPEnterSafeState()` 不获取 FreeRTOS 互斥锁，可在 NMI、HardFault、未实现中断和
栈溢出等致命错误路径停止 ADC/捕获/PWM 定时器、ADC 与 UART DMA，关闭 COMP、DAC，
并在有限轮询内直接向 AD9833 写入 `RESET + SLEEP1 + SLEEP12`，随后关闭 SPI。若 SPI
或外部 DDS 已损坏，这次写入仍可能失败；需要硬件级故障安全输出的产品应增加独立
输出使能、模拟开关或电源关断。

当前工作区配套的外部 FreeRTOS kernel build 已将 `configASSERT` 配置为调用
`ApplicationFatalHalt()`，并已重新生成静态库，因此内核断言也会进入本工程的安全态。
本框架所有 Application 任务、队列和互斥量都使用静态创建，因此配套配置
还会关闭未使用的 FreeRTOS Timer Service，并把为 `heap_4.c` 构建兼容保留的
备用堆从 3 KiB 缩小为 256 B。
该 kernel 工程不属于本仓库；仅克隆本仓库或更换 kernel build 后，需要在对应
`FreeRTOSConfig.h` 中声明 `extern void ApplicationFatalHalt(void);`，将 `configASSERT`
配置为失败时调用该函数，并重新生成 FreeRTOS 静态库。应用工程的普通编译不会替它
重建。仓库提供 [`FreeRTOSConfig.assert.patch`](../freertos/FreeRTOSConfig.assert.patch)
和 [`FreeRTOSConfig.resource.patch`](../freertos/FreeRTOSConfig.resource.patch)。在外部
kernel 工程目录中依次应用两个补丁并重建静态库，然后可执行：

```bash
python tools/check_freertos_config.py \
  ../freertos_builds_LP_MSPM0G3507_release_ticlang/FreeRTOSConfig.h \
  --library ../freertos_builds_LP_MSPM0G3507_release_ticlang/Debug/\
freertos_builds_LP_MSPM0G3507_release_ticlang.lib
```

该命令同时检查安全态、静态分配、Timer Service、备用堆、静态库
更新时间和库中的安全态符号；检查失败时不要继续发布固件。
CCS/生成 Makefile 的 `all` 目标会通过仓库根目录 `makefile.targets` 自动运行该检查；
若 kernel 工程不在默认相邻目录，可用 `FREERTOS_CONFIG=/绝对路径/FreeRTOSConfig.h`
和 `FREERTOS_LIBRARY=/绝对路径/freertos.lib` 覆盖路径。

## 5. 修改硬件配置

需要调整引脚、波特率、定时器、DMA 通道或中断时：

1. 在 CCS SysConfig 中打开 `blink_led.syscfg`。
2. 修改对应外设配置。
3. 保存并让 SysConfig 重新生成 `ti_msp_dl_config.c/.h`。
4. 同步检查 BSP 中使用的宏、DMA 通道和中断服务函数。
5. 重新完整编译并烧录。

不要直接修改 `Debug/` 下生成的 `ti_msp_dl_config.c/.h`，重新生成配置时这些修改会丢失。

## 6. BSP 与其他层的边界

推荐依赖方向：

```text
application → modules → bsp → DriverLib / SysConfig / hardware
```

- BSP：描述“这个板子有什么硬件、接在哪个引脚、怎样操作寄存器”。
- Modules：提供线程安全、单位换算、状态管理和通用功能接口。
- Application：组合模块，实现菜单、波形、串口协议等业务。

UART/I2C 的底层等待仍位于 BSP。它们会读取 FreeRTOS 调度状态：UART DMA 在调度器
运行时使用短延时等待，I2C 长轮询会主动让出 CPU；调度器启动前则保持有限轮询。
因此这两组接口可在初始化和任务上下文调用，但不能从 ISR 调用。互斥与多任务串行化
仍由 `modules/serial`、`modules/i2c` 提供。

除硬件定位和基础收发外，协议解析、界面逻辑、滤波算法等内容不应放入 BSP。

`BSPFlashEraseMainSector()` 和 `BSPFlashProgramMain64WithECC()` 只封装必需的
DriverLib 时序和中断保护，不分配 Flash 地址。上层必须只操作链接脚本
预留的用户数据区；擦写期间全局中断会被短暂关闭，不应在实时输出中执行。

## 7. 常见问题

### 外设注册返回 `NULL`

检查逻辑通道枚举是否有效，并确认 `BSPInit()` 已经先执行。

### 修改 SysConfig 后行为没有变化

执行一次 Clean/Rebuild，确认烧录的是当前工程最新生成的 `.out` 文件。

### 串口发送返回失败

UART DMA 等待已有按数据长度和波特率计算的超时，不会永久等待。检查全局中断、
NVIC、中断服务函数和 DMA 路由；可读取 Application 串口发送失败计数定位间歇故障。
