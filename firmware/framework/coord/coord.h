/**
 * @file coord.h
 * @brief 通用顶层协调状态机：管测试项选择、参数档、启停、急停、超时。与具体题目无关。
 *
 *   IDLE --select/start--> RUNNING --stop/超时/完成--> DONE --reset--> IDLE
 *     任意状态 --estop--> ESTOP --reset(且急停已释放)--> IDLE
 *     任意状态 --fault--> FAULT --reset--> IDLE
 *
 * 测试项与参数档来自 project.yaml（生成为表），题目特有的逻辑（例如跨子系统前馈、
 * 某测试项的目标轨迹）通过 hooks 注入，状态机本身不改。
 */
#ifndef COORD_H
#define COORD_H

#include <stdint.h>
#include <stdbool.h>
#include "dz_err.h"
#include "subsys.h"

#define COORD_VERSION "1.0.0"

typedef enum { COORD_IDLE = 0, COORD_RUNNING, COORD_DONE, COORD_ESTOP, COORD_FAULT } coord_state_t;
typedef enum { COORD_EV_START, COORD_EV_STOP, COORD_EV_ESTOP, COORD_EV_RESET, COORD_EV_FAULT, COORD_EV_FINISHED } coord_event_t;

typedef struct {
    uint8_t     id;            /**< 题目里的小题号，例如 1、2、3 */
    const char *name;
    uint8_t     profile;       /**< 默认参数档下标 */
    uint32_t    time_limit_ms; /**< 0 = 不限时 */
} coord_test_t;

typedef struct {
    const char *name;
    const void *params;        /**< 指向题目生成的 params_t */
} coord_profile_t;

typedef struct {
    /** 每次 coord_poll 调用，在子系统 step 之前：写协调器自己的指令段、做跨子系统前馈 */
    void (*pre_step)(void *state, const coord_test_t *test, const void *params, uint32_t t_in_test_ms);
    /** 返回 true 表示本测试项完成（例如球已停稳 3 秒） */
    bool (*is_finished)(const void *state, const coord_test_t *test, uint32_t t_in_test_ms);
    /** 状态变化通知（遥测/蜂鸣器/LED） */
    void (*on_state)(coord_state_t from, coord_state_t to, coord_event_t why);
} coord_hooks_t;

typedef struct {
    const coord_test_t    *tests;    uint8_t n_tests;
    const coord_profile_t *profiles; uint8_t n_profiles;
    coord_hooks_t hooks;
    subsys_sched_t *sched;
    coord_state_t st;
    uint8_t  test_idx, profile_idx;
    uint32_t t_start_ms, now_ms;
    bool     estop_latched;
} coord_t;

dz_err_t coord_init(coord_t *c, subsys_sched_t *sched,
                    const coord_test_t *tests, uint8_t n_tests,
                    const coord_profile_t *profiles, uint8_t n_profiles,
                    const coord_hooks_t *hooks);
/** 仅在 IDLE/DONE 下允许；参数档跟随测试项默认值。 */
dz_err_t coord_select_test(coord_t *c, uint8_t idx);
/** 仅在 IDLE/DONE 下允许，用于现场换参数档。 */
dz_err_t coord_select_profile(coord_t *c, uint8_t idx);
/** 投递事件。非法转换返回 DZ_ESTATE 且状态不变。 */
dz_err_t coord_event(coord_t *c, coord_event_t ev);
/** 主循环调用：更新时间、检查超时/完成、调 pre_step，再调度子系统。 */
void     coord_poll(coord_t *c, uint32_t now_ms);
coord_state_t coord_state(const coord_t *c);
const char   *coord_state_name(coord_state_t s);

#endif
