#include "pal.h"
static volatile int32_t s_cnt;
static void on_a(void *ctx, bool level, uint32_t t_us)
{
    (void)ctx; (void)t_us;
    s_cnt += level ? 1 : -1;
    printf("cnt=%ld\n", (long)s_cnt);   /* I1：中断里打印 */
}
static void on_b(void *ctx, bool level, uint32_t t_us) { (void)ctx; (void)level; (void)t_us; s_cnt++; }   /* 合规 */
void enc_init(void)
{
    (void)pal_gpio_irq_attach(1, PAL_EDGE_BOTH, on_a, 0);
    (void)pal_gpio_irq_attach(2, PAL_EDGE_BOTH, on_b, 0);
}
