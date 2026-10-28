/* STM32F4 的 main：所有应用共用。应用只实现 app_init()/app_loop()（见 apps/include/app.h）。 */
#include "board_gen.h"
#include "app.h"

int main(void)
{
    dz_err_t e = pal_init();          /* 部分资源失败也继续：失败资源在使用时返回错误 */
    if (e == DZ_OK) e = app_init();
    if (e != DZ_OK) {
        /* 故障：LED 快闪（10 Hz）。用调试器看 e 的值，或在 docs/01 查错误码 */
        for (;;) {
#if defined(RES_GPIO_LED)
            pal_gpio_toggle(RES_GPIO_LED);
#endif
            pal_delay_ms(50);
        }
    }
    for (;;) app_loop();
}

/* 硬件异常：停在这里方便调试器定位，不悄悄复位 */
void HardFault_Handler(void) { for (;;) { } }
