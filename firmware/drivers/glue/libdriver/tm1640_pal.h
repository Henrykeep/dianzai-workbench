/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef TM1640_PAL_H
#define TM1640_PAL_H
#include "ld_pal.h"

#define LD_TM1640_GPIO_SCLK 0u
#define LD_TM1640_GPIO_DIN 1u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_TM1640_GPIO_*]）；在调用 tm1640_init 之前调用一次。 */
void tm1640_pal_bind(const ld_pal_bind_t *b);

#endif
