#include <string.h>
#include <stdlib.h>
#include "tt.h"
#include "dzframe.h"

static int feed_all(dzframe_parser_t *p, const uint8_t *b, size_t n, dzframe_t *out, int max)
{
    int k = 0; dzframe_t f;
    for (size_t i = 0; i < n; i++) if (dzframe_feed(p, b[i], &f) && k < max) out[k++] = f;
    return k;
}

TEST(dzframe_crc_known_vector)
{
    CHECK(dzframe_crc16((const uint8_t *)"123456789", 9) == 0x29B1);   /* CCITT-FALSE 标准校验值 */
}

TEST(dzframe_roundtrip_and_fields)
{
    dzframe_t f = { DZF_DATA, 3, 200, 0, {0} }, g[2];
    CHECK(dzframe_put_u16(&f, 0xBEEF) && dzframe_put_f32(&f, -1.5f) && dzframe_put_u8(&f, 7));
    uint8_t buf[DZFRAME_MAX_FRAME];
    size_t n = dzframe_encode(buf, sizeof buf, &f);
    CHECK(n == 7u + DZFRAME_OVERHEAD && buf[7] == 0xEF && buf[8] == 0xBE);    /* 小端 */
    CHECK(dzframe_encode(buf, n - 1, &f) == 0);
    dzframe_parser_t p; dzframe_parser_init(&p);
    CHECK(feed_all(&p, buf, n, g, 2) == 1);
    CHECK(g[0].id == 3 && g[0].seq == 200 && dzframe_get_u16(&g[0], 0) == 0xBEEF);
    CHECK(dzframe_get_f32(&g[0], 2) == -1.5f && dzframe_get_u8(&g[0], 6) == 7);
    CHECK(dzframe_get_u32(&g[0], 5) == 0);                                   /* 越界读返回 0 */
    dzframe_t big = { DZF_DATA, 0, 0, 0, {0} };
    for (int i = 0; i < 16; i++) CHECK(dzframe_put_u32(&big, (uint32_t)i));
    CHECK(!dzframe_put_u8(&big, 1));                                         /* 满 64 字节 */
    big.len = DZFRAME_MAX_PAYLOAD + 1; CHECK(dzframe_encode(buf, sizeof buf, &big) == 0);
}

TEST(dzframe_resync_after_corruption)
{
    uint8_t s[4 * DZFRAME_MAX_FRAME]; size_t n = 0;
    dzframe_t a = { DZF_DATA, 1, 1, 2, { 0xA5, 0x5A } };   /* 负载里故意放帧头字节 */
    dzframe_t b = { DZF_HEARTBEAT, 0, 2, 0, {0} };
    s[n++] = 0x00; s[n++] = 0xA5;                           /* 垃圾 + 孤立帧头 */
    size_t ka = dzframe_encode(&s[n], sizeof s - n, &a);
    s[n + ka - 1] ^= 0xFF;                                  /* 第一帧 CRC 坏 */
    n += ka;
    n += dzframe_encode(&s[n], sizeof s - n, &b);           /* 紧跟一帧好的 */
    n += dzframe_encode(&s[n], sizeof s - n, &a);
    dzframe_parser_t p; dzframe_parser_init(&p); dzframe_t g[4];
    int k = feed_all(&p, s, n, g, 4);
    CHECK(k == 2 && g[0].kind == DZF_HEARTBEAT && g[1].payload[0] == 0xA5);
    CHECK(p.bad >= 1 && p.good == 2);
    /* 随机噪声不能让解析器崩溃或越界（ASan 检查），且噪声后好帧仍能收到 */
    srand(1);
    for (int i = 0; i < 20000; i++) { uint8_t c = (uint8_t)rand(); dzframe_feed(&p, c, NULL); }
    uint8_t pad[DZFRAME_MAX_FRAME]; memset(pad, 0, sizeof pad);
    feed_all(&p, pad, sizeof pad, g, 4);                    /* 冲掉未完成的半帧 */
    size_t kb = dzframe_encode(s, sizeof s, &b);
    CHECK(feed_all(&p, s, kb, g, 4) == 1);
}

/* 与 host/python/dzlink 的互通：Python 生成的这帧（kind=0 id=5 seq=9 payload=01020304）必须能解析 */
TEST(dzframe_python_interop)
{
    static const uint8_t py[] = { 0xA5, 0x5A, 0x01, 0x00, 0x05, 0x09, 0x04, 0x01, 0x02, 0x03, 0x04, PY_CRC_L, PY_CRC_H };
    dzframe_parser_t p; dzframe_parser_init(&p); dzframe_t g[1];
    CHECK(feed_all(&p, py, sizeof py, g, 1) == 1 && g[0].id == 5 && dzframe_get_u32(&g[0], 0) == 0x04030201u);
}

void suite_dzframe(void) { RUN(dzframe_crc_known_vector); RUN(dzframe_roundtrip_and_fields); RUN(dzframe_resync_after_corruption); RUN(dzframe_python_interop); }
