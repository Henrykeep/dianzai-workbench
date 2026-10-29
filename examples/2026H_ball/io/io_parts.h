#ifndef IO_PARTS_H
#define IO_PARTS_H
/* io 胶水内部接口（只给 io/ 下的 .c 用）：io_main.c 持有共享状态与协调器，io_link.c / io_imu.c 通过这里访问。 */
#include <stdint.h>
#include "project_gen.h"
#include "coord.h"
shared_state_t *io_state(void);
coord_t *io_coord(void);
void io_link_init(void);
void io_link_read(void);
void io_link_write(uint32_t now);
void io_imu_init(void);
void io_imu_read(uint32_t now, const params_t *p);
#endif
