/**
 * @file pal_hal_compat.h
 * @brief 把直接调 STM32 HAL 的第三方驱动（ADS1256 / ST7735 / ILI9488）换成 pal_* 时用的几个 pal 风格帮手
 *        （XinTai 自写，AGPL-3.0-or-later）。tools/pal_patch_hal.py 只把 HAL_* 调用替换成下面这些/pal_* 调用。
 *
 * 片选：这些驱动自己用 GPIO 拉片选，所以 board.yaml 里给它们的 SPI 设备填一个空脚做 cs
 *       （pal_spi_xfer 每次调用会拉一次自己的 cs）；驱动的 CS/DC/RST 脚各写一条 gpio（dir: out，高有效）。
 */
#ifndef PAL_HAL_COMPAT_H
#define PAL_HAL_COMPAT_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "pal.h"

/** 读引脚电平：1 = 高（active），0 = 低或读失败。 */
static inline uint8_t pal_gpio_level(pal_id_t id)
{
    bool v = false;
    return (pal_gpio_read(id, &v) == DZ_OK && v) ? 1u : 0u;
}

/** 只发：长度不限，按 pal_spi_xfer 的 64 字节分块（驱动自己控制片选，分块不影响时序）。 */
static inline dz_err_t pal_spi_tx(pal_id_t id, const uint8_t *buf, uint32_t n)
{
    while (n) {
        uint16_t k = (uint16_t)(n > 64u ? 64u : n);
        dz_err_t e = pal_spi_xfer(id, buf, NULL, k);
        if (e != DZ_OK) return e;
        buf += k; n -= k;
    }
    return DZ_OK;
}

/** 只收（发 0xFF）：长度不限，64 字节分块。 */
static inline dz_err_t pal_spi_rx(pal_id_t id, uint8_t *buf, uint32_t n)
{
    while (n) {
        uint16_t k = (uint16_t)(n > 64u ? 64u : n);
        dz_err_t e = pal_spi_xfer(id, NULL, buf, k);
        if (e != DZ_OK) return e;
        buf += k; n -= k;
    }
    return DZ_OK;
}

#endif
