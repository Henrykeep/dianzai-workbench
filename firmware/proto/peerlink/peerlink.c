/* 两车状态链路，见 peerlink.h。 */
#include <math.h>
#include <string.h>
#include "peerlink.h"

void peerlink_state_frame(const peer_state_t *s, dzframe_t *out)
{
    memset(out, 0, sizeof *out);
    out->kind = DZF_DATA; out->id = PEERLINK_ID_STATE;
    (void)dzframe_put_u32(out, s->t_ms);
    (void)dzframe_put_f32(out, s->s_m); (void)dzframe_put_f32(out, s->v_mps);
    (void)dzframe_put_f32(out, s->x_m); (void)dzframe_put_f32(out, s->y_m); (void)dzframe_put_f32(out, s->yaw_rad);
    (void)dzframe_put_u16(out, s->flags);
}

void peerlink_abort_frame(uint16_t reason, dzframe_t *out)
{
    memset(out, 0, sizeof *out);
    out->kind = DZF_DATA; out->id = PEERLINK_ID_ABORT;
    (void)dzframe_put_u16(out, reason);
}

void peer_rx_init(peer_rx_t *r, uint32_t stale_ms)
{
    memset(r, 0, sizeof *r);
    r->stale_ms = stale_ms;
}

bool peer_rx_feed(peer_rx_t *r, const dzframe_t *f, uint32_t now_ms)
{
    if (f->kind != DZF_DATA) return false;
    if (f->id == PEERLINK_ID_ABORT) {
        if (f->len >= 2u) { r->aborted = true; r->abort_reason = dzframe_get_u16(f, 0); }
        else r->bad_len++;
        return true;
    }
    if (f->id != PEERLINK_ID_STATE) return false;
    if (f->len != PEERLINK_STATE_LEN) { r->bad_len++; return true; }
    if (r->have) {
        uint8_t d = (uint8_t)(f->seq - r->last_seq);
        if (d == 0u || d > 127u) { r->dup_ooo++; return true; }
    }
    {
        peer_state_t s;
        s.t_ms = dzframe_get_u32(f, 0);
        s.s_m = dzframe_get_f32(f, 4); s.v_mps = dzframe_get_f32(f, 8);
        s.x_m = dzframe_get_f32(f, 12); s.y_m = dzframe_get_f32(f, 16); s.yaw_rad = dzframe_get_f32(f, 20);
        s.flags = dzframe_get_u16(f, 24);
        if (!isfinite(s.s_m) || !isfinite(s.v_mps)) { r->bad_len++; return true; }
        r->last = s;
    }
    r->have = true; r->last_seq = f->seq; r->rx_ms = now_ms; r->good++;
    return true;
}

uint32_t peer_rx_age_ms(const peer_rx_t *r, uint32_t now_ms) { return r->have ? (uint32_t)(now_ms - r->rx_ms) : UINT32_MAX; }
bool peer_rx_fresh(const peer_rx_t *r, uint32_t now_ms) { return r->have && !r->aborted && peer_rx_age_ms(r, now_ms) <= r->stale_ms; }
void peer_rx_clear_abort(peer_rx_t *r) { r->aborted = false; r->abort_reason = 0; }

dz_err_t peerlink_selftest(void)
{
    peer_rx_t r; dzframe_t f, g; dzframe_parser_t p;
    peer_state_t s = { 1234u, 2.5f, 0.4f, 1.0f, -1.0f, 0.1f, PEER_F_RUNNING };
    uint8_t buf[DZFRAME_MAX_FRAME]; size_t n, i;
    int fail = 0; bool got = false;
    peer_rx_init(&r, 300u);
    peerlink_state_frame(&s, &f); f.seq = 5;
    fail += f.len != PEERLINK_STATE_LEN;
    n = dzframe_encode(buf, sizeof buf, &f);                   /* 过一遍真实编码/解析 */
    dzframe_parser_init(&p);
    for (i = 0; i < n; i++) got = dzframe_feed(&p, buf[i], &g) || got;
    fail += !got || !peer_rx_feed(&r, &g, 100u) || !peer_rx_fresh(&r, 100u) || r.last.s_m != 2.5f || r.last.flags != PEER_F_RUNNING;
    fail += !peer_rx_feed(&r, &g, 150u) || r.dup_ooo != 1u || r.rx_ms != 100u;          /* 重复帧丢 */
    g.seq = 4; (void)peer_rx_feed(&r, &g, 160u); fail += r.dup_ooo != 2u;            /* 乱序丢 */
    g.seq = 6; (void)peer_rx_feed(&r, &g, 200u); fail += r.good != 2u;
    fail += peer_rx_fresh(&r, 501u) || !peer_rx_fresh(&r, 500u);                     /* 300 ms 超时 */
    peerlink_abort_frame(7u, &f); (void)peer_rx_feed(&r, &f, 210u);
    fail += !r.aborted || r.abort_reason != 7u || peer_rx_fresh(&r, 210u);
    peer_rx_clear_abort(&r); fail += !peer_rx_fresh(&r, 210u);
    f.id = 0x10; fail += peer_rx_feed(&r, &f, 0);                                   /* 别人的帧不吃 */
    return fail ? DZ_EINVAL : DZ_OK;
}
