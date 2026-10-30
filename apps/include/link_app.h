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

typedef struct {
    dzframe_parser_t rx;
    dzctl_wd_t wd;
    uint32_t last_tx, last_hb;
    uint8_t seq, bb_seq;
    volatile bool estop;
    volatile float sp[4];
    volatile uint32_t sp_ms;
    void (*on_params)(void);
    const bb_t *bb;                         /**< 可选：非 NULL 时响应黑匣子导出请求 */
    void (*on_cmd)(uint8_t c, uint8_t n);   /**< 'R' 以外的单字节命令；n = 第二字节（没有为 0） */
} link_app_t;

/* 仿真专用命令钩子：真板为空；host-sim 的 sim_setup.c 可覆盖（例如 'V' 让假相机停发、'U' 把摆扶正） */
DZ_WEAK void link_app_sim_cmd(uint8_t c, uint8_t n);
DZ_WEAK void link_app_sim_cmd(uint8_t c, uint8_t n) { (void)c; (void)n; }

static inline void link_app_init(link_app_t *L, void (*on_params)(void), void (*on_cmd)(uint8_t, uint8_t))
{
    dzframe_parser_init(&L->rx);
    dzctl_wd_init(&L->wd, 1000u);           /* 侧车每 250 ms 发一次心跳 */
    L->last_tx = 0; L->last_hb = 0u - 500u; /* 复位后第一拍就发心跳（带 schema 哈希） */
    L->seq = 0; L->estop = false; L->sp_ms = 0;
    for (unsigned k = 0; k < 4u; k++) L->sp[k] = 0.0f;
    L->on_params = on_params; L->on_cmd = on_cmd; L->bb = 0;
}

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
            if (dzctl_is_estop(&f)) { L->estop = true; pid_relay_stop(); }
            else if (link_relay_frame(&f, L->estop, &L->seq, &ack)) link_app_send(&ack);
            else if (dzctl_is_bb_request(&f)) {
                for (uint16_t k = 0; L->bb && k < bb_count(L->bb); k++) {
                    const bb_rec_t *r = bb_get(L->bb, k);
                    dzctl_bb_frame(r->t_ms, r->code, r->arg, r->a, r->b, L->bb_seq++, &ack);
                    link_app_send(&ack);
                }
            }
            else if (dzctl_handle(&t, &f, &ack)) { if (L->on_params) L->on_params(); link_app_send(&ack); }
            else if (f.kind == DZF_DATA && f.id == 1u && f.len >= 4u && f.len % 4u == 0u) {
                for (unsigned k = 0; k < 4u && 4u * k < f.len; k++) L->sp[k] = dzframe_get_f32(&f, 4u * k);
                L->sp_ms = now;
            }
            else if (f.kind == DZF_DATA && f.id == DZCTL_ID_CMD && f.len >= 1u) {
                uint8_t c = f.payload[0], n = f.len >= 2u ? f.payload[1] : 0u;
                if (c == 'R') L->estop = false;
                else if (L->on_cmd) L->on_cmd(c, n);
                link_app_sim_cmd(c, n);
            }
        }
    }
    if (dzctl_wd_expired(&L->wd, now)) L->estop = true;   /* 上位机掉线：急停 */
    link_relay_guard(L->estop);                           /* 急停中结束继电 */
    if (now - L->last_hb >= 500u) {
        L->last_hb = now;
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
