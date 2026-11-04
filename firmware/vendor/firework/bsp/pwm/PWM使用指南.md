# BSP PWM 使用指南

## 1. 硬件配置

| 逻辑通道 | 定时器输出 | 引脚 | 计数时钟 |
| --- | --- | --- | --- |
| `BSP_PWM_CHANNEL_OUTPUT_0` | TIMG7 CCP0 | PA23 | 1 MHz |
| `BSP_PWM_CHANNEL_OUTPUT_1` | TIMG7 CCP1 | PA24 | 1 MHz |

当前定时器支持的周期计数范围为 `2～65535`。两路共用 TIMG7 周期，比较值独立。

## 2. 公开接口

```c
BSPPWMInstance *BSPPWMRegister(BSP_PWM_Channel_e channel);
bool BSPPWMConfigure(BSPPWMInstance *instance,
    uint32_t period_counts, uint32_t compare_counts);
bool BSPPWMSetEnabled(BSPPWMInstance *instance, bool enabled);
void BSPPWMEnterSafeState(void);
uint32_t BSPPWMGetClockFrequency(const BSPPWMInstance *instance);
uint32_t BSPPWMGetMaximumPeriodCounts(const BSPPWMInstance *instance);
```

BSP 使用定时器原始计数值，不直接接收频率和占空比参数。
`BSPPWMEnterSafeState()` 不获取 RTOS 锁，用于 fault 路径一次关闭两路输出。

## 3. 基本使用

下面以 1 MHz 计数时钟输出约 1 kHz、50% 占空比为例：

```c
BSPPWMInstance *pwm =
    BSPPWMRegister(BSP_PWM_CHANNEL_OUTPUT_0);

if (pwm != NULL) {
    (void)BSPPWMConfigure(pwm, 1000U, 500U);
    (void)BSPPWMSetEnabled(pwm, true);
}
```

频率换算：

```text
PWM 频率 ≈ 计数时钟 ÷ period_counts
         ≈ 1,000,000 ÷ 1000
         ≈ 1000 Hz
```

本项目的比较输出极性决定了模块层使用以下换算：

```text
compare_counts = period_counts × (100% - duty) ÷ 100%
```

普通应用应使用 `modules/pwm`，由模块层负责频率、占空比与计数值之间的换算。

## 4. 注册和启停行为

- `BSPPWMRegister()`：注册逻辑通道，并暂时断开该通道的 CCP 输出方向。
- `BSPPWMConfigure()`：设置周期计数和比较计数。
- `BSPPWMSetEnabled(true)`：连接对应 CCP；第一路启动时同时启动定时器。
- `BSPPWMSetEnabled(false)`：断开对应 CCP；最后一路关闭时才停止定时器。

注册并不代表 PWM 已经开始输出，必须配置参数后显式启用。

## 5. 运行时更新

PWM 停止时，配置会直接写入负载和比较寄存器。

PWM 运行时，配置写入影子寄存器，并在计数器归零事件同步生效，避免在一个周期中间突然修改参数产生异常窄脉冲。

`compare_counts` 不得大于 `period_counts`，否则配置失败。另一通道运行时，如果尝试
把共享周期改成不同值，配置会返回 `false`，避免破坏正在输出的波形。

## 6. 参数范围

获取硬件限制：

```c
uint32_t clock_hz = BSPPWMGetClockFrequency(pwm);
uint32_t max_period = BSPPWMGetMaximumPeriodCounts(pwm);
```

在 1 MHz 计数时钟、最大周期 65535 的条件下，最低可配置频率约为：

```text
1,000,000 ÷ 65,535 ≈ 15.3 Hz
```

需要更低频率时，应在 SysConfig 中调整定时器时钟或预分频，并同步检查上层换算。

## 7. 并发与硬件注意事项

- BSP PWM 不提供 FreeRTOS 互斥锁，多任务控制应通过 `modules/pwm`。
- PA23/PA24 必须保持 TIMG7 CCP0/CCP1 引脚复用，不能同时当作普通 GPIO 输出。
- 停止 PWM 后引脚输出状态取决于引脚复用和外部电路，不应假设一定保持高或低。
- 驱动电机、蜂鸣器或大功率负载时，PA23/PA24 只能提供逻辑信号，需要外接驱动电路。
