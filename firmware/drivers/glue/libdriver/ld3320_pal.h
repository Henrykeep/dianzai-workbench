/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef LD3320_PAL_H
#define LD3320_PAL_H
#include "ld_pal.h"

#define LD_LD3320_GPIO_RESET 0u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_LD3320_GPIO_*]）；在调用 ld3320_init 之前调用一次。 */
void ld3320_pal_bind(const ld_pal_bind_t *b);

#endif
