#ifndef HOOKS_H
#define HOOKS_H
#include "coord.h"
extern const coord_hooks_t g_project_hooks;
/** io 层提供：上位机经 LINK 给的钢珠目标 px（默认 0）。 */
float io_host_ball_sp_px(void);
#endif
