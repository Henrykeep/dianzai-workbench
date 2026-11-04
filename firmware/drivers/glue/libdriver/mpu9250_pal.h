/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef MPU9250_PAL_H
#define MPU9250_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_MPU9250_GPIO_*]）；在调用 mpu9250_init 之前调用一次。 */
void mpu9250_pal_bind(const ld_pal_bind_t *b);

#endif
