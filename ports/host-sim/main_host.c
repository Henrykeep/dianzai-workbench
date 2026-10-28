/**
 * host-sim 的 main：在电脑上跑任意应用。
 * 用法：./app.elf [仿真秒数=3] [在第几秒发送的命令行，例如 "1.5:S-1.5"]...
 * 遥测（应用写到 LINK 串口的内容）原样打印到标准输出。
 * 每仿真 1 ms 调一次 app_loop()，定时器回调按虚拟时间触发。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"

__attribute__((weak)) void host_sim_app_setup(void) { }

int main(int argc, char **argv)
{
    double secs = argc > 1 ? atof(argv[1]) : 3.0;
    host_sim_reset();
    host_sim_set_reset_cause(PAL_RESET_POWER_ON);
    host_sim_app_setup();
    dz_err_t e = pal_init();
    if (e == DZ_OK) e = app_init();
    if (e != DZ_OK) { fprintf(stderr, "init failed: %s\n", dz_err_str(e)); return 2; }
    uint64_t end_ms = (uint64_t)(secs * 1000.0);
    for (uint64_t ms = 0; ms < end_ms; ms++) {
        for (int i = 2; i < argc; i++) {
            char *colon = strchr(argv[i], ':');
            if (colon && (uint64_t)(atof(argv[i]) * 1000.0) == ms) {
                char line[64]; snprintf(line, sizeof line, "%s\n", colon + 1);
#if defined(RES_UART_LINK)
                host_sim_uart_inject_rx(RES_UART_LINK, (const uint8_t *)line, (uint16_t)strlen(line));
#endif
            }
        }
        app_loop();
        host_sim_run_us(1000);
#if defined(RES_UART_LINK)
        uint8_t buf[512]; uint16_t n;
        while ((n = host_sim_uart_take_tx(RES_UART_LINK, buf, sizeof buf)) > 0) fwrite(buf, 1, n, stdout);
#endif
    }
    return 0;
}
