/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef TTP229_PAL_H
#define TTP229_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_TTP229_GPIO_*]）；在调用 ttp229_init 之前调用一次。 */
void ttp229_pal_bind(const ld_pal_bind_t *b);

#endif
