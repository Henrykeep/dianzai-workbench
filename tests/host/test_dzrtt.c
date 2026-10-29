#include <string.h>
#include "tt.h"
#include "dzrtt.h"

/* 模拟探针（pyOCD rtt.py 的读写方式）：上行读 rd..wr 后更新 rd；下行写到 wr 后更新 wr */
static uint32_t probe_read(uint8_t *out, uint32_t max)
{
    dzrtt_ring_t *r = &g_dzrtt.up[0]; uint32_t n = 0;
    while (r->rd != r->wr && n < max) { out[n++] = (uint8_t)r->buf[r->rd]; r->rd = (r->rd + 1u) % r->size; }
    return n;
}
static void probe_write(const uint8_t *b, uint32_t n)
{
    dzrtt_ring_t *r = &g_dzrtt.down[0];
    for (uint32_t i = 0; i < n; i++) { r->buf[r->wr] = (char)b[i]; r->wr = (r->wr + 1u) % r->size; }
}

TEST(dzrtt_control_block_and_roundtrip)
{
    CHECK(dzrtt_selftest() == 0);
    CHECK(g_dzrtt.max_up == 1 && g_dzrtt.max_down == 1 && strcmp(g_dzrtt.up[0].name, "Terminal") == 0);
    uint8_t a[300], o[400]; for (int i = 0; i < 300; i++) a[i] = (uint8_t)(i * 7);
    for (int k = 0; k < 10; k++) {                          /* 3000 B 走 1 KB 环：多次回绕 */
        CHECK(dzrtt_write(a, 300) == DZ_OK);
        CHECK(probe_read(o, sizeof o) == 300 && memcmp(a, o, 300) == 0);
    }
    probe_write((const uint8_t *)"\xa5\x5aHI", 4);
    uint16_t got = 0; uint8_t in[8];
    CHECK(dzrtt_read(in, sizeof in, &got) == DZ_OK && got == 4 && in[2] == 'H');
    CHECK(dzrtt_read(in, sizeof in, &got) == DZ_OK && got == 0);
}

TEST(dzrtt_full_drops_whole_chunk)
{
    uint8_t a[600] = {0}, o[DZRTT_UP_SIZE];
    CHECK(dzrtt_write(a, 600) == DZ_OK);
    CHECK(dzrtt_write(a, 600) == DZ_EBUSY);                   /* 只剩 423 B：整段不写，不拆帧 */
    CHECK(probe_read(o, sizeof o) == 600);
    CHECK(dzrtt_write(NULL, 3) == DZ_EINVAL);
}
void suite_dzrtt(void);
void suite_dzrtt(void) { RUN(dzrtt_control_block_and_roundtrip); RUN(dzrtt_full_drops_whole_chunk); }
