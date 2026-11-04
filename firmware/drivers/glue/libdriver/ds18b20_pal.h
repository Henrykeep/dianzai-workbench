/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef DS18B20_PAL_H
#define DS18B20_PAL_H
#include "ld_pal.h"

#define LD_DS18B20_GPIO_DATA 0u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_DS18B20_GPIO_*]）；在调用 ds18b20_init 之前调用一次。 */
void ds18b20_pal_bind(const ld_pal_bind_t *b);

#endif
