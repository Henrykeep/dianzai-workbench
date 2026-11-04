/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef MAX30102_PAL_H
#define MAX30102_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_MAX30102_GPIO_*]）；在调用 max30102_init 之前调用一次。 */
void max30102_pal_bind(const ld_pal_bind_t *b);

#endif
