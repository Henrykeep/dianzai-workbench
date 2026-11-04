/* EasyLogger 移植（芯台 pal）：时间 = pal_millis；输出给 dz_log_set_sink 设的钩子；WARN 及以上同时写进 FlashDB 事件日志（掉电不丢）。 */
#include <stdio.h>
#include <string.h>
#include <elog.h>
#include "dz_store.h"
#include "pal.h"

static dz_log_sink_t s_sink;
static uint32_t s_irq;
void dz_log_set_sink(dz_log_sink_t sink) { s_sink = sink; }

ElogErrCode elog_port_init(void) { return ELOG_NO_ERR; }
void elog_port_deinit(void) {}
void elog_port_output(const char *log, size_t size)
{
    char line[DZ_EVENT_MAX];
    size_t n;
    if (s_sink) s_sink(log, size);
    if (size > 2 && (log[0] == 'A' || log[0] == 'E' || log[0] == 'W') && log[1] == '/') {
        n = size < sizeof line - 1 ? size : sizeof line - 1;
        memcpy(line, log, n); line[n] = 0;
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = 0;
        (void)dz_event_log(line);
    }
}
void elog_port_output_lock(void) { s_irq = pal_irq_save(); }
void elog_port_output_unlock(void) { pal_irq_restore(s_irq); }
const char *elog_port_get_time(void)
{
    static char t[16];
    snprintf(t, sizeof t, "%lu", (unsigned long)pal_millis());
    return t;
}
const char *elog_port_get_p_info(void) { return ""; }
const char *elog_port_get_t_info(void) { return ""; }
