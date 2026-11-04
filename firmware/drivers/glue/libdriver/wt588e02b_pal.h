/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef WT588E02B_PAL_H
#define WT588E02B_PAL_H
#include "ld_pal.h"

#define LD_WT588E02B_GPIO_SCLK 0u
#define LD_WT588E02B_GPIO_MOSI 1u
#define LD_WT588E02B_GPIO_MISO 2u
#define LD_WT588E02B_GPIO_CS 3u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_WT588E02B_GPIO_*]）；在调用 wt588e02b_init 之前调用一次。 */
void wt588e02b_pal_bind(const ld_pal_bind_t *b);

#endif
