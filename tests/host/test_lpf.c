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

#include "biquad.h"
/* 同在 100 Hz 衰减 20 dB（fs=1 kHz）：lpf1 fc=9.9 Hz，lpf2p fc=32.7 Hz；比 2 Hz 正弦的过零滞后 */
static float lag_deg(int second, float fc)
{
    lpf1_t a; biquad_t b; float fs = 1000.0f, hz = 2.0f, prev = 0.0f, t0 = -1.0f;
    lpf1_init(&a, &(lpf1_cfg_t){ fc, 1.0f / fs }); lpf2p_init(&b, fc, fs);
    lpf1_reset(&a, 0.0f); biquad_reset(&b, 0.0f);
    for (int i = 1; i < 3000; i++) {
        float x = sinf(2.0f * 3.14159265f * hz * i / fs);
        float y = second ? biquad_update(&b, x) : lpf1_update(&a, x);
        if (i > 1000 && prev < 0.0f && y >= 0.0f) { t0 = (i - y / (y - prev)) / fs; break; }
        prev = y;
    }
    float per = 1.0f / hz; float ph = fmodf(t0, per) / per * 360.0f; return ph;
}
TEST(lpf2p_less_lag_than_lpf1)
{
    CHECK_NEAR(lag_deg(0, 9.9f), 11.1, 0.6);
    CHECK_NEAR(lag_deg(1, 32.7f), 4.9, 0.6);
}
TEST(biquad_selftest_ok) { CHECK(biquad_selftest() == DZ_OK); }
void suite_biquad(void) { RUN(lpf2p_less_lag_than_lpf1); RUN(biquad_selftest_ok); }
