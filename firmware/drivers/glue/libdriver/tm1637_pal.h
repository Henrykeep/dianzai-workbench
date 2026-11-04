/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef TM1637_PAL_H
#define TM1637_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_TM1637_GPIO_*]）；在调用 tm1637_init 之前调用一次。 */
void tm1637_pal_bind(const ld_pal_bind_t *b);

#endif
