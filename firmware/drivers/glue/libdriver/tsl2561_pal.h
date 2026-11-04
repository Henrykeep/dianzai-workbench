/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef TSL2561_PAL_H
#define TSL2561_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_TSL2561_GPIO_*]）；在调用 tsl2561_init 之前调用一次。 */
void tsl2561_pal_bind(const ld_pal_bind_t *b);

#endif
