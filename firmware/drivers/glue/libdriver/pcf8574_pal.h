/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef PCF8574_PAL_H
#define PCF8574_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_PCF8574_GPIO_*]）；在调用 pcf8574_init 之前调用一次。 */
void pcf8574_pal_bind(const ld_pal_bind_t *b);

#endif
