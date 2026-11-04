/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef DS1302_PAL_H
#define DS1302_PAL_H
#include "ld_pal.h"

#define LD_DS1302_GPIO_CE 0u
#define LD_DS1302_GPIO_SCLK 1u
#define LD_DS1302_GPIO_IO 2u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_DS1302_GPIO_*]）；在调用 ds1302_init 之前调用一次。 */
void ds1302_pal_bind(const ld_pal_bind_t *b);

#endif
