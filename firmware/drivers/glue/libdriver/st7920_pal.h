/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef ST7920_PAL_H
#define ST7920_PAL_H
#include "ld_pal.h"

#define LD_ST7920_GPIO_CS 0u
#define LD_ST7920_GPIO_SCLK 1u
#define LD_ST7920_GPIO_SID 2u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_ST7920_GPIO_*]）；在调用 st7920_init 之前调用一次。 */
void st7920_pal_bind(const ld_pal_bind_t *b);

#endif
