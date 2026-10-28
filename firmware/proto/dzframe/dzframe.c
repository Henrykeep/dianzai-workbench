#include "dzframe.h"
#include <string.h>

#define SOF0 0xA5u
#define SOF1 0x5Au

uint16_t dzframe_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (int b = 0; b < 8; b++)
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
    }
    return crc;
}

size_t dzframe_encode(uint8_t *out, size_t cap, const dzframe_t *f)
{
    if (!out || !f || f->len > DZFRAME_MAX_PAYLOAD) return 0;
    size_t n = (size_t)f->len + DZFRAME_OVERHEAD;
    if (cap < n) return 0;
    out[0] = SOF0; out[1] = SOF1; out[2] = DZFRAME_PROTO_VER;
    out[3] = f->kind; out[4] = f->id; out[5] = f->seq; out[6] = f->len;
    memcpy(&out[7], f->payload, f->len);
    uint16_t crc = dzframe_crc16(&out[2], (size_t)f->len + 5u);
    out[7 + f->len] = (uint8_t)crc;
    out[8 + f->len] = (uint8_t)(crc >> 8);
    return n;
}

void dzframe_parser_init(dzframe_parser_t *p)
{
    memset(p, 0, sizeof *p);
}

/* 检查 buf 前 n 字节：返回 0=还需要更多字节，1=完整正确帧，-1=错误（需要重新同步） */
static int check(const uint8_t *b, uint16_t n)
{
    if (n >= 1 && b[0] != SOF0) return -1;
    if (n >= 2 && b[1] != SOF1) return -1;
    if (n >= 3 && b[2] != DZFRAME_PROTO_VER) return -1;
    if (n >= 7 && b[6] > DZFRAME_MAX_PAYLOAD) return -1;
    if (n < 7 || n < (uint16_t)(b[6] + DZFRAME_OVERHEAD)) return 0;
    uint16_t crc = dzframe_crc16(&b[2], (size_t)b[6] + 5u);
    return (b[7 + b[6]] == (uint8_t)crc && b[8 + b[6]] == (uint8_t)(crc >> 8)) ? 1 : -1;
}

/* 丢掉第一个字节，并把剩余字节前移到下一个可能的帧头 */
static void resync(dzframe_parser_t *p)
{
    uint16_t i = 1;
    while (i < p->n && p->buf[i] != SOF0) i++;
    memmove(p->buf, &p->buf[i], (size_t)(p->n - i));
    p->n = (uint16_t)(p->n - i);
}

bool dzframe_feed(dzframe_parser_t *p, uint8_t byte, dzframe_t *out)
{
    if (p->n == 0 && byte != SOF0) return false;      /* 快速跳过帧间垃圾 */
    p->buf[p->n++] = byte;
    for (;;) {
        int r = check(p->buf, p->n);
        if (r == 0) return false;
        if (r == 1) {
            uint8_t len = p->buf[6];
            if (out) {
                out->kind = p->buf[3]; out->id = p->buf[4]; out->seq = p->buf[5]; out->len = len;
                memcpy(out->payload, &p->buf[7], len);
            }
            p->good++;
            p->n = 0;                    /* 一次 feed 只加入一个字节，所以完整帧之后不会有残余 */
            return true;
        }
        if (p->n > 1 || p->buf[0] == SOF0) p->bad++;
        resync(p);
        if (p->n == 0) return false;
    }
}

static bool room(const dzframe_t *f, size_t n) { return (size_t)f->len + n <= DZFRAME_MAX_PAYLOAD; }
static bool put_le(dzframe_t *f, uint32_t v, size_t n)
{
    if (!room(f, n)) return false;
    for (size_t i = 0; i < n; i++) f->payload[f->len + i] = (uint8_t)(v >> (8u * i));   /* 显式小端，与 CPU 字节序无关 */
    f->len = (uint8_t)(f->len + n);
    return true;
}
static uint32_t get_le(const dzframe_t *f, size_t off, size_t n)
{
    if (off + n > f->len) return 0;
    uint32_t v = 0;
    for (size_t i = 0; i < n; i++) v |= (uint32_t)f->payload[off + i] << (8u * i);
    return v;
}

bool dzframe_put_u8 (dzframe_t *f, uint8_t v)  { return put_le(f, v, 1); }
bool dzframe_put_u16(dzframe_t *f, uint16_t v) { return put_le(f, v, 2); }
bool dzframe_put_u32(dzframe_t *f, uint32_t v) { return put_le(f, v, 4); }
bool dzframe_put_f32(dzframe_t *f, float v)    { uint32_t u; memcpy(&u, &v, 4); return put_le(f, u, 4); }   /* IEEE754 单精度 */
uint8_t  dzframe_get_u8 (const dzframe_t *f, size_t off) { return (uint8_t)get_le(f, off, 1); }
uint16_t dzframe_get_u16(const dzframe_t *f, size_t off) { return (uint16_t)get_le(f, off, 2); }
uint32_t dzframe_get_u32(const dzframe_t *f, size_t off) { return get_le(f, off, 4); }
float    dzframe_get_f32(const dzframe_t *f, size_t off) { uint32_t u = get_le(f, off, 4); float v; memcpy(&v, &u, 4); return v; }

dz_err_t dzframe_selftest(void)
{
    if (dzframe_crc16((const uint8_t *)"123456789", 9) != 0x29B1u) return DZ_EIO;
    dzframe_t f = { DZF_DATA, 7, 42, 0, {0} }, g;
    if (!dzframe_put_u16(&f, 0xBEEFu) || !dzframe_put_f32(&f, 1.5f)) return DZ_EIO;
    uint8_t buf[DZFRAME_MAX_FRAME];
    size_t n = dzframe_encode(buf, sizeof buf, &f);
    if (n != f.len + DZFRAME_OVERHEAD) return DZ_EIO;
    dzframe_parser_t p;
    dzframe_parser_init(&p);
    bool got = false;
    for (size_t i = 0; i < n; i++) got = dzframe_feed(&p, buf[i], &g);
    if (!got || g.id != 7 || g.seq != 42 || dzframe_get_u16(&g, 0) != 0xBEEFu || dzframe_get_f32(&g, 2) != 1.5f) return DZ_EIO;
    buf[n - 3] ^= 0x01u;                       /* 损坏一个负载字节 */
    got = false;
    for (size_t i = 0; i < n; i++) got |= dzframe_feed(&p, buf[i], &g);
    return got ? DZ_EIO : DZ_OK;
}
