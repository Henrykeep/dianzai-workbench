/**
 * @file dzctl.h
 * @brief 上位机控制服务（dzframe/1 之上）：参数读写（带限幅）+ 急停 + 带 schema 哈希的心跳。
 *
 * 线上格式（全部小端，见 README）：
 *   上位机 -> 板  PARAM_SET id=参数序号  len=0 读 / len=4 写（f32，板端按类型换算并限幅）
 *   板 -> 上位机  PARAM_ACK id=参数序号  payload: u8 status, f32 生效值
 *   上位机 -> 板  DATA id=DZCTL_ID_ESTOP len=0   急停（应用必须锁存，只有复位/显式解除才能恢复）
 *   上位机 -> 板  DATA id=DZCTL_ID_CMD   len=1   单字节命令（应用自定义，如 'G' 开始 'S' 停止 'R' 复位）
 *   板 -> 上位机  HEARTBEAT id=0 payload: u32 schema_hash [, u32 board_uid]  —— 上位机据此匹配 link_schema.json；
 *                 0.5.0 起第 4 个 u32 status：低 8 位 = 复位原因（pal_reset_cause_t 数值），高位 = DZCTL_HB_* 标志
 *                 board_uid（0.3.0 起）= 芯片唯一 ID 折成 32 位，两块同型号板同时插着时上位机靠它认板；0 = 未知
 * 参数表由 tools/gen_link.py 从 yaml 生成，应用不手写。
 */
#ifndef DZCTL_H
#define DZCTL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "dzframe.h"

#define DZCTL_VERSION "0.6.0"
#define DZCTL_ID_CMD   0x7Eu
#define DZCTL_ID_ESTOP 0x7Fu
#define DZCTL_ID_BB    0x7Du   /**< 0.6.0 黑匣子：上位机 len=0 请求；板子每条记录回一帧 u32 t_ms, u16 code, u16 arg, f32 a, f32 b */

typedef enum { DZCTL_F32, DZCTL_U32, DZCTL_I32, DZCTL_U16, DZCTL_I16, DZCTL_U8, DZCTL_BOOL } dzctl_type_t;
typedef enum { DZCTL_OK = 0, DZCTL_CLAMPED = 1, DZCTL_BAD_ID = 2, DZCTL_BAD_LEN = 3, DZCTL_BAD_VALUE = 4 } dzctl_status_t;

typedef struct {
    const char *name;
    uint16_t offset;      /**< 在参数结构体里的偏移（offsetof） */
    uint8_t  type;        /**< dzctl_type_t */
    float    min, max;    /**< 写入时限幅到 [min, max] */
} dzctl_param_t;

typedef struct {
    void *base;                     /**< 当前生效的参数结构体 */
    const dzctl_param_t *desc;
    uint8_t n;
    uint32_t schema_hash;
} dzctl_table_t;

/** 读第 i 个参数（换算成 float）；i 越界返回 0。 */
float dzctl_get(const dzctl_table_t *t, uint8_t i);

/** 写第 i 个参数：NaN/Inf 拒绝（BAD_VALUE），超界限幅（CLAMPED）；*applied 返回生效值。 */
dzctl_status_t dzctl_set(const dzctl_table_t *t, uint8_t i, float v, float *applied);

/** 处理一帧 PARAM_SET；是则填好 ack 并返回 true（调用方负责发送），不是 PARAM_SET 返回 false。 */
bool dzctl_handle(const dzctl_table_t *t, const dzframe_t *in, dzframe_t *ack);

/** 是否急停帧。 */
bool dzctl_is_estop(const dzframe_t *f);

/** 芯片唯一 ID 折成 32 位（端口实现；弱默认返回 0 = 未知）。 */
uint32_t dzctl_board_uid(void);
/** 固件版本：git 短哈希（7 位十六进制 = 低 28 位），bit31 = 编译时工作区有未提交改动；0 = 未知（Keil/CCS 工程没传 DZ_FW_REV）。
 *  make 自动给 dzctl.c 传 -DDZ_FW_REV；应用也可覆盖（弱符号）。 */
uint32_t dzctl_fw_rev(void);

/* 心跳 status 字（0.5.0）：低 8 位复位原因，由应用在 app_init 里 dzctl_set_reset_cause(pal_reset_cause()) 填；
 * 不填 = 0 = 未知（proto 层不依赖 pal）。标志位应用按需置/清。 */
#define DZCTL_HB_SAFE_BOOT (1u << 8)   /**< 异常复位（看门狗/锁死）后进了安全态：输出关、锁急停，等人发 'R' */
#define DZCTL_HB_STALL     (1u << 9)   /**< 堵转锁存 */
#define DZCTL_HB_ESTOP     (1u << 10)  /**< 急停锁存中（任何原因） */
/** 是不是黑匣子导出请求。 */
bool dzctl_is_bb_request(const dzframe_t *f);
/** 填一帧黑匣子记录（字段同 blackbox 的 bb_rec_t；proto 层不依赖 framework，所以按字段传）。 */
void dzctl_bb_frame(uint32_t t_ms, uint16_t code, uint16_t arg, float a, float b, uint8_t seq, dzframe_t *out);
void dzctl_set_reset_cause(uint32_t cause);
void dzctl_set_flags(uint32_t mask, bool on);
uint32_t dzctl_status_word(void);

/** 填心跳帧（schema 哈希 + 板 ID + 固件版本 + status 字）。 */
void dzctl_heartbeat(const dzctl_table_t *t, uint8_t seq, dzframe_t *out);

/** 上位机链路看门狗：收到上位机 HEARTBEAT（LEN=0）才"布防"，之后超过 timeout_ms 没有任何上位机帧
 *  -> dzctl_wd_expired() 返回一次 true（应用必须：输出归零 + 锁存急停）并撤防。
 *  没连电脑跑比赛时上位机从不发心跳，看门狗不布防，不影响脱机运行。未上板验证。 */
typedef struct { uint32_t last_ms, timeout_ms; bool armed; } dzctl_wd_t;
void dzctl_wd_init(dzctl_wd_t *w, uint32_t timeout_ms);
/** 每收到一帧完整的上位机帧调用一次。 */
void dzctl_wd_feed(dzctl_wd_t *w, const dzframe_t *f, uint32_t now_ms);
bool dzctl_wd_expired(dzctl_wd_t *w, uint32_t now_ms);

/** 自检：返回失败项数。 */
int dzctl_selftest(void);

#endif
