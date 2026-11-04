/**
 * @file ld_pal.h
 * @brief 芯台通用胶水：libdriver 的 driver_<part>_interface_* 回调 → pal_*（XinTai 自写，AGPL-3.0-or-later）。
 *
 * 每个 libdriver 驱动只认一组全局 interface 函数（iic/spi/uart/gpio/delay/debug_print）。
 * tools/gen_driver_glue.py 读每个驱动的 interface 头，按函数名后缀生成 glue/libdriver/<part>_pal.c，
 * 函数体全部转到本文件的 ld_* 帮手。用户只调一次 <part>_pal_bind(&bind) 指定 pal id。
 *
 * 地址约定：libdriver 传 8 位地址（addr7 << 1），这里右移成 pal 的 7 位地址。
 * 限制（pal 1.1 能力所限，返回 1 = 失败，驱动会按通信错误处理）：
 *  - I2C 无寄存器的纯读（*_iic_read_cmd）与 16 位寄存器读：pal 只有 mem_read；
 *  - 一次 SPI 片选窗口最多 64 字节（pal_spi_xfer n ≤ 64）；
 *  - QSPI 只支持全部单线（line = 1）。
 */
#ifndef LD_PAL_H
#define LD_PAL_H
#include <stdint.h>
#include <stdbool.h>
#include "pal.h"

#ifdef __cplusplus
extern "C" {
#endif

#define LD_PAL_MAX_GPIO 8u

/** 一个驱动实例用到的 pal 资源；不用的填 PAL_ID_NONE。gpio[] 下标见生成的 <part>_pal.h 里的 LD_<PART>_GPIO_*。 */
typedef struct {
    pal_id_t i2c;
    pal_id_t spi;
    pal_id_t uart;
    pal_id_t adc;
    pal_id_t gpio[LD_PAL_MAX_GPIO];
} ld_pal_bind_t;

#define LD_PAL_BIND_NONE { PAL_ID_NONE, PAL_ID_NONE, PAL_ID_NONE, PAL_ID_NONE, \
    { PAL_ID_NONE, PAL_ID_NONE, PAL_ID_NONE, PAL_ID_NONE, PAL_ID_NONE, PAL_ID_NONE, PAL_ID_NONE, PAL_ID_NONE } }

uint8_t ld_iic_read(pal_id_t id, uint8_t addr8, uint8_t reg, uint8_t *buf, uint16_t len);
uint8_t ld_iic_write(pal_id_t id, uint8_t addr8, uint8_t reg, const uint8_t *buf, uint16_t len);
uint8_t ld_iic_write_cmd(pal_id_t id, uint8_t addr8, const uint8_t *buf, uint16_t len);
uint8_t ld_iic_read_cmd(pal_id_t id, uint8_t addr8, uint8_t *buf, uint16_t len);
uint8_t ld_iic_write16(pal_id_t id, uint8_t addr8, uint16_t reg, const uint8_t *buf, uint16_t len);
uint8_t ld_iic_read16(pal_id_t id, uint8_t addr8, uint16_t reg, uint8_t *buf, uint16_t len);

/** 一个片选窗口：先发 hdr[hn]，再发 tx[tn]，再收 rx[rn]（全双工交换，收到的头部丢弃）。 */
uint8_t ld_spi_frame(pal_id_t id, const uint8_t *hdr, uint16_t hn, const uint8_t *tx, uint16_t tn, uint8_t *rx, uint16_t rn);
uint8_t ld_spi_transmit(pal_id_t id, const uint8_t *tx, uint8_t *rx, uint16_t len);

uint8_t ld_uart_write(pal_id_t id, const uint8_t *buf, uint16_t len);
uint16_t ld_uart_read(pal_id_t id, uint8_t *buf, uint16_t len);
uint8_t ld_uart_flush(pal_id_t id);

uint8_t ld_adc_read(pal_id_t id, uint16_t *raw);
uint8_t ld_gpio_write(pal_id_t id, uint8_t level);
uint8_t ld_gpio_read(pal_id_t id, uint8_t *level);

void ld_delay_ms(uint32_t ms);
void ld_delay_us(uint32_t us);
void ld_debug_vprint(const char *fmt, __builtin_va_list ap);
void ld_irq_disable(void);
void ld_irq_enable(void);
void ld_time_now(uint64_t *s, uint32_t *us, uint64_t *total_us, uint32_t *total_ms);

/** debug_print 输出口：默认丢弃；需要日志的应用自己实现同名强符号（例如转到 pal_uart_write）。 */
void ld_pal_debug_sink(const char *line, uint16_t len);

#ifdef __cplusplus
}
#endif
#endif /* LD_PAL_H */
