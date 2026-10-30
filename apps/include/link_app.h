/**
 * @file link_app.h
 * @brief 应用侧 LINK 通用收发：参数读写 / 急停锁存 / 'R' 解除 / 单字节命令 / 心跳 / 上位机看门狗 / 遥测节拍。
 *        仿真被控对象（apps/motor_pos、pendulum_rot、pan_tilt、line_car）共用，题目代码只写控制律和遥测内容。只在应用的 app_main.c 里包含一次。
 *
 * 用法：
 *   static link_app_t L;
 *   link_app_init(&L, apply_params, on_cmd);          // 回调可为 NULL
 *   app_loop: if (link_app_poll(&L, now)) { link_telem_t t = {...}; link_app_send_telem(&L, &t); }
 *   急停：L.estop 为 true 时应用必须让输出归零（控制中断里读）。
 *   黑匣子：L.bb = &my_bb（可选）后，上位机“导出黑匣子”（DATA 0x7D len=0）由这里统一回 BB 帧。
 *   设定值约定：上位机 DATA id=1 = 1..4 个 f32 设定值（工作台阶跃 / 扫频实验就发它），存到 L.sp[]，L.sp_ms 为收到时刻。
 *   通用运行时（dz_runtime.h，dzctl 0.12.0）默认就有：上电从 flash 读参数（读到会调一次 on_params）、上电自检上报心跳
 *   （自检不过 → 急停锁存，原因 SELFTEST）、'W' 存参、'M' 切联机/脱机、'H' 重跑自检。应用自己的自检项在 link_app_init 之前
 *   dzctl_selftest_register 注册。L.still 可选（默认：急停或设定值全 0 时算停稳）。
 *   脱机模式：不要求上位机心跳、不收上位机设定值（L.sp[] 保持 0）；link_app_running(&L) 告诉应用脱机是否已按键启动。
 */
#ifndef LINK_APP_H
#define LINK_APP_H

#include "link_io.h"
#include "dzframe.h"
#include "dzctl.h"
#include "link_gen.h"
#include "dz_compiler.h"
#include "blackbox.h"
#include "link_relay.h"
#include "dz_runtime.h"

typedef struct {
    dzframe_parser_t rx;
    dzctl_wd_t wd;
    uint32_t last_tx, last_hb;
    uint8_t seq, bb_seq;
    bool hb_was_estop;
    volatile bool estop;                    /**< 输出禁止：锁存中，或 'R' 解除后尚未收到新设定值/命令（不自动恢复） */
    volatile bool latched;                  /**< 急停锁存（心跳 bit10 / 原因）；'R' 清 */
    volatile float sp[4];
    volatile uint32_t sp_ms;
    void (*on_params)(void);
    const bb_t *bb;                         /**< 可选：非 NULL 时响应黑匣子导出请求 */
    void (*on_cmd)(uint8_t c, uint8_t n);   /**< 'R' 以外的单字节命令；n = 第二字节（没有为 0） */
    dzrt_t rt;                              /**< 通用运行时（自检 / 运行模式 / 存参） */
} link_app_t;

static link_app_t *s_link_app_self;
static bool link_app_still_default(void)
{
    const link_app_t *L = s_link_app_self;
    for (unsigned k = 0; L && k < 4u; k++) if (L->sp[k] != 0.0f) return false;
    return true;
}

/* 仿真专用命令钩子：真板为空；host-sim 的 sim_setup.c 可覆盖（例如 'V' 让假相机停发、'U' 把摆扶正） */
DZ_WEAK void link_app_sim_cmd(uint8_t c, uint8_t n);
DZ_WEAK void link_app_sim_cmd(uint8_t c, uint8_t n) { (void)c; (void)n; }

static inline void link_app_send(const dzframe_t *f);
static void link_app_send_fwd(const dzframe_t *f) { link_app_send(f); }

static inline void link_app_init(link_app_t *L, void (*on_params)(void), void (*on_cmd)(uint8_t, uint8_t))
{
    dzframe_parser_init(&L->rx);
    dzctl_wd_init(&L->wd, 1000u);           /* 侧车每 250 ms 发一次心跳 */
    L->last_tx = 0; L->last_hb = 0u - 500u; /* 复位后第一拍就发心跳（带 schema 哈希） */
    L->seq = 0; L->hb_was_estop = false; L->estop = false; L->latched = false; L->sp_ms = 0;
    for (unsigned k = 0; k < 4u; k++) L->sp[k] = 0.0f;
    L->on_params = on_params; L->on_cmd = on_cmd; L->bb = 0;
    s_link_app_self = L;
    dzctl_estop_clear();                    /* 上电：RAM 里的旧原因不算（仿真里 app_init 会重跑） */
    if (dzrt_boot(&L->rt, &g_link_params, &g_link_params_default, link_app_still_default, link_app_send_fwd) == 0u && on_params) on_params();
    if (dzrt_selftest(&L->rt, pal_millis()) != 0u) { L->estop = L->latched = true; dzctl_estop_note(DZCTL_ES_SELFTEST, pal_millis(), 0.0f); }
    dzrt_start(&L->rt, !L->estop, false);
}

/** 脱机模式且已按键启动。 */
static inline bool link_app_running(const link_app_t *L) { return dzrt_sa_running(&L->rt); }

static inline void link_app_send(const dzframe_t *f)
{
    uint8_t out[DZFRAME_MAX_FRAME];
    size_t n = dzframe_encode(out, sizeof out, f);
    if (n) (void)link_write(out, (uint16_t)n);   /* EBUSY 时丢这一帧，下一帧补上 */
}

/** 处理收到的帧、看门狗和心跳；到了遥测周期返回 true。 */
static inline bool link_app_poll(link_app_t *L, uint32_t now)
{
    uint8_t buf[32]; uint16_t got = 0;
    dzframe_t f, ack;
    dzctl_table_t t = link_param_table(&g_link_params);
    if (link_read(buf, sizeof buf, &got) == DZ_OK) {
        for (uint16_t i = 0; i < got; i++) {
            if (!dzframe_feed(&L->rx, buf[i], &f)) continue;
            dzctl_wd_feed(&L->wd, &f, now);
            if (dzctl_is_estop(&f)) { L->estop = L->latched = true; dzctl_estop_note(DZCTL_ES_MANUAL, now, 0.0f); pid_relay_stop(); }
            else if (link_relay_frame(&f, L->latched, &L->seq, &ack)) { if (!L->latched) L->estop = false; link_app_send(&ack); }   /* 继电实验 = 显式新指令，解除后可开始 */
            else if (dzctl_is_bb_request(&f)) {
                for (uint16_t k = 0; L->bb && k < bb_count(L->bb); k++) {
                    const bb_rec_t *r = bb_get(L->bb, k);
                    dzctl_bb_frame(r->t_ms, r->code, r->arg, r->a, r->b, L->bb_seq++, &ack);
                    link_app_send(&ack);
                }
            }
            else if (dzctl_handle(&t, &f, &ack)) { if (L->on_params) L->on_params(); link_app_send(&ack); }
            else if (dzrt_cmd(&L->rt, &f)) { }
            else if (f.kind == DZF_DATA && f.id == 1u && !dzrt_needs_host(&L->rt)) { }   /* 脱机：不收上位机设定值 */
            else if (f.kind == DZF_DATA && f.id == 1u && f.len >= 4u && f.len % 4u == 0u) {
                for (unsigned k = 0; k < 4u && 4u * k < f.len; k++) L->sp[k] = dzframe_get_f32(&f, 4u * k);
                L->sp_ms = now;
                if (!L->latched) L->estop = false;   /* 解除后由人/Agent 重新给设定值才恢复输出 */
            }
            else if (f.kind == DZF_DATA && f.id == DZCTL_ID_CMD && f.len >= 1u) {
                uint8_t c = f.payload[0], n = f.len >= 2u ? f.payload[1] : 0u;
                if (c == 'R') {                    /* 只解锁存：设定值清零、输出保持禁止，不自动恢复 */
                    L->latched = false; dzctl_estop_clear();
                    for (unsigned k = 0; k < 4u; k++) L->sp[k] = 0.0f;
                    L->sp_ms = now;
                }
                else { if (!L->latched) L->estop = false; if (L->on_cmd) L->on_cmd(c, n); }
                link_app_sim_cmd(c, n);
            }
        }
    }
    if (dzrt_needs_host(&L->rt) && dzctl_wd_expired(&L->wd, now)) {   /* 上位机掉线：急停 */
        L->estop = L->latched = true;
        dzctl_estop_note(DZCTL_ES_HB_TIMEOUT, now, (float)(uint32_t)(now - L->wd.last_ms));
    }
    link_relay_guard(L->estop);                           /* 急停中结束继电 */
    L->rt.bb = (bb_t *)L->bb;
    {
        bool was_sa = !dzrt_needs_host(&L->rt);
        dzrt_poll(&L->rt, now, L->latched, -1);
        if (was_sa != !dzrt_needs_host(&L->rt)) dzctl_wd_init(&L->wd, 1000u);   /* 切模式：看门狗重新计 */
    }
    if (dzrt_hb_due(now, L->latched, &L->hb_was_estop, &L->last_hb)) {   /* 急停上升沿立即发 */
        dzctl_heartbeat(&t, L->seq++, &f);
        link_app_send(&f);
    }
    if (now - L->last_tx >= LINK_TELEM_PERIOD_MS) { L->last_tx = now; return true; }
    return false;
}

static inline void link_app_send_telem(link_app_t *L, const link_telem_t *v)
{
    dzframe_t f;
    if (link_telem_pack(&f, v)) { f.seq = L->seq++; link_app_send(&f); }
}

#endif
