/**
 * @file subsys.h
 * @brief 通用子系统接口与调度器。
 *
 * 一道题 = 若干子系统 + 一个共享状态结构体 + 顶层协调状态机。子系统的数量、名字、周期、
 * 共享状态字段都写在每题的 project.yaml 里，由 tools/gen_project.py 生成，本框架不认识任何具体题目。
 *
 * 规则（check_deps.py 会检查）：
 *  - 子系统之间不互相 #include、不互相调用，只通过共享状态交换数据；
 *  - 每个子系统只写自己 owns 的那一段共享状态，读别的段；
 *  - 子系统不碰硬件（不包含 pal.h / board_gen.h / 驱动）：硬件读写放在题目的 io 胶水层，
 *    这样子系统可以喂模拟数据单独测试。
 */
#ifndef SUBSYS_H
#define SUBSYS_H

#include <stdint.h>
#include <stdbool.h>
#include "dz_err.h"

#define SUBSYS_VERSION "1.0.0"

/** 运行模式：由协调状态机下发给所有子系统 */
typedef enum {
    SUBSYS_MODE_IDLE = 0,   /**< 待机：输出安全值（电机停、舵机回中） */
    SUBSYS_MODE_RUN,        /**< 正常运行 */
    SUBSYS_MODE_ESTOP       /**< 急停：立即输出安全值，直到协调器复位 */
} subsys_mode_t;

/**
 * 子系统描述。state 指向题目的共享状态结构体（类型由生成代码定义，这里用 void* 保持框架通用）；
 * params 指向当前参数档。所有回调都可以为 NULL。
 */
typedef struct {
    const char *name;
    uint16_t period_ms;                                            /**< 调用周期，>0 */
    bool     run_always;   /**< true：IDLE/ESTOP 下也调用 step（例如传感器处理）；false：只在 RUN 下调用 */
    dz_err_t (*init)(void *state, const void *params);
    void     (*step)(void *state, const void *params, uint32_t now_ms);
    void     (*on_mode)(void *state, subsys_mode_t mode);          /**< 模式切换时调用一次 */
    dz_err_t (*selftest)(void);                                    /**< 纯逻辑自检（模拟数据） */
} subsys_t;

#define SUBSYS_MAX 16

typedef struct {
    const subsys_t *list[SUBSYS_MAX];
    uint32_t        next_ms[SUBSYS_MAX];
    uint32_t        overrun[SUBSYS_MAX];
    bool            started[SUBSYS_MAX];   /**< 错过周期的次数（主循环太慢的信号） */
    uint8_t         count;
    void           *state;
    const void     *params;
    subsys_mode_t   mode;
} subsys_sched_t;

/** 初始化调度器并依次调用各子系统 init。任一失败返回其错误码（已初始化的保持不动）。 */
dz_err_t subsys_sched_init(subsys_sched_t *s, const subsys_t *const *list, uint8_t n,
                           void *state, const void *params);
/** 主循环里反复调用：到期的子系统按列表顺序执行一次 step。now_ms 回绕安全。 */
void     subsys_sched_poll(subsys_sched_t *s, uint32_t now_ms);
/** 切换模式/参数档（参数档可为 NULL 表示不变）。 */
void     subsys_sched_set_mode(subsys_sched_t *s, subsys_mode_t mode);
void     subsys_sched_set_params(subsys_sched_t *s, const void *params);
/** 依次运行所有子系统 selftest，返回第一个失败的下标，全过返回 -1。 */
int      subsys_sched_selftest(const subsys_sched_t *s);

#endif
