/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef SX1262_PAL_H
#define SX1262_PAL_H
#include "ld_pal.h"

#define LD_SX1262_GPIO_RESET 0u
#define LD_SX1262_GPIO_BUSY 1u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_SX1262_GPIO_*]）；在调用 sx1262_init 之前调用一次。 */
void sx1262_pal_bind(const ld_pal_bind_t *b);

#endif
