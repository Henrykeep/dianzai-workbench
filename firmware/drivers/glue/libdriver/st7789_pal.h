/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef ST7789_PAL_H
#define ST7789_PAL_H
#include "ld_pal.h"

#define LD_ST7789_GPIO_CMD_DATA 0u
#define LD_ST7789_GPIO_RESET 1u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_ST7789_GPIO_*]）；在调用 st7789_init 之前调用一次。 */
void st7789_pal_bind(const ld_pal_bind_t *b);

#endif
