/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef NRF24L01_PAL_H
#define NRF24L01_PAL_H
#include "ld_pal.h"

#define LD_NRF24L01_GPIO_GPIO 0u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_NRF24L01_GPIO_*]）；在调用 nrf24l01_init 之前调用一次。 */
void nrf24l01_pal_bind(const ld_pal_bind_t *b);

#endif
