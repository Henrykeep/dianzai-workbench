# PWM Module 使用指南

`modules/pwm/` 将 TIMG7 的 PA23/CCP0、PA24/CCP1 封装为两个线程安全的频率、
占空比、微秒脉宽和启停接口。

## 1. 当前硬件参数

| 逻辑设备 | 输出引脚 | 定时器通道 |
|---|---|---|
| `PWM_DEVICE_OUTPUT_0` | PA23 | TIMG7 CCP0 |
| `PWM_DEVICE_OUTPUT_1` | PA24 | TIMG7 CCP1 |

两路计数时钟均为 1 MHz，周期计数范围为 2～65535。由于共用同一个 TIMG7 负载
寄存器，两路运行时必须使用相同频率；占空比、脉宽和启停状态可以独立设置。
因此理论频率范围约为 `16 Hz～500 kHz`。高频时周期计数较少，占空比分辨率会降低。

## 2. 注册PWM

```c
#include "modules/pwm/pwm.h"

static PWMInstance *pwm_1;
static PWMInstance *pwm_2;

bool ExamplePWMInit(void)
{
    static const PWMConfig config = {
        .frequency_hz = 1000U,
        .duty_cycle_percent = 50U,
        .start_enabled = true
    };

    pwm_1 = PWMRegister(PWM_DEVICE_OUTPUT_0, &config);
    pwm_2 = PWMRegister(PWM_DEVICE_OUTPUT_1, &config);
    return (pwm_1 != NULL) && (pwm_2 != NULL);
}
```

同一逻辑设备重复注册返回已有实例，不会再次应用新的注册配置。

## 3. 动态控制

```c
(void)PWMSetPulseWidthMicroseconds(pwm_1, 1000U);
(void)PWMSetPulseWidthMicroseconds(pwm_2, 2000U);
(void)PWMStop(pwm_2);  /* pwm_1 继续运行。 */
```

若要修改共享频率，应先停止两路，再把两个实例设置为同一频率后重新启动：

```c
(void)PWMStop(pwm_1);
(void)PWMStop(pwm_2);
(void)PWMSetFrequency(pwm_1, 50U);
(void)PWMSetFrequency(pwm_2, 50U);
(void)PWMStart(pwm_1);
(void)PWMStart(pwm_2);
```

- 占空比范围为 `0～100`。
- 设置频率时保持当前占空比。
- 设置占空比时保持当前频率。
- 微秒脉宽按当前频率直接换算为高电平计数，不能超过一个 PWM 周期。
- 频率无法映射到合法定时器计数时返回 `false`。
- 实际频率会根据整数周期计数进行四舍五入。

## 4. 运行中更新

定时器运行时使用影子寄存器，在周期边界加载新周期和比较值，减少周期中途更新产生
的毛刺。停止状态下则直接写入活动配置，确保下次启动立即使用新参数。

`PWMStop()` 只关闭当前设备的 CCP 输出；另一通道仍运行时 TIMG7 会继续计数，
最后一路停止后才关闭定时器。外部电路如果要求停止时保持确定高低电平，应增加
合适的上下拉或单独设计停止状态。

## 5. 线程和负载注意事项

- 每个实例和共享 TIMG7 硬件都使用静态 FreeRTOS 互斥锁，可从不同任务调用。
- 接口可能等待互斥锁，不能在ISR中调用。
- PA23/PA24 输出为 3.3 V 逻辑信号，不能直接驱动电机、继电器或大功率 LED。
- 功率负载应通过MOSFET、三极管或专用驱动芯片连接，并与开发板共地。
- 频率越高，占空比可选档位越少，示波器上可能看到取整误差。
