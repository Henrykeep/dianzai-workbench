/**
 * io 胶水 · 上位机链路（从 io_main.c 原样拆出，2026-10-29，行为不变）。
 * LINK 串口（可选，板上有 LINK 才编译）：dzframe/1 + dzctl（见 firmware/proto/dzctl），桌面工作台 app/ 直接连。
 *   板→PC：遥测 DATA id=2 每 20 ms（字段见 project.yaml link.telemetry），心跳带 schema 哈希，PARAM_ACK
 *   PC→板：PARAM_SET 读写“当前参数档”（板端限幅）；DATA 0x7F 急停；DATA 0x7E u8 命令：
 *          'T'+n 选测试项（n = 测试项 id，即 project.yaml tests[].id，不是下标；在第 2 字节）  'P'+n 选参数档  'G' 开始  'S' 停止  'R' 复位
 *          DATA id=1 <f32 px>：上位机给钢珠目标位置（覆盖 hooks 里的默认 0；钳到 ±400 px，非有限值忽略，急停清零）。
 *          工作台的阶跃实验 / Agent 评测用它（dzbench.json step_test）。
 *
 */
#include <math.h>
#include <string.h>
#include "board_gen.h"
#include "io_parts.h"

#ifdef RES_UART_LINK
#include "link_io.h"
#include "link_gen.h"
#include "dz_compiler.h"
#include "dzframe.h"
#include "io_safety.h"
#include "safety.h"
#include "dzctl.h"
#include "link_relay.h"
#include "rtosmon.h"
#define DZRT_PARAMS_T params_t
#include "dz_runtime.h"

#define LINK_ID_BALL_SP 0x01u
static dzctl_wd_t WD;
static dzframe_parser_t LL;   /* LINK 上位机帧 */
static float s_host_sp_px;    /* 上位机给的钢珠目标 */
float io_host_ball_sp_px(void) { return s_host_sp_px; }

static uint8_t link_seq;
static dzrt_t RT;              /* 通用运行时：自检 / 运行模式 / 存参（dz_runtime.h） */
static params_t s_par_def;     /* 上电时当前档的默认值（flash 坏 → 回到它） */
static void link_send(dzframe_t *f);
static void link_send_c(const dzframe_t *f) { dzframe_t g = *f; link_send(&g); }
static bool io_still(void)
{
    coord_state_t s = io_coord()->st;
    return s == COORD_IDLE || s == COORD_DONE || s == COORD_ESTOP || s == COORD_FAULT;
}
static bool st_subsys(void) { return subsys_sched_selftest(io_coord()->sched) < 0; }

void io_link_init(void)
{
    dzframe_parser_init(&LL);
    dzctl_wd_init(&WD, 1000u);   /* 上位机心跳看门狗（侧车每 250 ms 发心跳；脱机比赛不布防） */
}

/* coord/sched 建好之后调用（io_main app_init 末尾）：读 flash 参数、跑自检（失败 → 急停）、读运行模式 */
void io_link_boot(void)
{
    s_par_def = g_project_params[io_coord()->profile_idx];
    (void)dzrt_boot(&RT, &g_project_params[io_coord()->profile_idx], &s_par_def, io_still, link_send_c);
    (void)dzctl_selftest_register(DZCTL_ST_SUBSYS, st_subsys);
    if (dzrt_selftest(&RT, pal_millis()) != 0u) { dzctl_estop_note(DZCTL_ES_SELFTEST, pal_millis(), 0.0f); coord_event(io_coord(), COORD_EV_ESTOP); }
    dzrt_start(&RT, io_coord()->st != COORD_ESTOP, false);
}

static void link_send(dzframe_t *f)
{
    uint8_t out[DZFRAME_MAX_FRAME];
    size_t n;
    f->seq = link_seq++;
    n = dzframe_encode(out, sizeof out, f);
    if (n) (void)link_write(out, (uint16_t)n);   /* EBUSY 丢帧：遥测下一拍补，ACK 由上位机超时重发 */
}

/* 仿真专用命令的钩子：真板上是空函数；host-sim 的 sim_setup.c 覆盖它（如 'V' = 让假相机停发，测 HELD/LOST） */
DZ_WEAK void io_sim_cmd(uint8_t c, uint8_t n);
DZ_WEAK void io_sim_cmd(uint8_t c, uint8_t n) { (void)c; (void)n; }

/* 'T' 的 n 是测试项 id（dzbench.json step_tests 的 ["T",1] = 小题 1）。曾经直接当下标用：'T'1 选中了下标 1 = 小题 2（fast 档 + 底盘加速），
 * 上位机写的 base 档参数全都不生效，阶跃指标与 pos_k 无关。找不到该 id 时不切换。 */
static void select_test_id(uint8_t id)
{
    const coord_t *c = io_coord();
    for (uint8_t i = 0; i < c->n_tests; i++)
        if (c->tests[i].id == id) { (void)coord_select_test(io_coord(), i); return; }
}

static void handle_cmd(const dzframe_t *f)
{
    uint8_t n = f->len > 1u ? f->payload[1] : 0u;
    switch (f->payload[0]) {
    case 'T': select_test_id(n); break;
    case 'P': coord_select_profile(io_coord(), n); break;
    case 'G': coord_event(io_coord(), COORD_EV_START); break;
    case 'S': coord_event(io_coord(), COORD_EV_STOP); break;
    case 'R': io_safety_clear(pal_millis()); dzctl_estop_clear(); coord_event(io_coord(), COORD_EV_RESET); break;   /* 人确认：解堵转/安全态 */
    default: io_sim_cmd(f->payload[0], n); break;
    }
}

static uint8_t s_relay_seq;

void io_link_read(void)
{
    uint8_t buf[32]; uint16_t got = 0, i;
    dzframe_t f, ack;
    dzctl_table_t t = link_param_table(&g_project_params[io_coord()->profile_idx]);
    if (dzrt_needs_host(&RT) && dzctl_wd_expired(&WD, pal_millis())) {
        dzctl_estop_note(DZCTL_ES_HB_TIMEOUT, pal_millis(), (float)(uint32_t)(pal_millis() - WD.last_ms));
        coord_event(io_coord(), COORD_EV_ESTOP);
    }   /* 急停路径负责输出归零 */
    bool stop = io_coord()->st == COORD_ESTOP || io_coord()->st == COORD_FAULT;
    link_relay_guard(stop);                                  /* 急停/故障中结束继电 */
    if (link_read(buf, sizeof buf, &got) != DZ_OK) return;
    for (i = 0; i < got; i++) {
        if (!dzframe_feed(&LL, buf[i], &f)) continue;
        dzctl_wd_feed(&WD, &f, pal_millis());
        if (dzctl_is_estop(&f)) { dzctl_estop_note(DZCTL_ES_MANUAL, pal_millis(), 0.0f); coord_event(io_coord(), COORD_EV_ESTOP); s_host_sp_px = 0.0f; }
        else if (link_relay_frame(&f, stop, &s_relay_seq, &ack)) link_send(&ack);
        else if (dzctl_handle(&t, &f, &ack)) link_send(&ack);
        else if (dzctl_is_bb_request(&f)) {                 /* 黑匣子导出（dzctl 0.6.0） */
            const bb_t *bb = io_safety_bb();
            for (uint16_t k = 0; k < bb_count(bb); k++) {
                const bb_rec_t *r = bb_get(bb, k);
                dzctl_bb_frame(r->t_ms, r->code, r->arg, r->a, r->b, 0u, &ack);
                link_send(&ack);
            }
        }
        else if (dzrt_cmd(&RT, &f)) { }                   /* 'W' 存参 / 'M' 切模式 / 'H' 重跑自检（dz_runtime.h） */
        else if (f.kind == DZF_DATA && f.id == DZCTL_ID_CMD && f.len >= 1u) handle_cmd(&f);
        else if (f.kind == DZF_DATA && f.id == LINK_ID_BALL_SP && f.len == 4u) {
            float v; memcpy(&v, f.payload, 4u);
            if (isfinite(v)) s_host_sp_px = v > 400.0f ? 400.0f : (v < -400.0f ? -400.0f : v);
        }
    }
}

void io_link_write(uint32_t now)
{
    static uint32_t last_tx;
    static uint32_t last_hb = 0u - 500u;   /* 复位后第一拍就发心跳，上位机马上认出 schema */
    static bool hb_was_estop;
    bool estop;
    dzframe_t f;
    if (now - last_tx >= LINK_TELEM_PERIOD_MS) {
        link_telem_t t;
        last_tx = now;
        t.t_ms = now; t.state = (uint8_t)coord_state(io_coord()); t.test_id = io_state()->coord.test_id;
        t.cam_x_px = io_state()->io_in.cam_x_px; t.ball_sp_px = io_state()->coord.ball_sp_px;
        t.angle_deg = io_state()->beam_out.angle_deg; t.beam_fb_deg = io_state()->io_in.beam_fb_deg;
        t.wheel_a_mps = io_state()->io_in.wheel_a_mps; t.wheel_b_mps = io_state()->io_in.wheel_b_mps;
        t.bb_state = io_state()->beam_out.state; t.beam_online = io_state()->io_in.beam_online ? 1u : 0u;
        t.vis_state = io_state()->vision_out.state; t.vis_age_ms = io_state()->vision_out.age_ms; t.vis_drops = io_state()->vision_out.drops;
        t.vis_lat_ms = (int16_t)(io_state()->vision_out.lat_jit_ms > 32767 ? 32767 : io_state()->vision_out.lat_jit_ms);
        t.ff_deg = io_state()->beam_out.ff_deg;
        t.imu_ax_mps2 = io_state()->io_in.imu_ax_mps2; t.imu_ok = io_state()->io_in.imu_ok ? 1u : 0u;
        t.cpu_pm = rtosmon_cpu_permille(&g_rtosmon); t.stk_min_w = rtosmon_stack_min_words(&g_rtosmon);   /* 裸机 = 0xFFFF */
        if (link_telem_pack(&f, &t)) link_send(&f);
    }
    RT.p = &g_project_params[io_coord()->profile_idx];
    {
        bool was_sa = !dzrt_needs_host(&RT);
        coord_state_t cs = io_coord()->st;
        estop = cs == COORD_ESTOP || cs == COORD_FAULT;
        dzrt_poll(&RT, now, estop, -1);
        if (was_sa != !dzrt_needs_host(&RT)) dzctl_wd_init(&WD, 1000u);
    }
    if (dzrt_hb_due(now, estop, &hb_was_estop, &last_hb)) {   /* 置 DZCTL_HB_ESTOP；急停上升沿立即发 */
        dzctl_table_t pt = link_param_table(&g_project_params[io_coord()->profile_idx]);
        dzctl_set_flags(SAFETY_F_SAFE_BOOT | SAFETY_F_STALL, false);
        dzctl_set_flags(io_safety_flags(), true);
        dzctl_heartbeat(&pt, 0, &f);
        link_send(&f);
    }
}

#else   /* 板上没有 LINK 串口：空实现，目标恒 0 */
float io_host_ball_sp_px(void) { return 0.0f; }
void io_link_init(void) {}
void io_link_boot(void) {}
void io_link_read(void) {}
void io_link_write(uint32_t now) { (void)now; }
#endif
