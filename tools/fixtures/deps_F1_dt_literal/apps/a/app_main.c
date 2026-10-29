/* 复刻 2026H io_main.c 修复前的写法：调度按 1 ms 门控，编码器 dt 另写一份 0.001f */
typedef struct { float dt_s; } enc_cfg_t;
void f(void)
{
    enc_cfg_t ec;
    ec.dt_s = 0.001f;
    (void)ec;
}
