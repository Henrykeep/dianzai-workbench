#include "tt.h"
#include "lpf1.h"

TEST(lpf_invalid_cfg)
{
    lpf1_t f;
    CHECK(lpf1_init(&f, &(lpf1_cfg_t){ 0.0f, 0.001f }) == DZ_EINVAL);
    CHECK(lpf1_init(&f, &(lpf1_cfg_t){ 10.0f, 0.0f }) == DZ_EINVAL);
    CHECK(lpf1_init(&f, &(lpf1_cfg_t){ NAN, 0.001f }) == DZ_EINVAL);
    CHECK(lpf1_init(0, &(lpf1_cfg_t){ 10.0f, 0.001f }) == DZ_EINVAL);
    CHECK(lpf1_init(&f, 0) == DZ_EINVAL);
    CHECK(lpf1_init_alpha(&f, 0.0f) == DZ_EINVAL);
    CHECK(lpf1_init_alpha(&f, 1.5f) == DZ_EINVAL);
    CHECK(lpf1_init_alpha(&f, 1.0f) == DZ_OK);
}

TEST(lpf_first_sample_primes_and_step)
{
    lpf1_t f;
    CHECK(lpf1_init(&f, &(lpf1_cfg_t){ 10.0f, 0.001f }) == DZ_OK);
    CHECK_NEAR(lpf1_update(&f, 5.0f), 5.0f, 1e-6);      /* 第一个样本直接输出，不从 0 爬升 */
    for (int i = 0; i < 2000; i++) lpf1_update(&f, 1.0f);
    CHECK_NEAR(lpf1_value(&f), 1.0f, 1e-3);
    /* 时间常数：1/(2π·10) ≈ 15.9 ms 后到 63% */
    lpf1_reset(&f, 0.0f);
    for (int i = 0; i < 16; i++) lpf1_update(&f, 1.0f);
    CHECK_NEAR(lpf1_value(&f), 0.63, 0.04);
}

TEST(lpf_nan_ignored)
{
    lpf1_t f;
    lpf1_init_alpha(&f, 0.5f);
    lpf1_update(&f, 2.0f);
    CHECK_NEAR(lpf1_update(&f, NAN), 2.0f, 1e-6);
    CHECK_NEAR(lpf1_update(&f, INFINITY), 2.0f, 1e-6);
    lpf1_clear(&f);
    CHECK_NEAR(lpf1_update(&f, 7.0f), 7.0f, 1e-6);
}

TEST(lpf_selftest) { CHECK(lpf1_selftest() == DZ_OK); }

void suite_lpf(void) { RUN(lpf_invalid_cfg); RUN(lpf_first_sample_primes_and_step); RUN(lpf_nan_ignored); RUN(lpf_selftest); }
