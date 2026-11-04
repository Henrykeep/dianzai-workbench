/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef CS1237_PAL_H
#define CS1237_PAL_H
#include "ld_pal.h"

#define LD_CS1237_GPIO_SCLK 0u
#define LD_CS1237_GPIO_DOUT 1u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_CS1237_GPIO_*]）；在调用 cs1237_init 之前调用一次。 */
void cs1237_pal_bind(const ld_pal_bind_t *b);

#endif
