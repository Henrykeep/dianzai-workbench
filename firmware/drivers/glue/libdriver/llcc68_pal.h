/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef LLCC68_PAL_H
#define LLCC68_PAL_H
#include "ld_pal.h"

#define LD_LLCC68_GPIO_RESET 0u
#define LD_LLCC68_GPIO_BUSY 1u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_LLCC68_GPIO_*]）；在调用 llcc68_init 之前调用一次。 */
void llcc68_pal_bind(const ld_pal_bind_t *b);

#endif
