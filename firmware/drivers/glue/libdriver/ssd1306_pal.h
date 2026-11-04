/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef SSD1306_PAL_H
#define SSD1306_PAL_H
#include "ld_pal.h"

#define LD_SSD1306_GPIO_SPI_CMD_DATA 0u
#define LD_SSD1306_GPIO_RESET 1u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_SSD1306_GPIO_*]）；在调用 ssd1306_init 之前调用一次。 */
void ssd1306_pal_bind(const ld_pal_bind_t *b);

#endif
