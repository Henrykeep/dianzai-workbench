/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef MFRC522_PAL_H
#define MFRC522_PAL_H
#include "ld_pal.h"

#define LD_MFRC522_GPIO_RESET 0u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_MFRC522_GPIO_*]）；在调用 mfrc522_init 之前调用一次。 */
void mfrc522_pal_bind(const ld_pal_bind_t *b);

#endif
