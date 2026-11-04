# Servo Module 使用指南

`modules/servo/` 在 PWM Module 之上提供双路位置舵机控制。第一路使用
PA23 / TIMG7 CCP0，第二路使用 PA24 / TIMG7 CCP1；两路输出固定 50 Hz 控制脉冲，
角度分别线性映射到可配置的最小、最大高电平脉宽。

## 1. 接线

| 设备 | 信号线 | 电源 |
|---|---|---|
| 舵机 1 | PA23 | 独立舵机电源 |
| 舵机 2 | PA24 | 独立舵机电源 |
| 两只舵机 | — | 电源 GND 与开发板 GND 共地 |

不要使用开发板 3.3 V GPIO 给舵机供电。舵机启动和堵转电流较大，建议在舵机电源
附近增加合适的储能与去耦电容。PA23/PA24 只输出 3.3 V 控制逻辑，不承担电机电流。

## 2. 注册和控制

以下参数适合很多 180° 小型舵机，但最终脉宽范围应以具体型号的数据手册和实测
机械限位为准：

```c
#include "modules/servo/servo.h"

static ServoInstance *servo_1;
static ServoInstance *servo_2;

bool ExampleServoInit(void)
{
    static const ServoConfig config = {
        .minimum_pulse_width_microseconds = 500U,
        .maximum_pulse_width_microseconds = 2500U,
        .maximum_angle_degrees = 180U,
        .initial_angle_degrees = 90U,
        .start_enabled = false
    };

    servo_1 = ServoRegister(SERVO_DEVICE_OUTPUT_0, &config);
    servo_2 = ServoRegister(SERVO_DEVICE_OUTPUT_1, &config);
    return (servo_1 != NULL) && (servo_2 != NULL);
}

void ExampleServoRun(void)
{
    (void)ServoStart(servo_1);
    (void)ServoStart(servo_2);
    (void)ServoSetAngleDegrees(servo_1, 30U);
    (void)ServoSetAngleDegrees(servo_2, 150U);
    (void)ServoStop(servo_2); /* 第一路继续输出。 */
}
```

初始化时会先停止对应 CCP 输出、设置 50 Hz 和初始脉宽，再根据 `start_enabled` 决定
是否启动。建议默认保持关闭，确认接线和机械范围后再调用 `ServoStart()`。

## 3. 直接按脉宽控制

需要标定机械端点时，可以绕过角度换算直接设置脉宽：

```c
(void)ServoSetPulseWidthMicroseconds(servo_1, 1500U);
```

脉宽必须位于注册配置的最小值和最大值之间。设置成功后，模块会同步保存最接近的
逻辑角度。可以用以下接口读取最近一次成功设置的目标值：

```c
uint16_t angle_degrees;
uint16_t pulse_width_microseconds;

(void)ServoGetAngleDegrees(servo_1, &angle_degrees);
(void)ServoGetPulseWidthMicroseconds(
    servo_1, &pulse_width_microseconds);
```

这些值是输出命令，不是舵机位置反馈。普通三线舵机没有向单片机返回实际角度；若
需要闭环位置检测，应增加带反馈的舵机或外部角度传感器。

## 4. 资源和线程约束

- 两路 Servo 共用 TIMG7 周期，必须保持相同频率；各自的比较值和启停状态独立。
- 第一路 Servo 与 `PWMOutput` 共用 PA23 / TIMG7 CCP0，二者不能同时使用。
- `app_config.h` 会禁止 `APP_ENABLE_SERVO_CONTROL` 与
  `APP_ENABLE_DISPLAY_MENU_PWM_OUTPUT` 同时开启，避免两个 Application 争用该资源。
- 公共控制接口使用静态 FreeRTOS 互斥锁，可从任务或调度器启动前调用，不能从 ISR
  中调用。
- `ServoStop()` 会停止控制脉冲，舵机通常会失去保持力，但具体行为取决于舵机型号。
- 端点脉宽设置过宽可能撞击机械限位。首次调试应从 1500 us 中位开始，小步扩展范围。

## 5. 双路设备映射

| Servo 设备 | PWM 设备 | BSP 通道 | 引脚 |
|---|---|---|---|
| `SERVO_DEVICE_OUTPUT_0` | `PWM_DEVICE_OUTPUT_0` | `BSP_PWM_CHANNEL_OUTPUT_0` | PA23 |
| `SERVO_DEVICE_OUTPUT_1` | `PWM_DEVICE_OUTPUT_1` | `BSP_PWM_CHANNEL_OUTPUT_1` | PA24 |
