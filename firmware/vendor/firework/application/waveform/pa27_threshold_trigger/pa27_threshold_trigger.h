/**
 * @file pa27_threshold_trigger.h
 * @brief PA27 阈值触发采集并保存任意波形的状态机接口。
 *
 * Arm 后由 ADC 事件回调推进状态，后台任务负责等待采集完成和写入 Flash。
 */
#ifndef PA27_THRESHOLD_TRIGGER_H
#define PA27_THRESHOLD_TRIGGER_H

#include <stdbool.h>
#include <stdint.h>

/** PA27 触发采集的运行模式。 */
typedef enum {
    PA27_THRESHOLD_TRIGGER_MODE_OFF = 0,
    PA27_THRESHOLD_TRIGGER_MODE_SINGLE,
    PA27_THRESHOLD_TRIGGER_MODE_CONTINUOUS
} PA27ThresholdTriggerMode_e;

/** PA27 触发采集的当前生命周期状态。 */
typedef enum {
    PA27_THRESHOLD_TRIGGER_IDLE = 0,
    PA27_THRESHOLD_TRIGGER_WAITING,
    PA27_THRESHOLD_TRIGGER_CAPTURING,
    PA27_THRESHOLD_TRIGGER_WAITING_LOW,
    PA27_THRESHOLD_TRIGGER_SAVED,
    PA27_THRESHOLD_TRIGGER_TIMEOUT,
    PA27_THRESHOLD_TRIGGER_ERROR
} PA27ThresholdTriggerStatus_e;

/** 创建 PA27 阈值触发任务；默认不自动开始，需调用 Arm。 */
bool PA27ThresholdTriggerInit(void);

/** 设置运行模式；OFF 会立即取消当前采集，其他模式等待 Arm 启动。 */
bool PA27ThresholdTriggerSetMode(PA27ThresholdTriggerMode_e mode);

/** 返回当前选择的运行模式。 */
PA27ThresholdTriggerMode_e PA27ThresholdTriggerGetMode(void);

/** 返回是否已经布置了正在等待或执行的触发采集。 */
bool PA27ThresholdTriggerIsActive(void);

/**
 * 按当前模式启动触发采集，从 slot_id 开始保存；SINGLE 完成一次后停止，
 * CONTINUOUS 在信号回落后自动切换到下一个槽位并循环。
 */
bool PA27ThresholdTriggerArm(uint8_t slot_id);

/** 取消当前等待或采集。 */
bool PA27ThresholdTriggerCancel(void);

/** 返回当前触发任务状态。 */
PA27ThresholdTriggerStatus_e PA27ThresholdTriggerGetStatus(void);

/** 返回最近一次成功保存的槽位。 */
uint8_t PA27ThresholdTriggerGetLastSavedSlot(void);

#endif
