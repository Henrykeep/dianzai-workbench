/*
 * TB6612 Module 在板级双 H 桥接口之上提供线程安全的速度、停止模式和待机状态管理。
 */
#include "modules/tb6612/tb6612.h"

#include <stddef.h>

#include "application/app_config.h"

#if APP_ENABLE_TB6612_CONTROL != 0U

#include "FreeRTOS.h"
#include "semphr.h"

#include "bsp/tb6612/bsp_tb6612.h"

#define TB6612_SPEED_MINIMUM (-100)
#define TB6612_SPEED_MAXIMUM (100)

struct TB6612Instance {
    /* 底层板级硬件实例。 */
    BSPTB6612Instance *bsp;
    /* 每路保存最近一次成功应用的状态，查询时直接复制该快照。 */
    TB6612MotorState motors[TB6612_MOTOR_COUNT];
    /* 两路电机共享硬件，所有普通控制接口由同一静态互斥锁串行化。 */
    SemaphoreHandle_t mutex;
    StaticSemaphore_t mutex_control;
    bool standby_released;
    bool registered;
};

/* 板上单一驱动芯片对应一个静态实例。 */
static TB6612Instance tb6612_instance;

static bool TB6612IsValid(const TB6612Instance *instance);
static bool TB6612MotorIsValid(TB6612_Motor_e motor);
static BSP_TB6612_Motor_e TB6612ToBSPMotor(TB6612_Motor_e motor);
static bool TB6612ApplyStop(TB6612Instance *instance,
    TB6612_Motor_e motor, TB6612_StopMode_e stop_mode);

TB6612Instance *TB6612Register(const TB6612Config *config)
{
    if ((config == NULL) || (config->pwm_frequency_hz == 0U)) {
        return NULL;
    }
    if (tb6612_instance.registered) {
        return &tb6612_instance;
    }

    /* 先创建锁，再把底层配置为两路滑行且功率级关闭。 */
    tb6612_instance.mutex = xSemaphoreCreateMutexStatic(
        &tb6612_instance.mutex_control);
    if (tb6612_instance.mutex == NULL) {
        return NULL;
    }

    tb6612_instance.bsp = BSPTB6612Register();
    if ((tb6612_instance.bsp == NULL) ||
        !BSPTB6612ConfigurePWM(
            tb6612_instance.bsp, config->pwm_frequency_hz) ||
        !BSPTB6612SetMotorOutput(tb6612_instance.bsp,
            BSP_TB6612_MOTOR_A, false, false, 100U) ||
        !BSPTB6612SetMotorOutput(tb6612_instance.bsp,
            BSP_TB6612_MOTOR_B, false, false, 100U) ||
        !BSPTB6612SetStandby(tb6612_instance.bsp, false)) {
        BSPTB6612EnterSafeState();
        tb6612_instance.bsp = NULL;
        return NULL;
    }

    tb6612_instance.motors[TB6612_MOTOR_A].speed_percent = 0;
    tb6612_instance.motors[TB6612_MOTOR_A].stop_mode =
        TB6612_STOP_MODE_COAST;
    tb6612_instance.motors[TB6612_MOTOR_B].speed_percent = 0;
    tb6612_instance.motors[TB6612_MOTOR_B].stop_mode =
        TB6612_STOP_MODE_COAST;
    tb6612_instance.standby_released = false;
    tb6612_instance.registered = true;
    return &tb6612_instance;
}

bool TB6612SetSpeedPercent(
    TB6612Instance *instance, TB6612_Motor_e motor,
    int8_t speed_percent)
{
    uint8_t duty_cycle;
    bool input_1_high;
    bool input_2_high;
    bool result;

    if (!TB6612IsValid(instance) || !TB6612MotorIsValid(motor) ||
        (speed_percent < TB6612_SPEED_MINIMUM) ||
        (speed_percent > TB6612_SPEED_MAXIMUM) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    /* 零速度统一按滑行停止处理，显式制动由 StopMotor 接口选择。 */
    if (speed_percent == 0) {
        result = TB6612ApplyStop(
            instance, motor, TB6612_STOP_MODE_COAST);
        (void)xSemaphoreGive(instance->mutex);
        return result;
    }

    /* 速度符号决定 H 桥方向，绝对值直接作为 0～100% 占空比。 */
    input_1_high = speed_percent > 0;
    input_2_high = speed_percent < 0;
    duty_cycle = (uint8_t)(
        (speed_percent < 0) ? -speed_percent : speed_percent);

    /* 先配置方向和 PWM，首次运行时最后释放 STBY。 */
    result = BSPTB6612SetMotorOutput(instance->bsp,
                 TB6612ToBSPMotor(motor), input_1_high,
                 input_2_high, duty_cycle) &&
             (instance->standby_released ||
                 BSPTB6612SetStandby(instance->bsp, true));
    if (result) {
        instance->standby_released = true;
        instance->motors[motor].speed_percent = speed_percent;
        instance->motors[motor].standby_released = true;
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

bool TB6612StopMotor(TB6612Instance *instance,
    TB6612_Motor_e motor, TB6612_StopMode_e stop_mode)
{
    bool result;

    if (!TB6612IsValid(instance) || !TB6612MotorIsValid(motor) ||
        (stop_mode > TB6612_STOP_MODE_BRAKE) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    result = TB6612ApplyStop(instance, motor, stop_mode);
    (void)xSemaphoreGive(instance->mutex);
    return result;
}

bool TB6612SetStandby(
    TB6612Instance *instance, bool standby_released)
{
    bool result;
    uint32_t index;

    if (!TB6612IsValid(instance) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    /* 进入待机后硬件输出被切断，因此两路运行速度快照同时归零。 */
    result = BSPTB6612SetStandby(instance->bsp, standby_released);
    if (result) {
        instance->standby_released = standby_released;
        for (index = 0U; index < TB6612_MOTOR_COUNT; ++index) {
            instance->motors[index].standby_released =
                standby_released;
            if (!standby_released) {
                instance->motors[index].speed_percent = 0;
            }
        }
    }

    (void)xSemaphoreGive(instance->mutex);
    return result;
}

bool TB6612GetMotorState(TB6612Instance *instance,
    TB6612_Motor_e motor, TB6612MotorState *state)
{
    if (!TB6612IsValid(instance) || !TB6612MotorIsValid(motor) ||
        (state == NULL) ||
        (xSemaphoreTake(instance->mutex, portMAX_DELAY) != pdPASS)) {
        return false;
    }

    *state = instance->motors[motor];
    (void)xSemaphoreGive(instance->mutex);
    return true;
}

void TB6612EnterSafeState(void)
{
    uint32_t index;

    /* Fault 路径不获取互斥锁，直接关断板级功率级并同步静态状态。 */
    BSPTB6612EnterSafeState();
    tb6612_instance.standby_released = false;
    for (index = 0U; index < TB6612_MOTOR_COUNT; ++index) {
        tb6612_instance.motors[index].speed_percent = 0;
        tb6612_instance.motors[index].standby_released = false;
    }
}

static bool TB6612IsValid(const TB6612Instance *instance)
{
    return (instance == &tb6612_instance) && instance->registered &&
           (instance->bsp != NULL) && (instance->mutex != NULL);
}

static bool TB6612MotorIsValid(TB6612_Motor_e motor)
{
    return (motor >= TB6612_MOTOR_A) &&
           (motor < TB6612_MOTOR_COUNT);
}

static BSP_TB6612_Motor_e TB6612ToBSPMotor(TB6612_Motor_e motor)
{
    return (motor == TB6612_MOTOR_A)
               ? BSP_TB6612_MOTOR_A
               : BSP_TB6612_MOTOR_B;
}

static bool TB6612ApplyStop(TB6612Instance *instance,
    TB6612_Motor_e motor, TB6612_StopMode_e stop_mode)
{
    /* 滑行使用 IN1=IN2=0，制动使用 IN1=IN2=1。 */
    bool brake = stop_mode == TB6612_STOP_MODE_BRAKE;
    bool result = BSPTB6612SetMotorOutput(instance->bsp,
        TB6612ToBSPMotor(motor), brake, brake, 100U);

    if (result) {
        instance->motors[motor].speed_percent = 0;
        instance->motors[motor].stop_mode = stop_mode;
        instance->motors[motor].standby_released =
            instance->standby_released;
    }
    return result;
}

#endif
