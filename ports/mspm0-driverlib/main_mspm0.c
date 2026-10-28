/**
 * @file main_mspm0.c
 * @brief MSPM0 入口：SysConfig 不生成 main()，由移植层提供。SYSCFG_DL_init() → 端口启动 → app_init() → 循环 app_loop()。
 */
#include "port_mspm0.h"
#include "app.h"

dz_err_t dz_m0_start(void);

int main(void)
{
    SYSCFG_DL_init();
    dz_err_t e = dz_m0_start();
    if (e == DZ_OK) e = app_init();
    if (e != DZ_OK) {
        for (;;) {
#ifdef RES_GPIO_LED
            pal_gpio_toggle(RES_GPIO_LED);
#endif
            pal_delay_ms(50);
        }
    }
    for (;;) app_loop();
}
