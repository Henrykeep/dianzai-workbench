/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef X9CXX_PAL_H
#define X9CXX_PAL_H
#include "ld_pal.h"

#define LD_X9CXX_GPIO_CS 0u
#define LD_X9CXX_GPIO_UP_DOWN 1u
#define LD_X9CXX_GPIO_INC 2u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_X9CXX_GPIO_*]）；在调用 x9cxx_init 之前调用一次。 */
void x9cxx_pal_bind(const ld_pal_bind_t *b);

#endif
