# PID 使用指南

`modules/pid/` 提供与 ADC、PWM、DAC 和具体业务无关的位置式 PID 控制器。模块使用
静态实例池，不申请动态内存，并实现输出限幅、积分限幅和条件积分抗饱和。

## 1. PID 计算公式

```text
误差 e = 设定值 - 测量值

输出 = Kp × e
     + Ki × ∫e dt
     + Kd × de/dt
```

- `Kp`：误差越大，比例输出越大。
- `Ki`：消除长期存在的静差，但过大会产生积分饱和和振荡。
- `Kd`：根据变化趋势提前抑制过冲，但对测量噪声比较敏感。

## 2. 注册 PID 实例

```c
#include "modules/pid/pid.h"

static PIDInstance *speed_pid;

bool SpeedPIDInit(void)
{
    static const PIDConfig config = {
        .kp = 1.20F,
        .ki = 0.50F,
        .kd = 0.02F,
        .output_minimum = 0.0F,
        .output_maximum = 100.0F,
        .integral_minimum = -30.0F,
        .integral_maximum = 30.0F,
        .derivative_mode = PID_DERIVATIVE_ON_MEASUREMENT
    };

    speed_pid = PIDRegister(&config);
    return speed_pid != NULL;
}
```

当前静态池最多提供 4 个 PID 实例。电机速度、温度、电压等不同控制环必须分别注册
实例，不能共用历史状态。

## 3. 周期计算

假设控制任务固定每 10 ms 执行一次：

```c
float output;

if (PIDProcess(speed_pid, target_speed, measured_speed,
        0.010F, &output)) {
    /* output 已被限制在 0～100，可转换为 PWM 占空比。 */
    (void)PWMOutputSetDutyCycle((uint8_t)(output + 0.5F));
}
```

`delta_time_seconds` 的单位必须是秒：

| 控制周期 | 传入值 |
|---|---:|
| 1 ms | `0.001F` |
| 10 ms | `0.010F` |
| 100 ms | `0.100F` |

第一次调用没有足够的历史数据，微分项自动按 0 处理。

## 4. 微分模式

### 对误差微分

```c
.derivative_mode = PID_DERIVATIVE_ON_ERROR
```

微分项使用误差变化率。设定值突然变化时会产生较大的微分响应，适合需要快速响应且
设定值变化较平缓的场景。

### 对测量值微分

```c
.derivative_mode = PID_DERIVATIVE_ON_MEASUREMENT
```

微分项使用测量值变化率的负值，可以减小设定值阶跃造成的“微分冲击”。一般电机、
温度和电压闭环建议优先使用此模式。

## 5. 限幅和抗积分饱和

`output_minimum` 和 `output_maximum` 限制最终控制量，例如 PWM 使用 `0～100`，双向
控制可能使用 `-100～100`。

`integral_minimum` 和 `integral_maximum` 单独限制积分项。当最终输出已经饱和，而且
本周期新增积分会让饱和更严重时，模块会放弃本周期积分；误差反向、输出开始离开
饱和区时仍允许积分回退。

积分上下限需要根据执行器范围调整，不能盲目设置得非常大。

## 6. 重置和重新配置

停止控制、切换目标对象或重新启动一次控制过程时，应清除历史：

```c
(void)PIDReset(speed_pid);
```

运行期间修改 PID 参数可以调用：

```c
(void)PIDConfigure(speed_pid, &new_config);
```

`PIDConfigure()` 会应用新参数，同时清空积分、微分历史和最近输出，防止旧参数的状态
直接带入新控制环。

最近一次成功输出可以读取：

```c
float last_output;

if (PIDGetLastOutput(speed_pid, &last_output)) {
    /* 使用 last_output。 */
}
```

## 7. 参数整定建议

可以从最简单的步骤开始：

1. 先设置 `Ki = 0`、`Kd = 0`，逐渐增加 `Kp`，直到系统响应足够快但尚未持续振荡。
2. 缓慢增加 `Ki`，用于消除稳定后的静差。
3. 如果过冲明显，再少量增加 `Kd` 抑制快速变化。
4. 每次只调整一个参数，并记录实际响应。

PID 参数与被控对象、采样周期和数值单位有关，其他项目中的参数通常不能直接复制。

## 8. 使用限制

- PID 使用 `float`，MSPM0G3507 Cortex-M0+ 没有硬件浮点单元，运算由软件完成。
- 对 10 Hz～1 kHz 左右的常见控制任务通常足够；更高频率控制可考虑定点实现。
- 每个实例应由同一个 FreeRTOS 任务调用，不要在多个任务或 ISR 中并发访问。
- 微分项容易放大噪声，测量数据可先使用三点中值或低通滤波。
- PID 不能补偿错误接线、传感器悬空、执行器死区或控制方向错误。

当前模块只提供通用算法，尚未自动连接 ADC、PWM 或 DAC；闭环数据流应在
Application 层根据具体业务组合。
