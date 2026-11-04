/**
 * @file pid.h
 * @brief 带输出/积分限幅和条件积分抗饱和的位置式 PID 接口。
 */
#ifndef PID_H
#define PID_H

#include <stdbool.h>

/** PID 微分项使用的输入来源。 */
typedef enum {
    /* 对误差变化率求微分，设定值突变时响应更直接。 */
    PID_DERIVATIVE_ON_ERROR = 0,
    /* 对测量值变化率取反，可减小设定值突变造成的微分冲击。 */
    PID_DERIVATIVE_ON_MEASUREMENT
} PIDDerivativeMode_e;

/** PID 增益、限幅和微分模式配置。 */
typedef struct {
    /** 比例增益。 */
    float kp;
    /** 积分增益，单位与调用方传入的秒时间基准对应。 */
    float ki;
    /** 微分增益，单位与调用方传入的秒时间基准对应。 */
    float kd;
    /** 控制输出下限。 */
    float output_minimum;
    /** 控制输出上限。 */
    float output_maximum;
    /** 积分项下限，用于限制积分累积。 */
    float integral_minimum;
    /** 积分项上限，用于限制积分累积。 */
    float integral_maximum;
    /** 选择对误差或测量值求微分。 */
    PIDDerivativeMode_e derivative_mode;
} PIDConfig;

/** PID 控制器的不透明实例。 */
typedef struct PIDInstance PIDInstance;

/** 注册一个 PID 控制器；静态实例耗尽或配置无效时返回 NULL。 */
PIDInstance *PIDRegister(const PIDConfig *config);

/** 应用新配置并清空控制器历史状态。 */
bool PIDConfigure(PIDInstance *instance, const PIDConfig *config);

/** 清除积分、微分历史和最近输出，保留当前配置。 */
bool PIDReset(PIDInstance *instance);

/**
 * @brief 根据设定值、测量值和本次周期计算控制输出。
 *
 * @param delta_time_seconds 距上次计算经过的秒数，必须大于 0。
 * 第一次计算的微分项为 0。每个实例应固定由同一个任务调用。
 */
bool PIDProcess(PIDInstance *instance, float setpoint, float measurement,
    float delta_time_seconds, float *output);

/** 返回最近一次成功计算的输出；尚未计算时返回 false。 */
bool PIDGetLastOutput(const PIDInstance *instance, float *output);

#endif
