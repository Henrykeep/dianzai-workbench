# PWM Output Module 使用指南

本工程按 `BSP → Module → Application` 三层结构提供一个通用 PWM 输出。目前的
硬件映射如下：

| 项目 | 配置 |
| --- | --- |
| 输出引脚 | PA23 |
| 定时器通道 | TIMG7 CCP0 |
| PWM 模式 | 边沿对齐、向下计数 |
| 定时器计数时钟 | 1 MHz |
| 默认频率 | 1 kHz |
| 默认占空比 | 50% |

`PWMOutputInit()` 位于 Module 层。当 `APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT=1U` 时，
`DisplayMenuInit()` 会初始化该 Module 并保存默认 1 kHz、50% 参数，但 PA23
保持关闭。当前显示屏的 `PWM OUTPUT` 页面可以运行时启停输出，并选择常用参数。

当前默认 `APP_ENABLE_SERVO_CONTROL=0U`，因此
`APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT=1U`，通用 PWM 页面可用。若以后打开 Servo
Control，配置会自动关闭该菜单页，因为舵机与通用 PWM 共用 PA23/TIMG7。

## Module 便捷接口

应用代码只需要包含：

```c
#include "modules/pwm/pwm_output.h"
```

常用操作示例：

```c
/* 修改为 20 kHz。 */
PWMOutputSetFrequency(20000U);

/* 修改为 25% 占空比。 */
PWMOutputSetDutyCycle(25U);

/* 暂停和恢复输出。 */
PWMOutputStop();
PWMOutputStart();
```

接口返回 `true` 表示操作成功，返回 `false` 表示 PWM 尚未初始化、参数超出范围，
或底层操作失败。占空比范围为 `0～100`。

## 显示菜单控制

进入 `MAIN MENU → PWM OUTPUT`：

```text
OUTPUT ON      启动 PA23 PWM
OUTPUT OFF     停止 PA23 PWM
FREQUENCY      50/100/500 Hz，1/5/10/20 kHz
DUTY CYCLE     0/10/25/50/75/90/100%
```

选择频率不会改变当前占空比，选择占空比也不会改变当前频率。停止输出后设置的参数
会保留，下一次选择 `OUTPUT ON` 时按最新参数启动。

## 频率范围和精度

当前定时器计数时钟为 1 MHz，周期计数范围为 2～65535，因此软件允许的频率约为
16 Hz～500 kHz。实际频率由整数计数得到：

```text
实际频率 = 1,000,000 / 周期计数
```

当目标频率无法整除计数时，模块会选择最接近的整数周期。频率越高，可用的周期
计数越少，占空比分辨率也越低。例如 1 kHz 对应约 1000 个周期计数，20 kHz 只
对应约 50 个周期计数。

运行中修改频率或占空比时，BSP 使用定时器影子寄存器，在周期边界同步装载新值，
可以避免在当前周期中途直接改值造成明显毛刺。

## 直接使用通用 Module

若需要在其他应用中直接管理 PWM 实例，可使用 Module 层接口：

```c
#include "modules/pwm/pwm.h"

static PWMInstance *example_pwm;

static bool ExamplePWMInit(void)
{
    static const PWMConfig config = {
        .frequency_hz = 1000U,
        .duty_cycle_percent = 50U,
        .start_enabled = true,
    };

    example_pwm = PWMRegister(PWM_DEVICE_OUTPUT_0, &config);
    return example_pwm != NULL;
}
```

同一个逻辑设备重复注册时会返回已有实例。工程使用静态实例和静态 FreeRTOS
互斥锁，不会在注册过程中使用堆内存。

## 修改默认值或引脚

- 默认频率和占空比位于 `modules/pwm/pwm_output.c`。
- PWM 定时器、引脚、分频和影子更新配置位于 `blink_led.syscfg`。
- 修改 SysConfig 后，应重新生成 `ti_msp_dl_config.c/.h`，并执行一次 Clean Build。
- 如果增加第二路 PWM，应同时扩展 BSP 通道枚举、Module 设备枚举和静态实例映射。

## 测试和接线注意事项

用示波器或逻辑分析仪测量 PA23 与 GND，即可检查频率和占空比。PWM 是 3.3 V
逻辑信号，GPIO 驱动能力有限，不能直接驱动电机、继电器或大功率 LED；这类负载
应通过 MOSFET、三极管或专用驱动芯片连接，并与开发板共地。

调用 `PWMOutputStop()` 后，定时器停止且 PA23 的 CCP 输出方向被关闭；如外部电路
要求停止时保持确定电平，应额外使用合适的上下拉或在 BSP 中设计明确的 GPIO
停止状态。

PWM Output Module 不依赖 Application 串口服务，因此不在 Module 内发送
UART0 日志。菜单操作的成功或失败由当前启用的 OLED/TFT 显示后端反馈。
