#include <math.h>
#include <string.h>
#include "dzimu.h"

bool dzimu_encode(const dzimu_sample_t *s, uint8_t seq, dzframe_t *f)
{
    if (!s || !f) return false;
    memset(f, 0, sizeof *f);
    f->kind = DZF_DATA; f->id = DZIMU_CH; f->seq = seq;
    bool ok = dzframe_put_u32(f, s->t_ms);
    for (int i = 0; i < 3; i++) ok = ok && dzframe_put_f32(f, s->acc[i]);
    for (int i = 0; i < 3; i++) ok = ok && dzframe_put_f32(f, s->gyr[i]);
    ok = ok && dzframe_put_f32(f, s->roll_deg) && dzframe_put_f32(f, s->pitch_deg) && dzframe_put_u8(f, s->status);
    return ok && f->len == DZIMU_SIZE;
}

bool dzimu_decode(const dzframe_t *f, dzimu_sample_t *out)
{
    if (!f || !out || f->kind != DZF_DATA || f->id != DZIMU_CH || f->len != DZIMU_SIZE) return false;
    dzimu_sample_t s;
    s.t_ms = dzframe_get_u32(f, 0);
    for (int i = 0; i < 3; i++) s.acc[i] = dzframe_get_f32(f, 4u + 4u * (unsigned)i);
    for (int i = 0; i < 3; i++) s.gyr[i] = dzframe_get_f32(f, 16u + 4u * (unsigned)i);
    s.roll_deg = dzframe_get_f32(f, 28); s.pitch_deg = dzframe_get_f32(f, 32);
    s.status = dzframe_get_u8(f, 36);
    for (int i = 0; i < 3; i++) if (!isfinite(s.acc[i]) || !isfinite(s.gyr[i])) return false;
    if (!isfinite(s.roll_deg) || !isfinite(s.pitch_deg)) return false;
    *out = s;
    return true;
}

float dzimu_axis(const float v[3], uint8_t axis)
{
    if (!v || axis > 5u) return NAN;
    float x = v[axis / 2u];
    return (axis & 1u) ? -x : x;
}

bool dzimu_linear_acc(const dzimu_sample_t *s, float out[3])
{
    if (!s || !out) return false;
    for (int i = 0; i < 3; i++) out[i] = s->acc[i];
    if (!(s->status & DZIMU_ST_ATT_OK)) return false;
    const float d2r = 0.017453293f;
    float r = s->roll_deg * d2r, p = s->pitch_deg * d2r;
    float sr = sinf(r), cr = cosf(r), sp = sinf(p), cp = cosf(p);
    out[0] -= DZIMU_G * -sp;
    out[1] -= DZIMU_G * sr * cp;
    out[2] -= DZIMU_G * cr * cp;
    return true;
}

dz_err_t dzimu_selftest(void)
{
    dzimu_sample_t a = { 1234u, { 0.1f, -0.2f, 9.8f }, { 0.01f, 0.02f, -0.03f }, 1.5f, -2.5f, 0x0Fu }, b;
    dzframe_t f;
    uint8_t buf[DZFRAME_MAX_FRAME];
    if (!dzimu_encode(&a, 7u, &f)) return DZ_EFAIL;
    size_t n = dzframe_encode(buf, sizeof buf, &f);
    dzframe_parser_t p; dzframe_t g; bool got = false;
    dzframe_parser_init(&p);
    for (size_t i = 0; i < n; i++) got = dzframe_feed(&p, buf[i], &g) || got;
    if (!got || !dzimu_decode(&g, &b)) return DZ_EFAIL;
    if (b.t_ms != a.t_ms || b.acc[2] != a.acc[2] || b.gyr[1] != a.gyr[1] || b.pitch_deg != a.pitch_deg || b.status != a.status) return DZ_EFAIL;
    if (dzimu_axis(a.acc, 3) != 0.2f || !isnan(dzimu_axis(a.acc, 6))) return DZ_EFAIL;
    /* 俯仰 10°、前向真实加速 0.5 m/s²：去重力后 x ≈ 0.5，y/z ≈ 0 */
    {
        float pr = 10.0f * 0.017453293f, l[3];
        dzimu_sample_t t = { 0u, { 0.5f - DZIMU_G * sinf(pr), 0.0f, DZIMU_G * cosf(pr) }, { 0 }, 0.0f, 10.0f, DZIMU_ST_ATT_OK };
        if (!dzimu_linear_acc(&t, l) || fabsf(l[0] - 0.5f) > 1e-3f || fabsf(l[1]) > 1e-3f || fabsf(l[2]) > 1e-3f) return DZ_EFAIL;
        t.status = 0u;
        if (dzimu_linear_acc(&t, l) || l[0] != t.acc[0]) return DZ_EFAIL;
    }
    return DZ_OK;
}
