/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef AD9833_PAL_H
#define AD9833_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_AD9833_GPIO_*]）；在调用 ad9833_init 之前调用一次。 */
void ad9833_pal_bind(const ld_pal_bind_t *b);

#endif
