/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef HCSR04_PAL_H
#define HCSR04_PAL_H
#include "ld_pal.h"

#define LD_HCSR04_GPIO_TRIG 0u
#define LD_HCSR04_GPIO_ECHO 1u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_HCSR04_GPIO_*]）；在调用 hcsr04_init 之前调用一次。 */
void hcsr04_pal_bind(const ld_pal_bind_t *b);

#endif
