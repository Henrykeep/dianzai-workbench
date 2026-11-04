/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef ADS1115_PAL_H
#define ADS1115_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_ADS1115_GPIO_*]）；在调用 ads1115_init 之前调用一次。 */
void ads1115_pal_bind(const ld_pal_bind_t *b);

#endif
