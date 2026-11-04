/**
 * @file ad983x_port.c
 * @brief ad983x_port.h 的实现：SPI / GPIO 胶水接到 pal_spi_xfer / pal_gpio_write。
 */
#include "ad983x_port.h"

static BSPGPIOInstance g_ad9850_reset = { PAL_ID_NONE };

void ad983x_spi_ad9833(SPIInstance *s, pal_id_t spi)
{
    if (s) { s->spi = spi; s->fq_ud = PAL_ID_NONE; s->lsb_first = false; s->frames = 0; }
}

void ad983x_spi_ad9850(SPIInstance *s, pal_id_t spi, pal_id_t fq_ud)
{
    if (s) { s->spi = spi; s->fq_ud = fq_ud; s->lsb_first = true; s->frames = 0; }
}

void ad983x_bind_ad9850_reset(pal_id_t reset) { g_ad9850_reset.id = reset; }

/* 与原 BSPSPIWrite16 一致：一个 FSYNC 低电平窗口内连续发全部 16 位字，高字节先出。 */
bool SPIWrite16(SPIInstance *instance, const uint16_t *words, size_t word_count)
{
    uint8_t buf[64];
    size_t i;
    if (!instance || instance->lsb_first || !words || word_count == 0u || word_count > sizeof buf / 2u) return false;
    for (i = 0; i < word_count; ++i) {
        buf[2u * i]      = (uint8_t)(words[i] >> 8);
        buf[2u * i + 1u] = (uint8_t)(words[i] & 0xFFu);
    }
    if (pal_spi_xfer(instance->spi, buf, NULL, (uint16_t)(2u * word_count)) != DZ_OK) return false;
    instance->frames++;
    return true;
}

static uint8_t rev8(uint8_t b)
{
    b = (uint8_t)((b & 0xF0u) >> 4 | (b & 0x0Fu) << 4);
    b = (uint8_t)((b & 0xCCu) >> 2 | (b & 0x33u) << 2);
    return (uint8_t)((b & 0xAAu) >> 1 | (b & 0x55u) << 1);
}

/* 与原 BSPSPIWriteAD9850Frame 一致：LSB 先出的字节流，发完给 FQ_UD 一个上升沿锁存。 */
bool SPIWriteAD9850Frame(SPIInstance *instance, const uint8_t *bytes, size_t byte_count)
{
    uint8_t buf[8];
    size_t i;
    if (!instance || !instance->lsb_first || !bytes || byte_count == 0u || byte_count > sizeof buf) return false;
    for (i = 0; i < byte_count; ++i) buf[i] = rev8(bytes[i]);
    if (pal_gpio_write(instance->fq_ud, false) != DZ_OK) return false;
    if (pal_spi_xfer(instance->spi, buf, NULL, (uint16_t)byte_count) != DZ_OK) return false;
    if (pal_gpio_write(instance->fq_ud, true) != DZ_OK) return false;   /* tWH ≥ 7 ns：两次 GPIO 写之间足够 */
    (void)pal_gpio_write(instance->fq_ud, false);
    instance->frames++;
    return true;
}

BSPGPIOInstance *BSPGPIORegister(BSP_GPIO_Channel_e channel)
{
    if (channel != BSP_GPIO_CHANNEL_AD9850_RESET || g_ad9850_reset.id == PAL_ID_NONE) return NULL;
    return &g_ad9850_reset;
}

bool BSPGPIOWrite(BSPGPIOInstance *instance, bool active)
{
    if (!instance) return false;
    if (pal_gpio_write(instance->id, active) != DZ_OK) return false;
    if (active) pal_delay_us(1);   /* RESET 高电平 ≥ 5 个参考时钟周期 */
    return true;
}

static uint32_t ftw_round(uint32_t fref, uint32_t f, uint64_t modulus)
{
    return (uint32_t)((((uint64_t)f * modulus) + (fref / 2u)) / fref);
}

uint32_t ad9833_ftw(uint32_t fref_hz, uint32_t f_hz)
{
    if (fref_hz == 0u || fref_hz > 25000000u || f_hz == 0u || f_hz > fref_hz / 2u) return 0;
    return ftw_round(fref_hz, f_hz, 268435456ull) & 0x0FFFFFFFu;
}

uint32_t ad9850_ftw(uint32_t fref_hz, uint32_t f_hz)
{
    if (fref_hz == 0u || f_hz == 0u || f_hz > fref_hz / 2u) return 0;
    return ftw_round(fref_hz, f_hz, 4294967296ull);
}

uint64_t ad983x_actual_mhz(uint32_t ftw, uint32_t fref_hz, unsigned bits)
{
    if (bits == 0u || bits > 32u) return 0;
    uint64_t q = (uint64_t)ftw * fref_hz;            /* < 2^64 */
    uint64_t mask = (bits == 64u) ? ~0ull : ((1ull << bits) - 1u);
    return (q >> bits) * 1000u + (((q & mask) * 1000u + (1ull << (bits - 1u))) >> bits);
}
