#include "mtspeed.h"
#include <math.h>

dz_err_t mtspeed_init(mtspeed_t *m, const mtspeed_cfg_t *cfg)
{
    if (m == 0 || cfg == 0) return DZ_EINVAL;
    if (!(cfg->counts_per_rev > 0.0f) || !isfinite(cfg->counts_per_rev) || cfg->timeout_us == 0u) return DZ_EINVAL;
    m->cfg = *cfg;
    m->gen = 0u; m->count = 0; m->t_last = 0u; m->any = false;
    m->count_ref = 0; m->t_ref = 0u; m->have_ref = false; m->stopped = false;
    m->rps = 0.0f; m->ready = true;
    return DZ_OK;
}

void mtspeed_edge(mtspeed_t *m, uint32_t t_us, int8_t dir)
{
    if (m == 0 || !m->ready) return;
    m->gen = m->gen + 1u;
    m->count = m->count + (dir < 0 ? -1 : 1);
    m->t_last = t_us;
    m->any = true;
    m->gen = m->gen + 1u;
}

void mtspeed_poll(mtspeed_t *m, uint32_t now_us)
{
    if (m == 0 || !m->ready) return;
    int32_t c; uint32_t tl; bool any; uint32_t g0, g1;
    do {                                   /* 版本号双读：中间被边沿中断打断就重读 */
        g0 = m->gen; c = m->count; tl = m->t_last; any = m->any; g1 = m->gen;
    } while (g0 != g1 || (g0 & 1u));
    if (!any) { m->rps = 0.0f; return; }
    if (!m->have_ref) {                    /* 第一个边沿只当起点 */
        m->count_ref = c; m->t_ref = tl; m->have_ref = true; m->rps = 0.0f;
        return;
    }
    int32_t dm = c - m->count_ref;
    uint32_t since = now_us - tl;
    if (since > m->cfg.timeout_us) {       /* 停了：清零，并把起点挪到最后一个边沿 */
        m->rps = 0.0f; m->count_ref = c; m->t_ref = tl; m->stopped = true;
        return;
    }
    if (dm != 0 && m->stopped) {          /* 停后重新起步：这一拍只建立起点 */
        m->count_ref = c; m->t_ref = tl; m->stopped = false;
        return;
    }
    if (dm != 0) {
        uint32_t T = tl - m->t_ref;
        if (T > 0u) m->rps = ((float)dm / m->cfg.counts_per_rev) / ((float)T * 1e-6f);
        m->count_ref = c; m->t_ref = tl;
    } else if (since > 0u) {               /* 没新边沿：速度不可能超过 1 个边沿 / since */
        float cap = (1.0f / m->cfg.counts_per_rev) / ((float)since * 1e-6f);
        if (fabsf(m->rps) > cap) m->rps = (m->rps > 0.0f) ? cap : -cap;
    }
}

float mtspeed_rps(const mtspeed_t *m) { return (m != 0 && m->ready) ? m->rps : 0.0f; }

dz_err_t mtspeed_selftest(void)
{
    mtspeed_t m; mtspeed_cfg_t c = { 10.0f, 200000u };
    if (mtspeed_init(&m, &c) != DZ_OK) return DZ_EFAIL;
    /* 每 25 ms 一个边沿 = 40 边沿/s = 4 rps；1 ms 轮询 */
    uint32_t te = 0u;
    for (uint32_t t = 0u; t <= 200000u; t += 1000u) {
        if (t == te) { mtspeed_edge(&m, t, 1); te += 25000u; }
        mtspeed_poll(&m, t);
    }
    return fabsf(mtspeed_rps(&m) - 4.0f) < 0.01f ? DZ_OK : DZ_EFAIL;
}
