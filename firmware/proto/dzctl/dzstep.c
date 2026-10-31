/**
 * @file dzstep.c
 * @brief 见 dzstep.h。在线指标，O(1) 内存；口径与 tools/step_metrics.py（测试参考实现）一致。
 */
#include "dzstep.h"
#include <math.h>
#include <string.h>

uint32_t dzctl_crc32(const void *data, uint32_t len)
{
    const uint8_t *p = (const uint8_t *)data;
    uint32_t c = 0xFFFFFFFFu;
    while (len--) {
        c ^= *p++;
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return c ^ 0xFFFFFFFFu;
}

uint32_t dzctl_params_crc32(const dzctl_table_t *t)
{
    uint32_t c = 0xFFFFFFFFu;
    for (uint8_t i = 0; t && i < t->n; i++) {
        float v = dzctl_get(t, i);
        uint32_t w; memcpy(&w, &v, 4);
        for (int b = 0; b < 4; b++) {             /* little-endian，与主机字节序无关 */
            c ^= (w >> (8 * b)) & 0xFFu;
            for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
        }
    }
    return c ^ 0xFFFFFFFFu;
}

static bool finitef_(float v) { return v == v && v <= 3.4e38f && v >= -3.4e38f; }

uint8_t dzctl_param_check(const dzctl_table_t *t, uint8_t i, float v, bool locked)
{
    const dzctl_param_t *d = &t->desc[i];
    if (!finitef_(v)) return DZSTEP_REJ_TYPE;
    if (d->type != DZCTL_F32 && floorf(v) != v) return DZSTEP_REJ_TYPE;           /* 整型 / bool 只收整数 */
    if (d->type == DZCTL_BOOL && v != 0.0f && v != 1.0f) return DZSTEP_REJ_TYPE;
    if (locked) return DZSTEP_REJ_STATE;
    if (v < d->min || v > d->max) return DZSTEP_REJ_RANGE;
    if (d->max_delta > 0.0f && fabsf(v - dzctl_get(t, i)) > d->max_delta * (1.0f + 1e-6f)) return DZSTEP_REJ_STEP;
    return 0u;
}

void dzstep_reject_frame(const dzctl_table_t *t, uint8_t i, uint8_t reason, float req, dzframe_t *out)
{
    memset(out, 0, sizeof *out);
    out->kind = DZF_DATA; out->id = DZSTEP_REJECT_ID;
    (void)(dzframe_put_u8(out, i) && dzframe_put_u8(out, reason) && dzframe_put_f32(out, req) && dzframe_put_f32(out, dzctl_get(t, i)));
    const char *nm = t->desc[i].name;
    for (unsigned k = 0; nm && nm[k] && k < 16u; k++) (void)dzframe_put_u8(out, (uint8_t)nm[k]);
}

bool dzctl_handle_checked(const dzctl_table_t *t, const dzframe_t *in, bool locked, dzframe_t *ack, dzframe_t *rej, bool *has_rej)
{
    *has_rej = false;
    if (!in || in->kind != DZF_PARAM_SET) return false;
    if (!t || in->id >= t->n || in->len != 4u) return dzctl_handle(t, in, ack);   /* 读 / 序号错 / 长度错：同旧行为 */
    float v = dzframe_get_f32(in, 0);
    uint8_t r = dzctl_param_check(t, in->id, v, locked);
    if (r == 0u) return dzctl_handle(t, in, ack);                                  /* 已校验在界内：dzctl_set 不会再限幅 */
    memset(ack, 0, sizeof *ack);
    ack->kind = DZF_PARAM_ACK; ack->id = in->id; ack->seq = in->seq;
    (void)(dzframe_put_u8(ack, DZCTL_REJECTED) && dzframe_put_f32(ack, dzctl_get(t, in->id)));
    dzstep_reject_frame(t, in->id, r, v, rej);
    rej->seq = in->seq;
    *has_rej = true;
    return true;
}

uint8_t dzstep_parse(const dzframe_t *f, uint8_t n_ch, uint8_t *ch, uint16_t *iter, float *target, uint32_t *dur)
{
    *ch = 0; *iter = 0; *target = 0.0f; *dur = 0;
    if (f->len == 0u) return 0xFFu;
    if (f->len != DZSTEP_START_LEN) return DZSTEP_ST_BAD_ARG;
    *ch = f->payload[0];
    *iter = (uint16_t)(f->payload[2] | (f->payload[3] << 8));
    *target = dzframe_get_f32(f, 4);
    *dur = dzframe_get_u32(f, 8);
    if (n_ch == 0u) return DZSTEP_ST_UNSUPPORTED;
    if (*ch >= n_ch || !finitef_(*target) || *dur < DZSTEP_DUR_MIN_MS || *dur > DZSTEP_DUR_MAX_MS) return DZSTEP_ST_BAD_ARG;
    return DZSTEP_ST_STARTED;
}

void dzstep_ack(uint8_t status, uint8_t ch, uint16_t iter, uint8_t seq, dzframe_t *out)
{
    memset(out, 0, sizeof *out);
    out->kind = DZF_DATA; out->id = DZSTEP_ID; out->seq = seq;
    (void)(dzframe_put_u8(out, status) && dzframe_put_u8(out, ch) && dzframe_put_u16(out, iter));
}

void dzstep_begin(dzstep_t *s, const dzstep_ch_t *c, uint8_t ch, uint16_t iter, float sp, uint32_t dur, uint32_t t0, uint32_t hash, float u_max)
{
    memset(s, 0, sizeof *s);
    s->active = true; s->ch = ch; s->iter = iter; s->sp = sp; s->dur = dur; s->t0 = t0; s->hash = hash;
    s->u_max = u_max; s->umax_r = c->range; s->band = c->abs_tol;   /* 暂存 range / abs_tol，第一个样本时定口径 */
    s->rise10 = s->rise90 = DZSTEP_NONE;
}

bool dzstep_sample(dzstep_t *s, uint32_t t, float y, float u)
{
    if (!s->active) return false;
    uint32_t dt = t - s->t0;
    if (dt > s->dur) return true;
    float e = s->sp - y, ae = fabsf(e);
    if (s->n == 0u) {
        float range = s->umax_r, tol = s->band, amp;
        s->y0 = y; amp = fabsf(s->sp - y);
        float thr = 0.01f * range > tol ? 0.01f * range : tol;
        s->mode = amp < thr ? 1u : 0u;
        s->band = s->mode ? tol : 0.02f * amp;
        s->maxr = -1e30f;
    }
    s->n++;
    if (ae > s->peak) s->peak = ae;
    if (s->mode == 0u) {
        float r = (y - s->y0) / (s->sp - s->y0);
        if (r > s->maxr) s->maxr = r;
        if (s->rise10 == DZSTEP_NONE && r >= 0.1f) s->rise10 = dt;
        if (s->rise90 == DZSTEP_NONE && r >= 0.9f) s->rise90 = dt;
    }
    if (ae > s->band) s->settle_pending = true;
    else if (s->settle_pending) { s->settle_pending = false; s->settle_t = dt; }
    if (5u * (uint64_t)dt >= 4u * (uint64_t)s->dur) { s->n_ss++; s->ss_sum += ae; }
    if (u == u) { s->n_u++; if (s->u_max > 0.0f && fabsf(u) >= 0.99f * s->u_max) s->n_sat++; }
    return dt >= s->dur;
}

void dzstep_finish(dzstep_t *s, bool aborted, uint8_t cause, uint8_t seq, dzframe_t *out)
{
    float amp = fabsf(s->sp - s->y0), os, ss, usat;
    uint32_t rise, settle;
    if (s->mode == 0u && s->n) {
        os = s->maxr > 1.0f ? (s->maxr - 1.0f) * 100.0f : 0.0f;
        ss = s->n_ss ? s->ss_sum / (float)s->n_ss / amp * 100.0f : -1.0f;
        rise = (s->rise10 != DZSTEP_NONE && s->rise90 != DZSTEP_NONE) ? s->rise90 - s->rise10 : DZSTEP_NONE;
    } else {
        os = s->peak;
        ss = s->n_ss ? s->ss_sum / (float)s->n_ss : -1.0f;
        rise = DZSTEP_NONE;
    }
    settle = s->n == 0u || s->settle_pending ? DZSTEP_NONE : s->settle_t;
    usat = s->n_u ? (float)s->n_sat / (float)s->n_u : -1.0f;
    memset(out, 0, sizeof *out);
    out->kind = DZF_DATA; out->id = DZSTEP_ID; out->seq = seq;
    (void)(dzframe_put_u8(out, DZSTEP_PROTO) && dzframe_put_u8(out, s->mode) && dzframe_put_u8(out, aborted ? 1u : 0u)
        && dzframe_put_u8(out, aborted ? cause : 0u) && dzframe_put_u16(out, s->iter) && dzframe_put_u16(out, s->n)
        && dzframe_put_u32(out, s->hash) && dzframe_put_u32(out, s->t0) && dzframe_put_f32(out, s->sp)
        && dzframe_put_f32(out, s->y0) && dzframe_put_f32(out, os) && dzframe_put_u32(out, rise)
        && dzframe_put_u32(out, settle) && dzframe_put_f32(out, ss) && dzframe_put_f32(out, usat)
        && dzframe_put_f32(out, s->peak) && dzframe_put_f32(out, s->n ? s->band : 0.0f)
        && dzframe_put_u8(out, s->ch) && dzframe_put_u8(out, 0u) && dzframe_put_u16(out, 0u));
    s->active = false;
}

int dzstep_selftest(void)
{
    int fail = 0;
    fail += dzctl_crc32("123456789", 9) != 0xCBF43926u;
    dzstep_ch_t c = { 0, 100.0f, 0.5f, 1.0f, -1 };
    dzstep_t s; dzframe_t f;
    dzstep_begin(&s, &c, 0, 3, 10.0f, 1000, 100, 0x1234u, 1.0f);
    for (uint32_t t = 100; t <= 1100; t += 10) {
        float k = (float)(t - 100) / 1000.0f, y = k < 0.5f ? 22.0f * k : 10.0f;
        (void)dzstep_sample(&s, t, y, k < 0.3f ? 1.0f : 0.2f);
    }
    dzstep_finish(&s, false, 0, 0, &f);
    fail += f.len != DZSTEP_RESULT_LEN || dzframe_get_u16(&f, 6) != 101u || dzframe_get_u8(&f, 1) != 0u;
    fail += fabsf(dzframe_get_f32(&f, 24) - 7.8f) > 0.05f;      /* 峰值 0.49·22 = 10.78 → 超调 7.8% */
    fail += fabsf(dzframe_get_f32(&f, 40) - 0.2970f) > 0.01f;   /* u=1 的样本 30/101 */
    return fail;
}
