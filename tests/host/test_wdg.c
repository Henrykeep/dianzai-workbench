/* 看门狗：pal_wdg_* 的 host-sim 桩语义 + STM32 IWDG 分频换算（ports/stm32-cubemx/iwdg_calc.h，手算期望值）。 */
#include "tt.h"
#include "board_gen.h"
#include "host_sim.h"
#include "../../ports/stm32-cubemx/iwdg_calc.h"
#include "../../ports/mspm0-driverlib/wwdt_calc.h"

static void calc(void)
{
    uint8_t pr = 9; uint16_t rlr = 0;
    CHECK(iwdg_calc(500, 32000, &pr, &rlr) && pr == 0 && rlr == 3999);     /* 500 ms × 32 kHz / 4 = 4000 */
    CHECK(iwdg_calc(1000, 32000, &pr, &rlr) && pr == 1 && rlr == 3999);    /* /4 放不下 → /8 */
    CHECK(iwdg_calc(500, 40000, &pr, &rlr) && pr == 1 && rlr == 2499);     /* F1 LSI 40 kHz */
    CHECK(iwdg_calc(26000, 32000, &pr, &rlr) && pr == 6 && rlr == 3249);   /* /256 */
    CHECK(!iwdg_calc(33000, 32000, &pr, &rlr));                            /* 超上限 */
    CHECK(!iwdg_calc(0, 32000, &pr, &rlr));
    CHECK(iwdg_calc(1, 32000, &pr, &rlr) && pr == 0 && rlr == 7);          /* 1 ms = 8 拍 */
}

static void wcalc(void)
{
    uint8_t d = 0, p = 0; uint32_t a = 0;
    CHECK(wwdt_calc(500, 32768, &d, &p, &a) && d == 4 && WWDT_PER_BITS[p] == 12 && a == 500);    /* 4096 × 4 / 32768 = 0.5 s */
    CHECK(wwdt_calc(100, 32768, &d, &p, &a) && a >= 100 && a == 125);                         /* 粗档：向上取 125 ms */
    CHECK(wwdt_calc(1, 32768, &d, &p, &a) && d == 1 && WWDT_PER_BITS[p] == 6 && a == 1);       /* 64 拍 ≈ 1.95 ms，向下报 1 */
    CHECK(wwdt_calc(26000, 32768, &d, &p, &a) && a >= 26000 && a <= 32000);
    CHECK(!wwdt_calc(0, 32768, &d, &p, &a));
    CHECK(!wwdt_calc(9000000, 32768, &d, &p, &a));                                             /* 上限 8 × 2^25 / 32768 ≈ 8192 s */
}

static void stub(void)
{
    host_sim_reset(); pal_init();
    CHECK(!host_sim_wdg_bitten() && host_sim_wdg_timeout_ms() == 0);
    CHECK(pal_wdg_start(0) == DZ_EINVAL);
    CHECK(pal_wdg_start(100) == DZ_OK);
    CHECK(pal_wdg_start(100) == DZ_ESTATE);                                 /* 启动后不能改 */
    for (int k = 0; k < 10; k++) { host_sim_run_us(50000); pal_wdg_kick(); }
    CHECK(!host_sim_wdg_bitten());                                          /* 每 50 ms 喂：不咬 */
    host_sim_run_us(101000);
    CHECK(host_sim_wdg_bitten());
    pal_wdg_kick();
    CHECK(host_sim_wdg_bitten());                                           /* 锁存：咬了再喂也晚了 */
    host_sim_reset();
    CHECK(!host_sim_wdg_bitten());
}

void suite_wdg(void) { RUN(calc); RUN(wcalc); RUN(stub); }
