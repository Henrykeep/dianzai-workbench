/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef TCS34725_PAL_H
#define TCS34725_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_TCS34725_GPIO_*]）；在调用 tcs34725_init 之前调用一次。 */
void tcs34725_pal_bind(const ld_pal_bind_t *b);

#endif
