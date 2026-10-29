/**
 * @file host_sim.h
 * @brief host-sim 移植层的仿真控制接口：只给 PC 上的测试/仿真主程序用。
 *        固件代码（drivers/algo/apps 的业务部分）不得包含本文件，check_deps.py 会拦截。
 *
 * 时间是虚拟的：只有调用 host_sim_run_us() 或 pal_delay_*() 时才前进，
 * 因此仿真结果完全可复现，和电脑快慢无关。
 */
#ifndef HOST_SIM_H
#define HOST_SIM_H

#include <stdint.h>
#include <stdbool.h>
#include "pal.h"

/** 仿真步长（微秒）。所有定时器周期必须是它的整数倍。 */
#define HOST_SIM_STEP_US 100u

/** 一阶直流电机模型：tau * dω/dt = gain * u - ω - 负载，u 为带符号占空比 -1..1。 */
typedef struct {
    pal_id_t pwm, in1, in2, enc;
    float gain_rps;        /**< 满占空比稳态转速（转/秒） */
    float tau_s;           /**< 机械时间常数（秒） */
    float counts_per_rev;  /**< 编码器每转计数（与驱动配置一致） */
    float load_rps;        /**< 恒定负载造成的转速损失（模拟摩擦/扰动），可为 0 */
    bool  dir_mode;        /**< true: in1 为方向脚（PWM_DIR 模式），in2 忽略 */
} host_sim_motor_t;

/** 复位整个仿真（时间清零、所有状态清零、解除电机绑定）。每个测试开始时调用。 */
void  host_sim_reset(void);
/** 看门狗桩（2.3.0）：pal_wdg_start 之后超过 timeout 没喂 = 被咬（锁存，host_sim_reset 清）；0 = 没启动。 */
bool     host_sim_wdg_bitten(void);
uint32_t host_sim_wdg_timeout_ms(void);
/** 掉电存储桩（2.4.0）：8 KB / 擦除单位 1 KB，不随 host_sim_reset 清；wipe = 换一片新 flash；fail_next(n) = 接下来 n 次擦/写返回 DZ_EIO。 */
#define HOST_SIM_NVM_SIZE 8192u
#define HOST_SIM_NVM_UNIT 1024u
void     host_sim_nvm_wipe(void);
void     host_sim_nvm_fail_next(int n);
uint32_t host_sim_nvm_erases(void);
/** 推进虚拟时间，期间按步长运行电机模型并触发到期的定时器回调。 */
void  host_sim_run_us(uint64_t us);
uint64_t host_sim_now_us(void);

int   host_sim_bind_motor(const host_sim_motor_t *m);   /**< 返回电机编号，失败 -1 */
float host_sim_motor_speed_rps(int motor);
void  host_sim_motor_set_load(int motor, float load_rps);

/* 观测与注入 */
bool     host_sim_gpio_level(pal_id_t id);              /**< 物理电平（已考虑 active_low 前的逻辑值） */
void     host_sim_gpio_set_input(pal_id_t id, bool active);
/** 输入脚读钩子：设了之后 pal_gpio_read 返回 cb(id, 当前所有 GPIO 逻辑值, ctx)，用来模拟矩阵键盘这类“读数取决于输出脚”的外设。NULL 取消。 */
typedef bool (*host_sim_gpio_read_cb_t)(pal_id_t id, const bool *gpio, void *ctx);
void     host_sim_gpio_read_hook(host_sim_gpio_read_cb_t cb, void *ctx);
uint16_t host_sim_pwm_duty(pal_id_t id);
void     host_sim_enc_add(pal_id_t id, int32_t counts);
void     host_sim_adc_set(pal_id_t id, uint16_t raw);
uint16_t host_sim_uart_take_tx(pal_id_t id, uint8_t *buf, uint16_t max);
void     host_sim_uart_inject_rx(pal_id_t id, const uint8_t *buf, uint16_t len);
void     host_sim_uart_set_busy(pal_id_t id, bool busy);

/** 仿真外设：给某条 I2C 总线 / 某个 SPI 设备挂一个“假芯片”回调（例如 tests 里的假 MPU6050、假 BMI088）。
 *  I2C 回调：write=true 时 buf 是主机写入的数据；false 时由回调填 buf。返回 DZ_EIO 表示该地址无应答。
 *  host_sim_reset 会清掉所有挂载。 */
typedef dz_err_t (*host_sim_i2c_fn)(void *ctx, uint8_t addr7, uint8_t reg, uint8_t *buf, uint16_t n, bool write);
typedef dz_err_t (*host_sim_spi_fn)(void *ctx, const uint8_t *tx, uint8_t *rx, uint16_t n);
void host_sim_i2c_attach(pal_id_t id, host_sim_i2c_fn fn, void *ctx);
void host_sim_spi_attach(pal_id_t id, host_sim_spi_fn fn, void *ctx);

/** 事件日志：记录 GPIO/PWM 写操作的顺序，用于验证"换向前先关 PWM"之类的时序。 */
typedef enum { HS_EV_GPIO = 1, HS_EV_PWM = 2 } host_sim_ev_type_t;
typedef struct { host_sim_ev_type_t type; pal_id_t id; uint32_t value; } host_sim_ev_t;
unsigned host_sim_events(host_sim_ev_t *out, unsigned max);  /**< 取出并清空日志 */

/** 故障注入：之后 n 次对该类资源的调用返回 DZ_EIO。 */
typedef enum { HS_FAIL_GPIO, HS_FAIL_PWM, HS_FAIL_ENC, HS_FAIL_UART, HS_FAIL_ADC, HS_FAIL_I2C, HS_FAIL_SPI, HS_FAIL_COUNT } host_sim_fail_t;
void host_sim_fail_next(host_sim_fail_t what, unsigned n);

/** 仿真侧的周期事件（模拟外部设备，例如协处理器定时发帧）。与 PAL 定时器无关，最多 4 个。 */
int host_sim_add_periodic(uint32_t period_us, void (*fn)(void *), void *ctx);

/** 设置 pal_reset_cause() 的返回值（测试上电自报）。 */
void host_sim_set_reset_cause(pal_reset_cause_t c);

#endif /* HOST_SIM_H */
