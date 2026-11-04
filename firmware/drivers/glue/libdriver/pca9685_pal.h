/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef PCA9685_PAL_H
#define PCA9685_PAL_H
#include "ld_pal.h"

#define LD_PCA9685_GPIO_OE 0u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_PCA9685_GPIO_*]）；在调用 pca9685_init 之前调用一次。 */
void pca9685_pal_bind(const ld_pal_bind_t *b);

#endif
