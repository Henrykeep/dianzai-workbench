/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef ADXL345_PAL_H
#define ADXL345_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_ADXL345_GPIO_*]）；在调用 adxl345_init 之前调用一次。 */
void adxl345_pal_bind(const ld_pal_bind_t *b);

#endif
