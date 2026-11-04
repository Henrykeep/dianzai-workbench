/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef AD7705_PAL_H
#define AD7705_PAL_H
#include "ld_pal.h"

#define LD_AD7705_GPIO_GPIO_RESET 0u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_AD7705_GPIO_*]）；在调用 ad7705_init 之前调用一次。 */
void ad7705_pal_bind(const ld_pal_bind_t *b);

#endif
