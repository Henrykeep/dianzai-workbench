/**
 * @file pal.h
 * @brief 平台抽象层（Platform Abstraction Layer）—— 上层唯一可见的硬件接口。
 *
 * 版本见 firmware/pal/VERSION。本文件受接口冻结保护（tools/iface_hash.py）。
 *
 * 设计要点（为什么这样设计，见 docs/01-接口规范.md）：
 *  1. 只认逻辑 ID。ID 由 board.yaml 中的逻辑名生成（board_gen.h 里的 RES_xxx），
 *     上层永远看不到 GPIOA、TIM3、USART1、PWM_0_INST 这类芯片名。
 *  2. 只用整数做硬件边界上的数值（占空比 0..PAL_DUTY_MAX、微秒、原始 ADC 码），
 *     这样没有 FPU 的芯片（如 MSPM0G3507 的 Cortex-M0+）在中断里调用也不吃亏。
 *  3. 所有函数返回 dz_err_t 或通过出参返回值；ID 不存在返回 DZ_ENODEV，
 *     本平台做不到返回 DZ_ENOTSUP —— 不允许静默失败。
 *  4. 不暴露任何全局变量；端口内部状态由端口自己持有。
 *  5. 能力下限按"最弱的常用板"设计：F103C8T6（20KB RAM）、MSPM0G3507（无 FPU、
 *     部分定时器无硬件正交解码）、ESP32（PWM 用 LEDC、编码器用 PCNT）都能实现。
 *
 * 线程/中断安全约定：
 *  - 标注 [ISR-safe] 的函数可在中断回调中调用；其余只在主循环/初始化中调用。
 *  - 同一逻辑 ID 不允许在主循环与中断中同时调用（端口不加锁，以保持零开销）。
 */
#ifndef PAL_H
#define PAL_H

#include <stdint.h>
#include <stdbool.h>
#include "dz_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/* 通用                                                                      */
/* ------------------------------------------------------------------------- */

/** 逻辑资源 ID。各类资源各自从 0 编号，由 board_gen.h 给出。 */
typedef uint8_t pal_id_t;

/** "不使用该资源"，例如单方向引脚的 H 桥没有 IN2。 */
#define PAL_ID_NONE ((pal_id_t)0xFFu)

/** 接口版本，与 firmware/pal/VERSION 一致（tools/check_deps.py 核对）。 */
#define PAL_VERSION "1.4.0"

/** PWM 占空比满量程：10000 表示 100.00%。 */
#define PAL_DUTY_MAX 10000u

/** 复位原因，用于上电自报，帮助区分"程序跑飞"和"电源被电机拉垮"。 */
typedef enum {
    PAL_RESET_UNKNOWN = 0,
    PAL_RESET_POWER_ON,   /**< 上电 */
    PAL_RESET_PIN,        /**< 复位按键 / NRST */
    PAL_RESET_BROWNOUT,   /**< 欠压 —— 常见于电机启动拉低电源 */
    PAL_RESET_WATCHDOG,   /**< 看门狗 */
    PAL_RESET_SOFTWARE,   /**< 软件复位 */
    PAL_RESET_LOCKUP      /**< 内核锁死等（平台支持时） */
} pal_reset_cause_t;

/**
 * 初始化板卡：时钟、时基、以及 board.yaml 中声明的所有外设。
 * 必须最先调用，且只调用一次。重复调用返回 DZ_ESTATE。
 */
dz_err_t pal_init(void);

/** 板卡名（与 board.yaml 的 name 一致），用于上电自报。 */
const char *pal_board_name(void);

/** 最近一次复位原因。pal_init() 之后调用有效。 */
pal_reset_cause_t pal_reset_cause(void);
/** 是不是“程序出了问题”的复位（看门狗/内核锁死）：是的话应用上电应进安全态，等人确认。@since 1.4.0 */
#define PAL_RESET_IS_FAULT(c) ((c) == PAL_RESET_WATCHDOG || (c) == PAL_RESET_LOCKUP)

/** 关中断并返回之前的状态。[ISR-safe] */
uint32_t pal_irq_save(void);
/** 恢复 pal_irq_save() 保存的状态。[ISR-safe] */
void pal_irq_restore(uint32_t state);

/**
 * 启动独立看门狗（IWDG 一类：独立时钟，主循环卡死 timeout_ms 后硬件复位，复位原因 = PAL_RESET_WATCHDOG）。
 *  - 一旦启动不能停止（硬件如此）；重复调用返回 DZ_ESTATE。
 *  - 调试器暂停内核时，平台支持的话冻结看门狗（Keil/CCS 断点不会被狗咬）。
 *  - 实际超时按片内低速时钟标称值换算，误差可达 ±30%：timeout 至少取主循环最坏周期的 5 倍。
 *  - timeout_ms 为 0 或超出硬件上限返回 DZ_EINVAL；本平台没有/没实现返回 DZ_ENOTSUP。
 * 只在初始化里调用。@since 1.3.0
 */
dz_err_t pal_wdg_start(uint32_t timeout_ms);
/** 喂狗。没启动时什么也不做。只在主循环里调（不要放进定时器中断：中断还在跑不代表主循环没卡死）。@since 1.3.0 */
void pal_wdg_kick(void);

/* ------------------------------------------------------------------------- */
/* 时基                                                                      */
/* ------------------------------------------------------------------------- */

/** 上电以来的毫秒数，约 49.7 天回绕，比较请用差值 (now - then)。[ISR-safe] */
uint32_t pal_millis(void);
/** 上电以来的微秒数，约 71.6 分钟回绕，比较请用差值。[ISR-safe] */
uint32_t pal_micros(void);
/** 忙等延时。不得在中断中调用。 */
void pal_delay_us(uint32_t us);
void pal_delay_ms(uint32_t ms);

/* ------------------------------------------------------------------------- */
/* GPIO                                                                      */
/* ------------------------------------------------------------------------- */
/*
 * 逻辑电平：true = "有效"。高/低有效在 board.yaml 的 active_low 里配置，
 * 例如 LED 低电平点亮，上层仍然写 pal_gpio_write(RES_GPIO_LED, true) 点亮。
 */

dz_err_t pal_gpio_write(pal_id_t id, bool active);         /**< [ISR-safe] */
dz_err_t pal_gpio_read(pal_id_t id, bool *active);         /**< [ISR-safe] */
dz_err_t pal_gpio_toggle(pal_id_t id);                     /**< [ISR-safe] */

/*
 * GPIO 边沿中断（PAL 1.2.0 新增）。边沿按“逻辑电平”算：RISING = 变为有效（active_low 脚即物理下降沿）。
 * 回调在中断上下文执行：level = 触发后的逻辑电平，t_us = pal_micros() 时间戳（端口在中断入口处读取）。
 * 资源必须是输入脚；同一引脚号在 STM32 上共用一条 EXTI 线，第二个不同端口的同号脚返回 DZ_EBUSY。
 * 不支持中断的端口返回 DZ_ENOTSUP（上层退回轮询）。
 */
typedef enum { PAL_EDGE_RISING = 1, PAL_EDGE_FALLING = 2, PAL_EDGE_BOTH = 3 } pal_edge_t;
typedef void (*pal_gpio_irq_cb_t)(void *ctx, bool level, uint32_t t_us);
dz_err_t pal_gpio_irq_attach(pal_id_t id, pal_edge_t edge, pal_gpio_irq_cb_t cb, void *ctx);
dz_err_t pal_gpio_irq_detach(pal_id_t id);

/* ------------------------------------------------------------------------- */
/* PWM                                                                       */
/* ------------------------------------------------------------------------- */
/*
 * 频率在 board.yaml 中固定（例如电机 20 kHz、舵机 50 Hz），运行时只改占空比。
 * 理由：多数芯片同一定时器的多个通道共享频率，运行时改频率会悄悄影响别的通道。
 */

/** 设置占空比，duty 取 0..PAL_DUTY_MAX，超出返回 DZ_EINVAL。[ISR-safe] */
dz_err_t pal_pwm_set_duty(pal_id_t id, uint16_t duty);
/** 按高电平脉宽设置（舵机常用）。脉宽大于周期返回 DZ_EINVAL。[ISR-safe] */
dz_err_t pal_pwm_set_pulse_us(pal_id_t id, uint32_t pulse_us);
/** 读取该通道实际 PWM 频率（Hz），用于自检核对分频是否正确。 */
dz_err_t pal_pwm_get_freq(pal_id_t id, uint32_t *freq_hz);

/* ------------------------------------------------------------------------- */
/* 编码器（正交或脉冲计数）                                                   */
/* ------------------------------------------------------------------------- */
/*
 * 返回 32 位有符号累计计数。硬件计数器通常只有 16 位，端口负责扩展到 32 位，
 * 前提：调用间隔内硬件计数变化小于其半量程（16 位即 32767 个计数）。
 * 方向翻转在 board.yaml 的 invert 中配置，驱动层也可再翻转一次。
 */
dz_err_t pal_enc_get_count(pal_id_t id, int32_t *count);   /**< [ISR-safe] */
/** 把累计计数清零（扩展计数一并清零）。 */
dz_err_t pal_enc_reset(pal_id_t id);

/* ------------------------------------------------------------------------- */
/* UART（端口内部用 DMA 或中断实现，上层不关心）                              */
/* ------------------------------------------------------------------------- */

/**
 * 非阻塞发送：数据被拷贝进端口自有发送缓冲后立即返回，调用者的 buf 可马上复用。
 * 缓冲剩余空间不足以放下整帧时返回 DZ_EBUSY，且一个字节也不发（保证帧完整）。
 * [ISR-safe]
 */
dz_err_t pal_uart_write(pal_id_t id, const uint8_t *buf, uint16_t len);
/** 发送缓冲是否已全部发出。 */
dz_err_t pal_uart_tx_idle(pal_id_t id, bool *idle);
/**
 * 非阻塞读取：从端口接收环形缓冲取出最多 max 字节，实际字节数写入 *got（可为 0）。
 */
dz_err_t pal_uart_read(pal_id_t id, uint8_t *buf, uint16_t max, uint16_t *got);
/** 自初始化以来因接收缓冲满而丢弃的字节数，用于判断波特率/处理速度是否够。 */
dz_err_t pal_uart_rx_dropped(pal_id_t id, uint32_t *dropped);

/* ------------------------------------------------------------------------- */
/* 周期定时器（控制环节拍）                                                   */
/* ------------------------------------------------------------------------- */

/** 定时器回调，在中断上下文中执行，应尽快返回。 */
typedef void (*pal_timer_cb_t)(void *ctx);

/**
 * 以 period_us 为周期周期性调用 cb(ctx)。周期无法精确实现时返回 DZ_EINVAL，
 * 不悄悄取近似值。已在运行时再次调用会先停止再以新参数启动。
 */
dz_err_t pal_timer_start(pal_id_t id, uint32_t period_us, pal_timer_cb_t cb, void *ctx);
dz_err_t pal_timer_stop(pal_id_t id);

/* ------------------------------------------------------------------------- */
/* ADC                                                                       */
/* ------------------------------------------------------------------------- */

typedef struct {
    uint8_t  bits;       /**< 有效位数，例如 12 */
    uint32_t vref_mv;    /**< 满量程对应的电压（mV） */
    uint32_t scale_num;  /**< 外部分压换算：被测电压 = 引脚电压 * num / den */
    uint32_t scale_den;
} pal_adc_info_t;

/** 单次阻塞采样（典型几微秒）。不得在高频中断里循环调用。 */
dz_err_t pal_adc_read(pal_id_t id, uint16_t *raw);
dz_err_t pal_adc_info(pal_id_t id, pal_adc_info_t *info);


/* ------------------------------------------------------------------------- */
/* I2C（主机，阻塞；PAL 1.1.0 新增）                                          */
/* ------------------------------------------------------------------------- */

/** 单次传输超时（ms）。传感器寄存器读写典型 < 1 ms；超时返回 DZ_ETIMEOUT，无应答（NACK）返回 DZ_EIO。 */
#define PAL_I2C_TIMEOUT_MS 5u
/**
 * 寄存器读：START addr7+W reg RESTART addr7+R buf[n] STOP（8 位寄存器地址，绝大多数传感器如此）。
 * 阻塞，不得在中断里调用；n ≤ 255。
 */
dz_err_t pal_i2c_mem_read(pal_id_t id, uint8_t addr7, uint8_t reg, uint8_t *buf, uint16_t n);
/** 寄存器写：START addr7+W reg buf[n] STOP。阻塞，不得在中断里调用；n ≤ 32。 */
dz_err_t pal_i2c_mem_write(pal_id_t id, uint8_t addr7, uint8_t reg, const uint8_t *buf, uint16_t n);

/* ------------------------------------------------------------------------- */
/* SPI（主机，阻塞；PAL 1.1.0 新增）                                          */
/* ------------------------------------------------------------------------- */

/**
 * 一个 id = 一个“SPI 设备”（总线 + 片选），同一总线上的多个芯片在 board.yaml 里写多条、共用 instance。
 * 全双工收发 n 字节：拉低片选 → 交换 → 拉高片选。tx 为 NULL 时发 0xFF；rx 为 NULL 时丢弃收到的字节。
 * 阻塞，不得在中断里调用；n ≤ 64。超时 PAL_I2C_TIMEOUT_MS。
 */
dz_err_t pal_spi_xfer(pal_id_t id, const uint8_t *tx, uint8_t *rx, uint16_t n);

#ifdef __cplusplus
}
#endif

#endif /* PAL_H */
