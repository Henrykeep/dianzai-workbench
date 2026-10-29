/**
 * @file dzctl.c
 * @brief 见 dzctl.h。限幅与“回读生效值”的做法参考 MAVLink 参数协议（PARAM_SET → PARAM_VALUE 回传实际值）。
 */
#include "dzctl.h"
#include <string.h>
#include "dz_compiler.h"

DZ_STATIC_ASSERT(sizeof(float) == 4u, f32_is_4_bytes);

static void *field(const dzctl_table_t *t, uint8_t i) { return (uint8_t *)t->base + t->desc[i].offset; }

float dzctl_get(const dzctl_table_t *t, uint8_t i)
{
    if (!t || i >= t->n) return 0.0f;
    void *p = field(t, i);
    switch (t->desc[i].type) {
    case DZCTL_F32:  { float v;    memcpy(&v, p, sizeof v); return v; }
    case DZCTL_U32:  { uint32_t v; memcpy(&v, p, sizeof v); return (float)v; }
    case DZCTL_I32:  { int32_t v;  memcpy(&v, p, sizeof v); return (float)v; }
    case DZCTL_U16:  { uint16_t v; memcpy(&v, p, sizeof v); return (float)v; }
    case DZCTL_I16:  { int16_t v;  memcpy(&v, p, sizeof v); return (float)v; }
    case DZCTL_U8:   { uint8_t v;  memcpy(&v, p, sizeof v); return (float)v; }
    case DZCTL_BOOL: { bool v;     memcpy(&v, p, sizeof v); return v ? 1.0f : 0.0f; }
    default: return 0.0f;
    }
}

dzctl_status_t dzctl_set(const dzctl_table_t *t, uint8_t i, float v, float *applied)
{
    if (!t || i >= t->n) return DZCTL_BAD_ID;
    if (!(v == v) || v > 3.4e38f || v < -3.4e38f) return DZCTL_BAD_VALUE;   /* NaN / Inf */
    const dzctl_param_t *d = &t->desc[i];
    dzctl_status_t st = DZCTL_OK;
    if (v < d->min) { v = d->min; st = DZCTL_CLAMPED; }
    if (v > d->max) { v = d->max; st = DZCTL_CLAMPED; }
    void *p = field(t, i);
    float r = v >= 0.0f ? v + 0.5f : v - 0.5f;                              /* 整型四舍五入 */
    switch (d->type) {
    case DZCTL_F32:  memcpy(p, &v, sizeof v); break;
    case DZCTL_U32:  { uint32_t x = (uint32_t)r; memcpy(p, &x, sizeof x); } break;
    case DZCTL_I32:  { int32_t x = (int32_t)r;   memcpy(p, &x, sizeof x); } break;
    case DZCTL_U16:  { uint16_t x = (uint16_t)r; memcpy(p, &x, sizeof x); } break;
    case DZCTL_I16:  { int16_t x = (int16_t)r;   memcpy(p, &x, sizeof x); } break;
    case DZCTL_U8:   { uint8_t x = (uint8_t)r;   memcpy(p, &x, sizeof x); } break;
    case DZCTL_BOOL: { bool x = v >= 0.5f;       memcpy(p, &x, sizeof x); } break;
    default: return DZCTL_BAD_ID;
    }
    if (applied) *applied = dzctl_get(t, i);
    return st;
}

bool dzctl_handle(const dzctl_table_t *t, const dzframe_t *in, dzframe_t *ack)
{
    if (!in || !ack || in->kind != DZF_PARAM_SET) return false;
    float val = 0.0f;
    dzctl_status_t st;
    if (!t || in->id >= t->n) st = DZCTL_BAD_ID;
    else if (in->len == 0u) { st = DZCTL_OK; val = dzctl_get(t, in->id); }
    else if (in->len == 4u) {
        st = dzctl_set(t, in->id, dzframe_get_f32(in, 0), &val);
        if (st == DZCTL_BAD_VALUE) val = dzctl_get(t, in->id);
    } else st = DZCTL_BAD_LEN;
    memset(ack, 0, sizeof *ack);
    ack->kind = DZF_PARAM_ACK; ack->id = in->id; ack->seq = in->seq;
    (void)(dzframe_put_u8(ack, (uint8_t)st) && dzframe_put_f32(ack, val));
    return true;
}

bool dzctl_is_estop(const dzframe_t *f) { return f && f->kind == DZF_DATA && f->id == DZCTL_ID_ESTOP; }

void dzctl_heartbeat(const dzctl_table_t *t, uint8_t seq, dzframe_t *out)
{
    memset(out, 0, sizeof *out);
    out->kind = DZF_HEARTBEAT; out->seq = seq;
    (void)dzframe_put_u32(out, t ? t->schema_hash : 0u);
    (void)dzframe_put_u32(out, dzctl_board_uid());
    (void)dzframe_put_u32(out, dzctl_fw_rev());                 /* 0.4.0：第 3 个 u32，旧上位机不读 */
    (void)dzframe_put_u32(out, dzctl_status_word());            /* 0.5.0：第 4 个 u32 */
}

static volatile uint32_t s_status;
void dzctl_set_reset_cause(uint32_t cause) { s_status = (s_status & ~0xFFu) | (cause & 0xFFu); }
void dzctl_set_flags(uint32_t mask, bool on) { mask &= ~0xFFu; s_status = on ? (s_status | mask) : (s_status & ~mask); }
uint32_t dzctl_status_word(void) { return s_status; }

#ifndef DZ_FW_REV
#define DZ_FW_REV 0u
#endif
DZ_WEAK uint32_t dzctl_fw_rev(void) { return (uint32_t)(DZ_FW_REV); }

DZ_WEAK uint32_t dzctl_board_uid(void) { return 0u; }

void dzctl_wd_init(dzctl_wd_t *w, uint32_t timeout_ms) { w->last_ms = 0u; w->timeout_ms = timeout_ms; w->armed = false; }

void dzctl_wd_feed(dzctl_wd_t *w, const dzframe_t *f, uint32_t now_ms)
{
    if (!w || !f) return;
    if (f->kind == DZF_HEARTBEAT && f->len == 0u) w->armed = true;
    w->last_ms = now_ms;
}

bool dzctl_wd_expired(dzctl_wd_t *w, uint32_t now_ms)
{
    if (!w || !w->armed || w->timeout_ms == 0u || (uint32_t)(now_ms - w->last_ms) <= w->timeout_ms) return false;
    w->armed = false;
    return true;
}

int dzctl_selftest(void)
{
    typedef struct { float k; uint16_t n; bool on; } p_t;
    static const dzctl_param_t d[] = { { "k", 0, DZCTL_F32, -1.0f, 1.0f }, { "n", 4, DZCTL_U16, 0.0f, 100.0f },
                                       { "on", 6, DZCTL_BOOL, 0.0f, 1.0f } };
    p_t p = { 0.5f, 10u, false };
    dzctl_table_t t = { &p, d, 3u, 0x1234u };
    dzframe_t in, ack; int fail = 0; float v;
    fail += dzctl_set(&t, 0, 2.0f, &v) != DZCTL_CLAMPED || p.k != 1.0f;
    fail += dzctl_set(&t, 1, 41.6f, &v) != DZCTL_OK || p.n != 42u || v != 42.0f;
    fail += dzctl_set(&t, 2, 1.0f, &v) != DZCTL_OK || !p.on;
    fail += dzctl_set(&t, 3, 1.0f, &v) != DZCTL_BAD_ID;
    memset(&in, 0, sizeof in); in.kind = DZF_PARAM_SET; in.id = 0;
    dzctl_heartbeat(&t, 1u, &ack);
    fail += ack.kind != DZF_HEARTBEAT || ack.len != 16u || dzframe_get_u32(&ack, 0) != 0x1234u || dzframe_get_u32(&ack, 8) != dzctl_fw_rev();
    fail += !dzctl_handle(&t, &in, &ack) || ack.kind != DZF_PARAM_ACK || dzframe_get_u8(&ack, 0) != DZCTL_OK
            || dzframe_get_f32(&ack, 1) != 1.0f;
    {   /* status 字：复位原因只占低 8 位，标志不覆盖它 */
        uint32_t keep = s_status;
        dzctl_set_reset_cause(4u); dzctl_set_flags(DZCTL_HB_STALL | 0xFFu, true);
        fail += dzctl_status_word() != (4u | DZCTL_HB_STALL);
        dzctl_set_flags(DZCTL_HB_STALL, false);
        fail += dzctl_status_word() != 4u;
        s_status = keep;
    }
    {   /* 看门狗：未布防不触发；心跳布防后超时触发一次并撤防 */
        dzctl_wd_t w; dzframe_t hb, d2;
        memset(&hb, 0, sizeof hb); hb.kind = DZF_HEARTBEAT;
        memset(&d2, 0, sizeof d2); d2.kind = DZF_DATA;
        dzctl_wd_init(&w, 100u);
        dzctl_wd_feed(&w, &d2, 0u);
        fail += dzctl_wd_expired(&w, 1000u);
        dzctl_wd_feed(&w, &hb, 1000u); dzctl_wd_feed(&w, &d2, 1050u);
        fail += dzctl_wd_expired(&w, 1150u);
        fail += !dzctl_wd_expired(&w, 1151u);
        fail += dzctl_wd_expired(&w, 5000u);
    }
    return fail;
}
