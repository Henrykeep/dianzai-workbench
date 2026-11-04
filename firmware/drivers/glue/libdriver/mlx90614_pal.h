/* 由 tools/gen_driver_glue.py 生成，勿手改（XinTai，AGPL-3.0-or-later）。 */
#ifndef MLX90614_PAL_H
#define MLX90614_PAL_H
#include "ld_pal.h"

#define LD_MLX90614_GPIO_SCL 0u
#define LD_MLX90614_GPIO_SDA 1u

/** 绑定 pal 资源（i2c/spi/uart/gpio[LD_MLX90614_GPIO_*]）；在调用 mlx90614_init 之前调用一次。 */
void mlx90614_pal_bind(const ld_pal_bind_t *b);

#endif
