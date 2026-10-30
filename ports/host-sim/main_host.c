/**
 * host-sim 的 main：在电脑上跑任意应用。
 * 用法：./app.elf [仿真秒数=3] [在第几秒发送的命令行，例如 "1.5:S-1.5"]...
 *       ./app.elf --stream [倍速=1]   实时模式：标准输入的原始字节 → LINK 接收，LINK 发送 → 标准输出，
 *                                      按墙钟节拍运行到 stdin 关闭（桌面工作台 app/ 的“仿真板”就是它）。
 * 遥测（应用写到 LINK 串口的内容）原样打印到标准输出。
 * 每仿真 1 ms 调一次 app_loop()，定时器回调按虚拟时间触发。
 */
#define _POSIX_C_SOURCE 200809L   /* clock_gettime / nanosleep（实时模式） */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(__unix__) || defined(__APPLE__)
#define HOST_SIM_STREAM 1
#include <fcntl.h>
#include <time.h>
#include <unistd.h>
#elif defined(_WIN32)
#define HOST_SIM_STREAM 1
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#endif
#include "board_gen.h"
#include "host_sim.h"
#include "app.h"

__attribute__((weak)) void host_sim_app_setup(void) { }

#if defined(HOST_SIM_STREAM) && defined(RES_UART_LINK)
/* 实时模式：每 1 ms 虚拟时间对齐一次墙钟；stdin 非阻塞读，EOF 退出。 */
#if defined(_WIN32)
static int stream(double speed)
{
    /* Windows 版实时模式：管道无非阻塞 read，用 PeekNamedPipe 看有多少字节；二进制模式免得 \n 被改成 \r\n */
    HANDLE in = GetStdHandle(STD_INPUT_HANDLE);
    LARGE_INTEGER f, t0, now;
    uint64_t ms = 0;
    _setmode(0, _O_BINARY); _setmode(1, _O_BINARY);
    setvbuf(stdout, NULL, _IONBF, 0);
    timeBeginPeriod(1);
    QueryPerformanceFrequency(&f); QueryPerformanceCounter(&t0);
    for (;;) {
        uint8_t buf[512]; DWORD avail = 0, got = 0; uint16_t n;
        if (!PeekNamedPipe(in, NULL, 0, NULL, &avail, NULL)) return 0;   /* 上位机关了管道 */
        while (avail > 0) {
            if (!ReadFile(in, buf, avail < sizeof buf ? avail : (DWORD)sizeof buf, &got, NULL) || got == 0) return 0;
            host_sim_uart_inject_rx(RES_UART_LINK, buf, (uint16_t)got);
            avail -= got;
        }
        app_loop();
        host_sim_run_us(1000);
        while ((n = host_sim_uart_take_tx(RES_UART_LINK, buf, sizeof buf)) > 0)
            if (_write(1, buf, n) < 0) return 0;
        if (host_sim_wdg_bitten()) {
            fprintf(stderr, "host-sim: 看门狗 %u ms 没喂，真板此时已复位（复位原因 WATCHDOG）\n", (unsigned)host_sim_wdg_timeout_ms());
            return 86;
        }
        ms++;
        QueryPerformanceCounter(&now);
        double ahead_ms = (double)ms / speed - (double)(now.QuadPart - t0.QuadPart) * 1e3 / (double)f.QuadPart;
        if (ahead_ms > 1.0) Sleep((DWORD)ahead_ms);
    }
}
#else
static int stream(double speed)
{
    struct timespec t0, now;
    uint64_t ms = 0;
    fcntl(0, F_SETFL, fcntl(0, F_GETFL) | O_NONBLOCK);
    setvbuf(stdout, NULL, _IONBF, 0);
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (;;) {
        uint8_t buf[512]; ssize_t r; uint16_t n;
        while ((r = read(0, buf, sizeof buf)) > 0) host_sim_uart_inject_rx(RES_UART_LINK, buf, (uint16_t)r);
        if (r == 0) return 0;                                   /* 上位机关了管道 */
        app_loop();
        host_sim_run_us(1000);
        while ((n = host_sim_uart_take_tx(RES_UART_LINK, buf, sizeof buf)) > 0)
            if (write(1, buf, n) < 0) return 0;
        if (host_sim_wdg_bitten()) {                            /* 仿真没法真复位：报出来并退出，上位机看到心跳断 */
            fprintf(stderr, "host-sim: 看门狗 %u ms 没喂，真板此时已复位（复位原因 WATCHDOG）\n", (unsigned)host_sim_wdg_timeout_ms());
            return 86;
        }
        ms++;
        clock_gettime(CLOCK_MONOTONIC, &now);
        double ahead_ms = (double)ms / speed - ((double)(now.tv_sec - t0.tv_sec) * 1e3 + (double)(now.tv_nsec - t0.tv_nsec) / 1e6);
        if (ahead_ms > 0.2) { struct timespec d = { 0, (long)(ahead_ms * 1e6) }; nanosleep(&d, NULL); }
    }
}
#endif
#endif

int main(int argc, char **argv)
{
    double secs = argc > 1 ? atof(argv[1]) : 3.0;
    host_sim_reset();
    host_sim_set_reset_cause(PAL_RESET_POWER_ON);
    host_sim_app_setup();
    dz_err_t e = pal_init();
    if (e == DZ_OK) e = app_init();
    if (e != DZ_OK) { fprintf(stderr, "init failed: %s\n", dz_err_str(e)); return 2; }
#if defined(HOST_SIM_STREAM) && defined(RES_UART_LINK)
    if (argc > 1 && strcmp(argv[1], "--stream") == 0) return stream(argc > 2 && atof(argv[2]) > 0 ? atof(argv[2]) : 1.0);
#endif
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
