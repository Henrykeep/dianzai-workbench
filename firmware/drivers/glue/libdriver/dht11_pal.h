/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef DHT11_PAL_H
#define DHT11_PAL_H
#include "ld_pal.h"

#define LD_DHT11_GPIO_DATA 0u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_DHT11_GPIO_*]）；在调用 dht11_init 之前调用一次。 */
void dht11_pal_bind(const ld_pal_bind_t *b);

#endif
