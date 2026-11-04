/* dz_store（FlashDB+EasyLogger on pal_nvm）主机测试：RAM 模拟 flash（写只能 1→0、未擦写报错），随机参数 + 掉电（重新 init）后核对。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <elog.h>
#include "dz_store.h"
#include "pal.h"

#define NVM 8192u
#define UNIT 1024u
static uint8_t nvm[NVM];
static uint32_t ms;
dz_err_t pal_nvm_info(uint32_t *s, uint32_t *u) { *s = NVM; *u = UNIT; return DZ_OK; }
dz_err_t pal_nvm_erase(uint32_t o, uint32_t n) { if (o % UNIT || n % UNIT || o + n > NVM) return DZ_EINVAL; memset(nvm + o, 0xFF, n); return DZ_OK; }
dz_err_t pal_nvm_write(uint32_t o, const void *p, uint32_t n)
{
    const uint8_t *b = p;
    if (o % 8 || n % 8 || o + n > NVM) return DZ_EINVAL;
    for (uint32_t i = 0; i < n; i++) nvm[o + i] &= b[i];
    return DZ_OK;
}
dz_err_t pal_nvm_read(uint32_t o, void *p, uint32_t n) { if (o + n > NVM) return DZ_EINVAL; memcpy(p, nvm + o, n); return DZ_OK; }
uint32_t pal_irq_save(void) { return 0; }
void pal_irq_restore(uint32_t s) { (void)s; }
uint32_t pal_millis(void) { return ms += 7; }

static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)
static int count_cb(uint32_t t, const char *s, void *c) { (void)t; if (strstr(s, "overheat")) ++*(int *)c; return 0; }
static size_t sunk;
static void sink(const char *l, size_t n) { (void)l; sunk += n; }

int main(int argc, char **argv)
{
    unsigned seed = argc > 1 ? (unsigned)atoi(argv[1]) : 12345u;
    srand(seed);
    memset(nvm, 0xFF, sizeof nvm);
    CHECK(dz_store_init() == DZ_OK);
    float want[8]; char key[16];
    for (int round = 0; round < 20; round++)
        for (int k = 0; k < 8; k++) {
            want[k] = (float)rand() / 1000.0f;
            snprintf(key, sizeof key, "p%d", k);
            CHECK(dz_param_save(key, &want[k], sizeof want[k]) == DZ_OK);
        }
    elog_init(); elog_set_fmt(ELOG_LVL_WARN, ELOG_FMT_LVL | ELOG_FMT_TAG); elog_start();
    dz_log_set_sink(sink);
    elog_w("app", "overheat %d", 1);
    elog_i("app", "just info");
    CHECK(dz_event_log("boot ok") == DZ_OK);
    CHECK(sunk > 0);
    /* 掉电：RAM 状态全丢，只剩 nvm[] */
    CHECK(dz_store_init() == DZ_OK);
    for (int k = 0; k < 8; k++) {
        float got = 0; snprintf(key, sizeof key, "p%d", k);
        CHECK(dz_param_load(key, &got, sizeof got) == sizeof got);
        CHECK(got == want[k]);
    }
    int hot = 0;
    CHECK(dz_event_iter(count_cb, &hot) >= 2);
    CHECK(hot == 1);
    CHECK(dz_param_erase("p0") == DZ_OK);
    float z; CHECK(dz_param_load("p0", &z, sizeof z) == 0);
    for (int i = 0; i < 400; i++) CHECK(dz_event_log("filler event to force tsdb rollover ......") == DZ_OK);
    CHECK(dz_event_iter(NULL, NULL) > 0);
    printf("%s seed=%u\n", fails ? "FAILED" : "OK", seed);
    return fails != 0;
}
