/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef HLW8032_PAL_H
#define HLW8032_PAL_H
#include "ld_pal.h"


/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_HLW8032_GPIO_*]）；在调用 hlw8032_init 之前调用一次。 */
void hlw8032_pal_bind(const ld_pal_bind_t *b);

#endif
