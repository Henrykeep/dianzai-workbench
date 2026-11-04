/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef HX711_PAL_H
#define HX711_PAL_H
#include "ld_pal.h"

#define LD_HX711_GPIO_BUS 0u
#define LD_HX711_GPIO_CLOCK 1u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_HX711_GPIO_*]）；在调用 hx711_init 之前调用一次。 */
void hx711_pal_bind(const ld_pal_bind_t *b);

#endif
