/* 信号类模块（移植自 LP-MSPM0G3507_freertos_firework，MIT）：spectrum / sigfilt / dds / capfreq / wavemeas / menu / keypad4x4。
 * 期望值都按解析式手算，不拿实现自己的输出当期望。 */
#include <string.h>
#include "tt.h"
#include "spectrum.h"
#include "sigfilt.h"
#include "dds.h"
#include "capfreq.h"
#include "wavemeas.h"
#include "menu.h"
#include "keypad4x4.h"
#include "host_sim.h"
#include "board_gen.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static spec_work_t W;
static float X[1024];

TEST(spectrum_tone_and_interp)
{
    spec_result_t r;
    /* 整周期：1 kHz @ 25.6 kHz × 256 点 = 第 10 bin，幅度 0.8，直流 1.0 */
    for (int i = 0; i < 256; i++) X[i] = 1.0f + 0.8f * (float)sin(2 * M_PI * 1000.0 * i / 25600.0);
    CHECK(spec_analyze(&W, X, 256, 25600.0f, SPEC_WIN_RECT, true, &r) == DZ_OK);
    CHECK(r.peak_bin == 10); CHECK_NEAR(r.peak_hz, 1000.0, 0.5); CHECK_NEAR(r.peak_mag, 0.8, 0.002); CHECK_NEAR(r.dc, 1.0, 1e-4);
    CHECK(r.ncomp == 1);
    /* 非整周期：1234.5 Hz，bin 宽 100 Hz；Hann + 三点插值误差应远小于一个 bin */
    for (int i = 0; i < 256; i++) X[i] = 0.5f * (float)sin(2 * M_PI * 1234.5 * i / 25600.0);
    CHECK(spec_analyze(&W, X, 256, 25600.0f, SPEC_WIN_HANN, true, &r) == DZ_OK);
    CHECK_NEAR(r.peak_hz, 1234.5, 15.0);
    CHECK(r.peak_mag > 0.5f * 0.80f && r.peak_mag <= 0.5f * 1.01f);     /* Hann 扇贝损失 ≤ 1.42 dB */
    float bands_max = 0; for (unsigned b = 1; b < SPEC_BANDS; b++) if (r.bands[b] > bands_max) bands_max = r.bands[b];
    CHECK_NEAR(bands_max, r.peak_mag, 1e-6);
}

TEST(spectrum_components_sorted)
{
    spec_result_t r;
    /* 三个整周期分量：3 kHz(0.3)、1 kHz(1.0)、2 kHz(0.04 < 1/20 → 不算) */
    for (int i = 0; i < 512; i++) {
        double t = i / 51200.0;
        X[i] = (float)(1.0 * sin(2 * M_PI * 1000 * t) + 0.3 * sin(2 * M_PI * 3000 * t) + 0.04 * sin(2 * M_PI * 2000 * t));
    }
    CHECK(spec_analyze(&W, X, 512, 51200.0f, SPEC_WIN_RECT, true, &r) == DZ_OK);
    CHECK(r.ncomp == 2);
    CHECK_NEAR(r.comp[0].freq_hz, 1000.0, 0.5); CHECK_NEAR(r.comp[1].freq_hz, 3000.0, 0.5);
    CHECK_NEAR(r.comp[1].mag, 0.3, 0.002);
}

TEST(spectrum_phase_and_thd)
{
    spec_result_t a, b;
    static float Y[256];
    for (int i = 0; i < 256; i++) {
        double ph = 2 * M_PI * 1000.0 * i / 25600.0;
        X[i] = (float)sin(ph); Y[i] = (float)sin(ph + 60.0 * M_PI / 180.0);   /* b 超前 60° */
    }
    spec_analyze(&W, X, 256, 25600.0f, SPEC_WIN_HANN, true, &a);
    spec_analyze(&W, Y, 256, 25600.0f, SPEC_WIN_HANN, true, &b);
    CHECK_NEAR(spec_phase_diff_deg(&a, &b), 60.0, 1.0);
    CHECK_NEAR(spec_phase_diff_deg(&b, &a), -60.0, 1.0);
    /* 方波：THD 理论 sqrt(π²/8 − 1) = 48.3%（含全部奇次谐波）；只算到 15 次 = sqrt(Σ1/k²)，k=3,5..15 → 45.4% */
    for (int i = 0; i < 1024; i++) X[i] = ((i / 32) % 2) ? -1.0f : 1.0f;            /* 周期 64 点，16 个整周期 */
    spec_result_t r;
    CHECK(spec_analyze(&W, X, 1024, 64000.0f, SPEC_WIN_RECT, true, &r) == DZ_OK);
    CHECK_NEAR(r.peak_hz, 1000.0, 0.5);
    double s = 0; for (int k = 3; k <= 15; k += 2) s += 1.0 / (k * k);
    CHECK_NEAR(spec_thd(&W, &r, 15), sqrt(s), 0.02);
    CHECK_NEAR(r.peak_mag, 4.0 / M_PI, 0.02);                                      /* 方波基波幅度 4/π */
}

TEST(spectrum_rejects)
{
    spec_result_t r;
    memset(X, 0, sizeof X);
    CHECK(spec_analyze(&W, X, 100, 1000.0f, SPEC_WIN_RECT, true, &r) == DZ_EINVAL);   /* 非 2 的幂 */
    CHECK(spec_analyze(&W, X, 32, 1000.0f, SPEC_WIN_RECT, true, &r) == DZ_EINVAL);    /* 太短 */
    CHECK(spec_analyze(&W, X, 64, 0.0f, SPEC_WIN_RECT, true, &r) == DZ_EINVAL);
    X[3] = NAN;
    CHECK(spec_analyze(&W, X, 64, 1000.0f, SPEC_WIN_RECT, true, &r) == DZ_EINVAL);
    X[3] = 0;
    CHECK(spec_analyze(&W, X, 64, 1000.0f, SPEC_WIN_RECT, true, &r) == DZ_OK);
    CHECK(r.peak_bin == 0 && r.ncomp == 0); CHECK(isnan(spec_thd(&W, &r, 5)));
    CHECK(spectrum_selftest() == DZ_OK);
}

TEST(sigfilt_median_and_kalman)
{
    med3_t m = { 0 };
    int32_t in[] = { 10, 10, 500, 10, 10, 50, 50, 50 }, out[8];
    for (int i = 0; i < 8; i++) out[i] = med3_update(&m, in[i]);
    CHECK(out[2] == 10 && out[3] == 10);          /* 单点毛刺去掉 */
    CHECK(out[6] == 50);                          /* 阶跃只晚 1 个样本 */
    CHECK(med3_of(3, 1, 2) == 2 && med3_of(-5, 7, 7) == 7);

    kf1_t k; kf1_cfg_t c = { 0.001f, 0.25f, 1.0f };
    CHECK(kf1_init(&k, &c) == DZ_OK);
    unsigned s = 12345u; double se_in = 0, se_out = 0; float y = 0;
    for (int i = 0; i < 2000; i++) {
        s = s * 1103515245u + 12345u;
        float n = ((float)((s >> 8) & 0xFFFF) / 65535.0f - 0.5f) * 1.732f;   /* 方差 0.25 的均匀噪声 */
        kf1_update(&k, 3.0f + n, &y);
        if (i > 500) { se_in += n * n; se_out += (y - 3.0) * (y - 3.0); }
    }
    CHECK(se_out < se_in * 0.1);
    float g = kf1_steady_gain(&c);
    CHECK_NEAR(g, 0.0613, 0.002);                 /* P⁻=0.5(Q+√(Q²+4QR)) = 0.01631 → K = 0.0613 */
    float x0 = k.x;
    CHECK(kf1_update(&k, NAN, &y) == DZ_EINVAL); CHECK(k.x == x0);
    kf1_cfg_t bad = { 0.01f, 0.0f, 1.0f };
    CHECK(kf1_init(&k, &bad) == DZ_EINVAL);
    CHECK(sigfilt_selftest() == DZ_OK);
}

TEST(dds_freq_and_spectrum)
{
    dds_t d; dds_cfg_t c = { 51200u, 0, 4095, false };
    CHECK(dds_init(&d, &c) == DZ_OK);
    CHECK(dds_set(&d, DDS_SINE, 1000000u, 0.0f) == DZ_OK);             /* 1 kHz */
    CHECK(dds_actual_mhz(&d) >= 999999u && dds_actual_mhz(&d) <= 1000001u);
    static uint16_t buf[512];
    dds_fill(&d, buf, 512);
    for (int i = 0; i < 512; i++) X[i] = buf[i];
    spec_result_t r;
    spec_analyze(&W, X, 512, 51200.0f, SPEC_WIN_RECT, true, &r);
    CHECK_NEAR(r.peak_hz, 1000.0, 1.0); CHECK_NEAR(r.peak_mag, 2047.5, 10.0); CHECK_NEAR(r.dc, 2047.5, 5.0);
    /* 起始相位 90° → 第一个样本在峰值 */
    dds_set(&d, DDS_SINE, 1000000u, 90.0f); CHECK(dds_next(&d) >= 4090u);
    /* 方波整数半周期：fs=51200，f=3000 → 半周期 round(51200/6000)=9 点 → 实际 2844.444 Hz，每周期一样 */
    dds_cfg_t cq = { 51200u, 100, 900, true };
    dds_init(&d, &cq); CHECK(dds_set(&d, DDS_SQUARE, 3000000u, 0.0f) == DZ_OK);
    CHECK(dds_actual_mhz(&d) == 2844444u);
    int hi = 0; for (int i = 0; i < 18; i++) hi += dds_next(&d) == 900u;
    CHECK(hi == 9);
    CHECK(dds_set(&d, DDS_SINE, 25600001u, 0.0f) == DZ_EINVAL);        /* 超奈奎斯特 */
    CHECK(dds_set(&d, DDS_SINE, 0u, 0.0f) == DZ_EINVAL);
    CHECK(dds_selftest() == DZ_OK);
}

TEST(capfreq_wrap_duty_timeout)
{
    capfreq_t c; capfreq_cfg_t cfg = { 1000000u, 65536u, 8u, 50u };
    CHECK(capfreq_init(&c, &cfg) == DZ_OK);
    /* 1234.5 Hz、占空比 30%，1 MHz 计数 16 位回绕：真实边沿时刻量化到整 tick */
    double T = 1e6 / 1234.5; uint32_t f = 0; float du = 0;
    for (int i = 0; i <= 64; i++) {
        uint32_t tr = (uint32_t)llround(i * T), tf = (uint32_t)llround(i * T + 0.3 * T);
        capfreq_edge(&c, tr % 65536u, true, (uint32_t)(tr / 1000)); capfreq_edge(&c, tf % 65536u, false, (uint32_t)(tf / 1000));
    }
    CHECK(capfreq_read(&c, 52, &f, &du));
    CHECK_NEAR(f, 1234500.0, 1234.5 * 1000 * 1.0 / (8 * T) * 1.5);     /* ±1 tick / 8 周期 */
    CHECK_NEAR(du, 0.30, 0.002);
    CHECK(c.seq == 8);
    CHECK(!capfreq_read(&c, 52 + 51, &f, &du));                         /* 断信号 */
    /* 只喂上升沿：有频率，占空比 NAN */
    capfreq_init(&c, &cfg);
    for (int i = 0; i <= 8; i++) capfreq_edge(&c, (uint32_t)(i * 2000u), true, (uint32_t)i * 2u);
    CHECK(capfreq_read(&c, 17, &f, &du)); CHECK(f == 500000u); CHECK(isnan(du));
    CHECK(capfreq_init(&c, &(capfreq_cfg_t){ 0u, 0u, 8u, 50u }) == DZ_EINVAL);
    CHECK(capfreq_selftest() == DZ_OK);
}

/* 菜单：用字符数组当屏幕 */
static char SCR[4][32];
static void v_clear(void *ctx) { (void)ctx; memset(SCR, 0, sizeof SCR); }
static void v_line(void *ctx, uint8_t row, const char *t, bool sel) { (void)ctx; (void)sel; if (row < 4) strncpy(SCR[row], t, 31); }
static int hits;
static void act(void *ctx) { hits += *(int *)ctx; }

TEST(menu_nav_scroll_edit)
{
    static int one = 1;
    static float kp = 1.0f;
    static const menu_item_t pid_items[] = { { "Kp", NULL, NULL, NULL, &kp, 0.5f, 0.0f, 2.0f } };
    static const menu_page_t pid = { "PID", pid_items, 1 };
    static const menu_item_t root_items[] = {
        { "Start", NULL, act, &one, NULL, 0, 0, 0 }, { "PID", &pid, NULL, NULL, NULL, 0, 0, 0 },
        { "Item3", NULL, NULL, NULL, NULL, 0, 0, 0 }, { "Item4", NULL, NULL, NULL, NULL, 0, 0, 0 },
        { "AVeryLongLabelThatGetsCut", NULL, NULL, NULL, NULL, 0, 0, 0 },
    };
    static const menu_page_t root = { "Main menu", root_items, 5 };
    menu_view_t v = { 4, 12, v_clear, v_line, NULL, NULL };                /* 4 行：标题 + 3 条 */
    menu_t m;
    CHECK(menu_init(&m, &root, &v) == DZ_OK);
    menu_render(&m);
    CHECK(strcmp(SCR[0], "Main menu") == 0 && strcmp(SCR[1], ">Start") == 0 && strcmp(SCR[2], " PID >") == 0);
    CHECK(menu_input(&m, MENU_IN_OK) && hits == 1);
    CHECK(menu_input(&m, MENU_IN_UP));                                    /* 循环到最后一项，窗口滚到底 */
    menu_render(&m);
    CHECK(strcmp(SCR[1], " Item3") == 0 && strcmp(SCR[3], ">AVeryLongLa") == 0);
    menu_input(&m, MENU_IN_DOWN); menu_input(&m, MENU_IN_DOWN);           /* 回到 PID */
    CHECK(menu_input(&m, MENU_IN_OK) && menu_depth(&m) == 2);
    CHECK(menu_input(&m, MENU_IN_OK) && m.editing);                       /* 进入编辑 */
    menu_input(&m, MENU_IN_UP); menu_input(&m, MENU_IN_UP); menu_input(&m, MENU_IN_UP);
    CHECK_NEAR(kp, 2.0, 1e-6);                                            /* 上限 */
    menu_input(&m, MENU_IN_DOWN);
    menu_render(&m);
    CHECK(strcmp(SCR[1], "*Kp 1.5") == 0);
    CHECK(menu_input(&m, MENU_IN_BACK) && !m.editing && menu_depth(&m) == 2);
    CHECK(menu_input(&m, MENU_IN_BACK) && menu_depth(&m) == 1);
    CHECK(!menu_back(&m));
    CHECK(menu_goto(&m, &pid) && menu_depth(&m) == 2 && menu_back(&m));
    static const menu_page_t orphan = { "x", NULL, 0 };
    CHECK(!menu_goto(&m, &orphan));
    /* 自己指自己的环：goto 找不到时不会无限递归；进子页到深度上限停下 */
    static menu_item_t loop_item = { "loop", NULL, NULL, NULL, NULL, 0, 0, 0 };
    static menu_page_t loop = { "loop", &loop_item, 1 };
    loop_item.sub = &loop;
    menu_init(&m, &loop, NULL);
    for (int i = 0; i < 10; i++) menu_select(&m);
    CHECK(menu_depth(&m) == MENU_MAX_DEPTH);
    CHECK(!menu_goto(&m, &orphan));
    CHECK(menu_selftest() == DZ_OK);
}

/* 键盘：host-sim 读钩子模拟矩阵——列 c 有效 ⇔ 某个按下的键 (r,c) 的行 r 当前被选中 */
static uint16_t held_phys;
static bool kp_matrix(pal_id_t id, const bool *g, void *ctx)
{
    (void)ctx;
    const pal_id_t R[4] = { RES_GPIO_KP_R0, RES_GPIO_KP_R1, RES_GPIO_KP_R2, RES_GPIO_KP_R3 };
    const pal_id_t C[4] = { RES_GPIO_KP_C0, RES_GPIO_KP_C1, RES_GPIO_KP_C2, RES_GPIO_KP_C3 };
    for (int c = 0; c < 4; c++) if (C[c] == id)
        for (int r = 0; r < 4; r++) if (g[R[r]] && (held_phys & (1u << (r * 4 + c)))) return true;
    return g[id];
}

TEST(keypad_scan_debounce)
{
    host_sim_reset();
    host_sim_gpio_read_hook(kp_matrix, NULL);
    keypad_t k; kp_event_t ev;
    kp_cfg_t c = { { RES_GPIO_KP_R0, RES_GPIO_KP_R1, RES_GPIO_KP_R2, RES_GPIO_KP_R3 },
                   { RES_GPIO_KP_C0, RES_GPIO_KP_C1, RES_GPIO_KP_C2, RES_GPIO_KP_C3 }, 30, 0 };
    CHECK(kp_init(&k, &c) == DZ_OK);
    uint16_t raw = 0;
    held_phys = 1u << 9;                                         /* 第 3 行第 2 列 = '8' */
    CHECK(kp_scan_raw(&k, &raw) == DZ_OK && raw == (1u << 9));
    CHECK(kp_char(kp_first(raw)) == '8');
    /* 抖动：按 10 ms、松 10 ms、再按——都不到 30 ms，不报 */
    int pressed = 0, released = 0;
    uint16_t pattern[] = { 1, 1, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0 };
    for (unsigned i = 0; i < sizeof pattern / sizeof pattern[0]; i++) {
        held_phys = pattern[i] ? (1u << 15) : 0;                 /* 'D' */
        kp_process(&k, 10, &ev);
        if (ev.pressed) { pressed++; CHECK(kp_char(kp_first(ev.pressed)) == 'D'); }
        if (ev.released) released++;
    }
    CHECK(pressed == 1 && released == 1);
    held_phys = (1u << 0) | (1u << 5);                           /* '1' + '5' 同按 */
    for (int i = 0; i < 5; i++) kp_process(&k, 10, &ev);
    CHECK(ev.held == ((1u << 0) | (1u << 5)));
    host_sim_gpio_read_hook(NULL, NULL);
    CHECK(kp_char(16) == '\0' && kp_first(0) == KP_NONE);
    CHECK(keypad4x4_selftest() == DZ_OK);
}

static uint16_t U[1024], V[1024];

static wm_type_t wm_type_of(const uint16_t *x, uint32_t n, float fs, wm_result_t *r)
{
    static float F[1024];
    spec_result_t sp;
    for (uint32_t i = 0; i < n; i++) F[i] = x[i];
    CHECK(spec_analyze(&W, F, (uint16_t)n, fs, SPEC_WIN_HANN, true, &sp) == DZ_OK);
    CHECK(wm_measure(x, n, fs, 3.3f / 4095.0f, &sp, r) == DZ_OK);
    return r->type;
}

TEST(wavemeas_levels_freq_type)
{
    wm_result_t r;
    const float fs = 10000.0f;                                     /* 123.4 Hz，非整周期 */
    for (int i = 0; i < 1024; i++) U[i] = (uint16_t)lround(2048 + 1000 * sin(2 * M_PI * 123.4 * i / fs));
    CHECK(wm_type_of(U, 1024, fs, &r) == WM_SINE);
    CHECK_NEAR(r.freq_hz, 123.4, 0.6);
    CHECK_NEAR(r.pp_v, 2000 * 3.3 / 4095, 0.01);
    CHECK_NEAR(r.avg_v, 2048 * 3.3 / 4095, 0.02);
    CHECK_NEAR(r.rms_ac_v, 1000 / sqrt(2.0) * 3.3 / 4095, 0.01);  /* 正弦有效值 = A/√2 */
    CHECK_NEAR(r.duty, 0.5, 0.02);
    for (int i = 0; i < 1024; i++) U[i] = (i % 80) < 20 ? 3500 : 500;   /* 125 Hz、占空比 25% 方波 */
    wm_type_of(U, 1024, fs, &r);                                   /* 原版分类按均值算峰值因数，非 50% 方波不归 SQUARE（照原版） */
    CHECK_NEAR(r.freq_hz, 125.0, 0.3); CHECK_NEAR(r.duty, 0.25, 0.005); CHECK(r.edges == 12);
    for (int i = 0; i < 1024; i++) U[i] = (i % 80) < 40 ? 3500 : 500;   /* 50% 方波 */
    CHECK(wm_type_of(U, 1024, fs, &r) == WM_SQUARE);
    CHECK_NEAR(r.duty, 0.5, 0.005);
    for (int i = 0; i < 1024; i++) { int k = i % 100; U[i] = (uint16_t)(500 + (k < 50 ? k : 100 - k) * 60); }  /* 三角 100 Hz */
    CHECK(wm_type_of(U, 1024, fs, &r) == WM_TRIANGLE);
    CHECK_NEAR(r.freq_hz, 100.0, 0.5);
    for (int i = 0; i < 1024; i++) U[i] = (uint16_t)(500 + (i % 100) * 30);   /* 锯齿 100 Hz */
    CHECK(wm_type_of(U, 1024, fs, &r) == WM_SAWTOOTH);
    CHECK_NEAR(r.freq_hz, 100.0, 0.5);
    for (int i = 0; i < 1024; i++) U[i] = (uint16_t)(1500 + (i & 3));          /* 峰峰 3 码 = 直流 */
    CHECK(wm_measure(U, 1024, fs, 0.0f, NULL, &r) == DZ_OK);
    CHECK(r.type == WM_DC && !(r.valid & WM_V_FREQ) && r.freq_hz == 0.0f);
    CHECK(wm_measure(U, 1, fs, 0.0f, NULL, &r) == DZ_EINVAL);
    CHECK(wm_measure(U, 1024, 0.0f, 0.0f, NULL, &r) == DZ_EINVAL);
    CHECK(wm_measure(NULL, 1024, fs, 0.0f, NULL, &r) == DZ_EINVAL);
    CHECK(wavemeas_selftest() == DZ_OK);
}

TEST(wavemeas_phase)
{
    const float fs = 20000.0f, f = 317.0f;                          /* 不落在 bin 上 */
    for (int i = 0; i < 512; i++) {
        double ph = 2 * M_PI * f * i / fs;
        U[i] = (uint16_t)lround(2000 + 800 * sin(ph));
        V[i] = (uint16_t)lround(1000 + 300 * sin(ph - 45.0 * M_PI / 180.0));    /* b 滞后 45° */
    }
    CHECK_NEAR(wm_phase_deg(U, V, 512, fs, f), -45.0, 1.0);
    CHECK_NEAR(wm_phase_deg(V, U, 512, fs, f), 45.0, 1.0);
    for (int i = 0; i < 512; i++) V[i] = 1234;
    CHECK(isnan(wm_phase_deg(U, V, 512, fs, f)));
    CHECK(isnan(wm_phase_deg(U, U, 512, fs, 0.0f)));
    CHECK(isnan(wm_phase_deg(U, U, 512, fs, 15000.0f)));
}

static void feed_sine(void *ctx)
{
    (void)ctx;
    double t = host_sim_now_us() * 1e-6;
    host_sim_adc_set(RES_ADC_LINE_A0, (uint16_t)lround(2048 + 1000 * sin(2 * M_PI * 50.0 * t)));
}

TEST(pal_adc_block_and_dac)
{
    host_sim_reset();
    CHECK(host_sim_add_periodic(HOST_SIM_STEP_US, feed_sine, NULL) >= 0);
    feed_sine(NULL);
    wm_result_t r;
    CHECK(pal_adc_block_read(RES_ADC_LINE_A0, U, 1000, 1000u) == DZ_OK);     /* 1 kHz 采 1 s */
    CHECK(wm_measure(U, 1000, 1000.0f, 0.0f, NULL, &r) == DZ_OK);
    CHECK_NEAR(r.freq_hz, 50.0, 0.2); CHECK_NEAR(r.pp_v, 2000, 5);
    CHECK(pal_adc_block_read(RES_ADC_LINE_A0, U, 10, 3000u) == DZ_EINVAL);    /* 周期 333.3 µs 不是整数 */
    CHECK(pal_adc_block_read(RES_ADC_LINE_A0, U, 10, PAL_ADC_BLOCK_MAX_HZ * 2u) == DZ_EINVAL);
    CHECK(pal_adc_block_read(RES_ADC_LINE_A0, NULL, 10, 1000u) == DZ_EINVAL);
    CHECK(pal_adc_block_read(BOARD_ADC_COUNT, U, 10, 1000u) == DZ_ENODEV);
    CHECK(pal_adc_block_read(RES_ADC_LINE_A0, U, 10, 20000u) == DZ_ETIMEOUT); /* 仿真步长 100 µs 跟不上 50 µs 周期 → 报迟到，不给假数据 */
    pal_dac_info_t di;
    CHECK(pal_dac_info(RES_DAC_WAVE, &di) == DZ_OK && di.bits == 12 && di.vref_mv == 3300);
    CHECK(pal_dac_write(RES_DAC_WAVE, 4095) == DZ_OK && host_sim_dac_get(RES_DAC_WAVE) == 4095);
    CHECK(pal_dac_write(RES_DAC_WAVE, 4096) == DZ_EINVAL && host_sim_dac_get(RES_DAC_WAVE) == 4095);
    CHECK(pal_dac_write(BOARD_DAC_COUNT, 1) == DZ_ENODEV);
    host_sim_reset();
}

void suite_signal(void)
{
    printf("[signal]\n");
    RUN(spectrum_tone_and_interp); RUN(spectrum_components_sorted); RUN(spectrum_phase_and_thd); RUN(spectrum_rejects);
    RUN(sigfilt_median_and_kalman); RUN(dds_freq_and_spectrum); RUN(capfreq_wrap_duty_timeout);
    RUN(wavemeas_levels_freq_type); RUN(wavemeas_phase); RUN(pal_adc_block_and_dac);
    RUN(menu_nav_scroll_edit); RUN(keypad_scan_debounce);
}
