/*
 * TB6612 Application 保存两路目标速度，并在一个周期任务中完成斜坡调速。
 * 换向命令强制先经过 0，避免 H 桥和机械系统在同一周期直接反向。
 */
#include "application/control/motor_control/motor_control.h"

#include <stddef.h>

#include "application/app_config.h"

#if APP_ENABLE_TB6612_CONTROL != 0U

#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

#include "application/task/task_manager.h"
#include "modules/tb6612/tb6612.h"

/* 逻辑速度统一使用有符号百分比，正负号表示方向。 */
#define TB6612_CONTROL_MINIMUM_SPEED (-100)
#define TB6612_CONTROL_MAXIMUM_SPEED (100)

/* 单路电机的已应用速度、调用方目标和最近故障状态。 */
typedef struct {
    int8_t current_speed_percent;
    int8_t target_speed_percent;
    TB6612Control_StopMode_e stop_mode;
    bool faulted;
} TB6612ControlMotorState;

/*
 * 公开接口与周期任务共享下列状态，访问电机数组和命令代次时必须持有互斥量。
 * 驱动调用放在锁外，避免底层 PWM 操作延长其他命令的等待时间。
 */
static TB6612Instance *tb6612_control_driver;
static TB6612ControlMotorState
    tb6612_control_motors[TB6612_CONTROL_MOTOR_COUNT];
static SemaphoreHandle_t tb6612_control_mutex;
static StaticSemaphore_t tb6612_control_mutex_control;
static bool tb6612_control_task_created;
static bool tb6612_control_ready;
static uint32_t tb6612_control_command_generation;

static void TB6612ControlTask(void *argument);
static bool TB6612ControlProcessMotor(TB6612Control_Motor_e motor);
static bool TB6612ControlUpdateStandby(void);
static void TB6612ControlHandleFailure(void);
static bool TB6612ControlLock(void);
static void TB6612ControlUnlock(void);
static bool TB6612ControlMotorIsValid(TB6612Control_Motor_e motor);
static int8_t TB6612ControlGetNextSpeed(
    int8_t current_speed_percent, int8_t target_speed_percent);
static int8_t TB6612ControlGetPhysicalSpeed(
    TB6612Control_Motor_e motor, int8_t logical_speed_percent);
static TB6612_Motor_e TB6612ControlToModuleMotor(
    TB6612Control_Motor_e motor);
static TB6612_StopMode_e TB6612ControlToModuleStopMode(
    TB6612Control_StopMode_e stop_mode);
static TB6612Control_StopMode_e TB6612ControlDefaultStopMode(void);

#endif

bool TB6612ControlInit(void)
{
#if APP_ENABLE_TB6612_CONTROL != 0U
    TB6612Config config = { APP_TB6612_PWM_FREQUENCY_HZ };
    uint32_t index;

    if (tb6612_control_ready) {
        return true;
    }

    if (tb6612_control_mutex == NULL) {
        tb6612_control_mutex = xSemaphoreCreateMutexStatic(
            &tb6612_control_mutex_control);
        if (tb6612_control_mutex == NULL) {
            return false;
        }
    }

    tb6612_control_driver = TB6612Register(&config);
    if (tb6612_control_driver == NULL) {
        return false;
    }

    for (index = 0U; index < TB6612_CONTROL_MOTOR_COUNT; ++index) {
        tb6612_control_motors[index].current_speed_percent = 0;
        tb6612_control_motors[index].target_speed_percent = 0;
        /* 无论默认停止策略如何，上电都先滑行停止并保持 STBY 低。 */
        tb6612_control_motors[index].stop_mode =
            TB6612_CONTROL_STOP_COAST;
        tb6612_control_motors[index].faulted = false;
    }

    if (!tb6612_control_task_created &&
        (ApplicationTaskCreate(APPLICATION_TASK_MOTOR_CONTROL,
             TB6612ControlTask, NULL) == NULL)) {
        TB6612EnterSafeState();
        return false;
    }

    tb6612_control_task_created = true;
    tb6612_control_ready = true;
    return true;
#else
    return false;
#endif
}

bool TB6612ControlSetMotorSpeedPercent(
    TB6612Control_Motor_e motor, int8_t speed_percent)
{
#if APP_ENABLE_TB6612_CONTROL != 0U
    TB6612ControlMotorState *state;

    if (!tb6612_control_ready || !TB6612ControlMotorIsValid(motor) ||
        (speed_percent < TB6612_CONTROL_MINIMUM_SPEED) ||
        (speed_percent > TB6612_CONTROL_MAXIMUM_SPEED) ||
        !TB6612ControlLock()) {
        return false;
    }

    state = &tb6612_control_motors[motor];
    if (state->faulted) {
        TB6612ControlUnlock();
        return false;
    }
    state->target_speed_percent = speed_percent;
    if (speed_percent == 0) {
        state->stop_mode = TB6612ControlDefaultStopMode();
    }
    ++tb6612_control_command_generation;
    TB6612ControlUnlock();
    return true;
#else
    (void)motor;
    (void)speed_percent;
    return false;
#endif
}

bool TB6612ControlStopMotor(TB6612Control_Motor_e motor,
    TB6612Control_StopMode_e stop_mode)
{
#if APP_ENABLE_TB6612_CONTROL != 0U
    TB6612ControlMotorState *state;

    if (!tb6612_control_ready || !TB6612ControlMotorIsValid(motor) ||
        (stop_mode > TB6612_CONTROL_STOP_BRAKE) ||
        !TB6612ControlLock()) {
        return false;
    }

    state = &tb6612_control_motors[motor];
    if (state->faulted) {
        TB6612ControlUnlock();
        return false;
    }
    state->target_speed_percent = 0;
    state->stop_mode = stop_mode;
    ++tb6612_control_command_generation;
    TB6612ControlUnlock();
    return true;
#else
    (void)motor;
    (void)stop_mode;
    return false;
#endif
}

bool TB6612ControlEmergencyStopAll(void)
{
#if APP_ENABLE_TB6612_CONTROL != 0U
    uint32_t index;

    if (!tb6612_control_ready || !TB6612ControlLock()) {
        return false;
    }
    for (index = 0U; index < TB6612_CONTROL_MOTOR_COUNT; ++index) {
        tb6612_control_motors[index].current_speed_percent = 0;
        tb6612_control_motors[index].target_speed_percent = 0;
        tb6612_control_motors[index].stop_mode =
            TB6612_CONTROL_STOP_COAST;
    }
    ++tb6612_control_command_generation;
    TB6612ControlUnlock();

    return TB6612SetStandby(tb6612_control_driver, false);
#else
    return false;
#endif
}

bool TB6612ControlGetMotorStatus(
    TB6612Control_Motor_e motor, TB6612ControlStatus *status)
{
#if APP_ENABLE_TB6612_CONTROL != 0U
    const TB6612ControlMotorState *state;

    if (!tb6612_control_ready || !TB6612ControlMotorIsValid(motor) ||
        (status == NULL) || !TB6612ControlLock()) {
        return false;
    }

    state = &tb6612_control_motors[motor];
    status->current_speed_percent = state->current_speed_percent;
    status->target_speed_percent = state->target_speed_percent;
    status->stop_mode = state->stop_mode;
    status->running = state->current_speed_percent != 0;
    status->faulted = state->faulted;
    TB6612ControlUnlock();
    return true;
#else
    (void)motor;
    (void)status;
    return false;
#endif
}

bool TB6612ControlIsReady(void)
{
#if APP_ENABLE_TB6612_CONTROL != 0U
    return tb6612_control_ready && tb6612_control_task_created &&
           (tb6612_control_driver != NULL) &&
           (tb6612_control_mutex != NULL);
#else
    return false;
#endif
}

uint32_t TB6612ControlGetMinimumFreeStackWords(void)
{
#if APP_ENABLE_TB6612_CONTROL != 0U
    return ApplicationTaskGetMinimumFreeStackWords(
        APPLICATION_TASK_MOTOR_CONTROL);
#else
    return 0U;
#endif
}

void TB6612ControlEnterSafeState(void)
{
#if APP_ENABLE_TB6612_CONTROL != 0U
    TB6612EnterSafeState();
#endif
}

#if APP_ENABLE_TB6612_CONTROL != 0U

/* 固定周期推进两路速度斜坡，最后根据两路合并状态更新 STBY。 */
static void TB6612ControlTask(void *argument)
{
    TickType_t next_wake_time = xTaskGetTickCount();
    uint32_t index;

    (void)argument;

    for (;;) {
        bool success = true;

        for (index = 0U; index < TB6612_CONTROL_MOTOR_COUNT; ++index) {
            if (!TB6612ControlProcessMotor(
                    (TB6612Control_Motor_e)index)) {
                success = false;
                break;
            }
        }
        if (success) {
            success = TB6612ControlUpdateStandby();
        }
        if (!success) {
            TB6612ControlHandleFailure();
        }

        vTaskDelayUntil(&next_wake_time,
            pdMS_TO_TICKS(APP_TB6612_CONTROL_PERIOD_MS));
    }
}

/*
 * 先快照目标并在锁外操作硬件，再用命令代次确认结果仍属当前请求；
 * 若期间收到新命令则关闭功率级，下一周期按最新目标重新计算。
 */
static bool TB6612ControlProcessMotor(TB6612Control_Motor_e motor)
{
    TB6612ControlMotorState *state = &tb6612_control_motors[motor];
    TB6612Control_StopMode_e stop_mode;
    int8_t current_speed_percent;
    int8_t target_speed_percent;
    int8_t next_speed_percent;
    uint32_t command_generation;
    bool faulted;
    bool result;

    if (!TB6612ControlLock()) {
        return false;
    }
    current_speed_percent = state->current_speed_percent;
    target_speed_percent = state->target_speed_percent;
    stop_mode = state->stop_mode;
    faulted = state->faulted;
    command_generation = tb6612_control_command_generation;
    TB6612ControlUnlock();

    if (faulted) {
        return true;
    }

    next_speed_percent = TB6612ControlGetNextSpeed(
        current_speed_percent, target_speed_percent);
    if (next_speed_percent == 0) {
        result = TB6612StopMotor(tb6612_control_driver,
            TB6612ControlToModuleMotor(motor),
            TB6612ControlToModuleStopMode(stop_mode));
    } else {
        result = TB6612SetSpeedPercent(tb6612_control_driver,
            TB6612ControlToModuleMotor(motor),
            TB6612ControlGetPhysicalSpeed(
                motor, next_speed_percent));
    }
    if (!result || !TB6612ControlLock()) {
        return false;
    }
    if (command_generation != tb6612_control_command_generation) {
        /* 丢弃并关闭刚执行的过期命令，下一周期按新目标重新计算。 */
        TB6612ControlUnlock();
        return TB6612SetStandby(tb6612_control_driver, false);
    }
    state->current_speed_percent = next_speed_percent;
    TB6612ControlUnlock();
    return true;
}

/* 两路均滑行停止时进入待机；任一路运行或制动时保持 STBY 高电平。 */
static bool TB6612ControlUpdateStandby(void)
{
    bool release_standby = false;
    bool result;
    uint32_t command_generation;
    uint32_t index;

    if (!TB6612ControlLock()) {
        return false;
    }
    for (index = 0U; index < TB6612_CONTROL_MOTOR_COUNT; ++index) {
        const TB6612ControlMotorState *state =
            &tb6612_control_motors[index];

        if (!state->faulted &&
            ((state->current_speed_percent != 0) ||
                (state->stop_mode == TB6612_CONTROL_STOP_BRAKE))) {
            release_standby = true;
            break;
        }
    }
    command_generation = tb6612_control_command_generation;
    TB6612ControlUnlock();

    result = TB6612SetStandby(
        tb6612_control_driver, release_standby);
    if (!result || !TB6612ControlLock()) {
        return false;
    }
    if (command_generation != tb6612_control_command_generation) {
        TB6612ControlUnlock();
        return TB6612SetStandby(tb6612_control_driver, false);
    }
    TB6612ControlUnlock();
    return true;
}

/* 任一路底层操作失败即关闭整个 H 桥，并把两路锁定为故障状态。 */
static void TB6612ControlHandleFailure(void)
{
    uint32_t index;

    TB6612EnterSafeState();
    if (!TB6612ControlLock()) {
        return;
    }
    for (index = 0U; index < TB6612_CONTROL_MOTOR_COUNT; ++index) {
        tb6612_control_motors[index].current_speed_percent = 0;
        tb6612_control_motors[index].target_speed_percent = 0;
        tb6612_control_motors[index].faulted = true;
    }
    TB6612ControlUnlock();
}

static bool TB6612ControlLock(void)
{
    return (tb6612_control_mutex != NULL) &&
           (xSemaphoreTake(tb6612_control_mutex,
                portMAX_DELAY) == pdPASS);
}

static void TB6612ControlUnlock(void)
{
    (void)xSemaphoreGive(tb6612_control_mutex);
}

static bool TB6612ControlMotorIsValid(TB6612Control_Motor_e motor)
{
    return (motor >= TB6612_CONTROL_MOTOR_A) &&
           (motor < TB6612_CONTROL_MOTOR_COUNT);
}

static int8_t TB6612ControlGetNextSpeed(
    int8_t current_speed_percent, int8_t target_speed_percent)
{
    int16_t next_speed_percent = current_speed_percent;
    int16_t ramp_target_speed_percent = target_speed_percent;
    int16_t step = APP_TB6612_SPEED_STEP_PERCENT;

    /* 换向时先按斜坡降到 0；到 0 后下一周期才向相反方向升速。 */
    if (((current_speed_percent > 0) &&
            (target_speed_percent < 0)) ||
        ((current_speed_percent < 0) &&
            (target_speed_percent > 0))) {
        ramp_target_speed_percent = 0;
    }

    if (current_speed_percent < ramp_target_speed_percent) {
        next_speed_percent += step;
        if (next_speed_percent > ramp_target_speed_percent) {
            next_speed_percent = ramp_target_speed_percent;
        }
    } else if (current_speed_percent > ramp_target_speed_percent) {
        next_speed_percent -= step;
        if (next_speed_percent < ramp_target_speed_percent) {
            next_speed_percent = ramp_target_speed_percent;
        }
    }
    return (int8_t)next_speed_percent;
}

/* 将逻辑方向按每路安装方向配置转换为 TB6612 实际方向。 */
static int8_t TB6612ControlGetPhysicalSpeed(
    TB6612Control_Motor_e motor, int8_t logical_speed_percent)
{
    bool reversed = (motor == TB6612_CONTROL_MOTOR_A)
                        ? (APP_TB6612_MOTOR_A_REVERSED != 0U)
                        : (APP_TB6612_MOTOR_B_REVERSED != 0U);

    return reversed ? (int8_t)(-logical_speed_percent)
                    : logical_speed_percent;
}

static TB6612_Motor_e TB6612ControlToModuleMotor(
    TB6612Control_Motor_e motor)
{
    return (motor == TB6612_CONTROL_MOTOR_A)
               ? TB6612_MOTOR_A
               : TB6612_MOTOR_B;
}

static TB6612_StopMode_e TB6612ControlToModuleStopMode(
    TB6612Control_StopMode_e stop_mode)
{
    return (stop_mode == TB6612_CONTROL_STOP_BRAKE)
               ? TB6612_STOP_MODE_BRAKE
               : TB6612_STOP_MODE_COAST;
}

static TB6612Control_StopMode_e TB6612ControlDefaultStopMode(void)
{
    return (APP_TB6612_DEFAULT_BRAKE_ON_STOP != 0U)
               ? TB6612_CONTROL_STOP_BRAKE
               : TB6612_CONTROL_STOP_COAST;
}

#endif
